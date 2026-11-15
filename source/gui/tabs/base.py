"""What every tab shares. A tab has two pages and shows one at a time:

  asking     the tab's own question, "what matters most", the farmer's own numbers and more
             settings (both folded away), and the "Find rotations" button
  answering  the results page (gui/results.py), with a button back to the question and one
             that opens the full written report

A tab is a small subclass of BaseTab that says
  title, intro        what it is called and one line on what it does
  build_inputs()      any inputs of its own (optional)
  request()           which back-end call to make from those inputs

The input checking is in plain functions (common_inputs, farm_numbers, and one per tab) that
need no window, so they can be tested directly.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.ttk as ttk
from dataclasses import dataclass
from datetime import date
from tkinter.scrolledtext import ScrolledText
from typing import Any, Callable, Iterable

from backend import PRIORITY_PRESETS

from ..plots import Plot
from ..results import ResultsView
from ..runner import Runner
from ..theme import Theme
from ..units import to_metric
from ..widgets import Foldout, ScrollFrame, action_button, entry_box, text

YEARS_OF_DATA = 10
NUMBER_ROWS = 3
NUMBER_COLUMNS = (("price", "Price (USD per bushel*)"), ("yield", "Yield (bushels per acre*)"),
                  ("cost", "Cost (USD per acre)"))
NUMBER_NOTE = ("* Crops not sold by the bushel (potato, tomato and most vegetables): use "
               "hundredweight (cwt, 100 lb) instead.")
# The back end's priorities in a farmer's words (a new preset shows under its own name).
PRIORITY_NAMES = {"balanced": "A balance of everything", "save_water": "Saving water",
                  "build_soil": "Building soil health", "extra_income": "Earning more"}
NO_LOCATION = ("Set this plot's location first (plot details, above): type its zip code and press "
               "'Find location', or enter its latitude and longitude, then press Save.")


@dataclass
class Request:
    """One back-end call, ready to run."""
    call: Callable[..., Any]
    kwargs: dict

    def run(self, on_progress: Callable[[str], None]):
        return self.call(**self.kwargs, on_progress=on_progress)


def default_dates(today: date | None = None) -> tuple[str, str]:
    """The last YEARS_OF_DATA complete years."""
    last_year = (today or date.today()).year - 1
    return f"{last_year - YEARS_OF_DATA + 1}-01-01", f"{last_year}-12-31"


def common_inputs(plot: Plot, start_date: str, end_date: str, priority: str, years,
                  irrigated: bool = False) -> dict:
    """The settings every back-end call takes, from the plot and the shared settings."""
    if not plot.located:
        raise ValueError(NO_LOCATION)
    try:
        years = int(str(years).strip())
    except ValueError:
        raise ValueError(f"Rotation length must be a whole number of years, got {years!r}.") from None
    inputs = {"lat": plot.lat, "lon": plot.lon, "start_date": start_date.strip(),
              "end_date": end_date.strip(), "priorities": priority, "rotation_years": years,
              "irrigated": bool(irrigated)}
    if plot.last_rotation:
        inputs["current_rotation"] = list(plot.last_rotation)
    if plot.place:
        inputs["place"] = plot.place
    return inputs


def farm_numbers(rows: Iterable[tuple[str, str, str, str]]) -> dict | None:
    """Rows of (crop, price, yield, cost) as typed, in US units (USD per bushel or cwt, bushels or
    cwt per acre, USD per acre) -> the back end's farm_numbers in metric (USD per tonne, tonnes per
    hectare, USD per hectare), or None if nothing was entered. Empty cells are skipped."""
    out: dict[str, dict[str, float]] = {}
    for crop, *cells in rows:
        crop = crop.strip()
        filled = {what: cell.strip() for (what, _), cell in zip(NUMBER_COLUMNS, cells) if cell.strip()}
        if not crop and not filled:
            continue
        if not crop:
            raise ValueError("A row in 'Your numbers' has figures but no crop name.")
        for what, cell in filled.items():
            try:
                out.setdefault(crop, {})[what] = float(cell.replace(",", ""))
            except ValueError:
                raise ValueError(f"The {what} for {crop} must be a number, got {cell!r}.") from None
    return {crop: to_metric(crop, figures) for crop, figures in out.items()} or None


class BaseTab(tk.Frame):
    title = "Tab"
    intro = ""
    numbers_open = False      # True = show the "your numbers" table straight away
    numbers_title = "Your own prices, yields and costs (optional: they replace the national averages)"

    def __init__(self, parent, plot: Plot, theme: Theme) -> None:
        super().__init__(parent, bg=theme.background1)
        self.plot, self.theme = plot, theme
        self.font = theme.text_font()
        self.runner = Runner(self)
        self.last_result = None
        self._build_asking()
        self._build_answering()
        self.show_page(self.asking)

    # ---- for subclasses ----
    def build_inputs(self, frame: tk.Frame) -> None:
        """Add this tab's own inputs to `frame` (default: none)."""

    def crops_to_prefill(self) -> list[str]:
        """Crop names to put in the 'Your numbers' table to start with."""
        return []

    def request(self, common: dict, numbers: dict | None) -> Request:
        raise NotImplementedError

    def label(self, parent, words: str, **options) -> tk.Label:
        return tk.Label(parent, text=words, bg=parent.cget("bg"), fg=self.theme.colour1,
                        font=self.font, **options)

    def entry(self, parent, value: str = "", width: int = 12) -> tk.Entry:
        return entry_box(parent, self.theme, value, width)

    # ---- the asking page ----
    def _build_asking(self) -> None:
        self.asking = ScrollFrame(self, self.theme)
        page, bg = self.asking.body, self.theme.background1
        text(page, self.intro, self.theme, padx=12, pady=(8, 4))

        own = tk.Frame(page, bg=bg)
        own.pack(anchor="w", fill="x", padx=12, pady=4)
        self.build_inputs(own)

        text(page, "What matters most to you?", self.theme, font=self.theme.bold_font(),
             padx=12, pady=(8, 0))
        choices = tk.Frame(page, bg=bg)
        choices.pack(anchor="w", padx=12)
        self.priority = tk.StringVar(self, value="balanced")
        for key in PRIORITY_PRESETS:
            tk.Radiobutton(choices, text=PRIORITY_NAMES.get(key, key.replace("_", " ")), value=key,
                           variable=self.priority, font=self.font, bg=bg, fg=self.theme.colour1,
                           activebackground=bg, selectcolor=self.theme.card, cursor="hand2",
                           ).pack(side="left", padx=(0, 14))

        actions = tk.Frame(page, bg=bg)
        actions.pack(anchor="w", fill="x", padx=12, pady=(12, 4))
        self.run_button = action_button(actions, "Find rotations", self.run, self.theme)
        self.run_button.pack(side="left")
        self.back_button = action_button(actions, "Back to the last results",
                                         lambda: self.show_page(self.answering), self.theme, main=False)
        self.status = tk.Label(actions, text="", bg=bg, fg=self.theme.colour1, font=self.font,
                               wraplength=520, justify="left", anchor="w")
        self.status.pack(side="left", padx=12)

        numbers = Foldout(page, self.numbers_title, self.theme, is_open=self.numbers_open)
        numbers.pack(fill="x", padx=12, pady=(8, 0))
        self._build_numbers(numbers.body)

        more = Foldout(page, "More settings (weather years, rotation length, irrigation)", self.theme)
        more.pack(fill="x", padx=12)
        self._build_settings(more.body)

    def _build_settings(self, frame: tk.Frame) -> None:
        row = tk.Frame(frame, bg=frame.cget("bg"))
        row.pack(anchor="w", pady=4)
        start, end = default_dates()
        self.start_date, self.end_date = self.entry(row, start, 11), self.entry(row, end, 11)
        self.years = ttk.Spinbox(row, from_=1, to=4, width=3, font=self.font)
        self.years.set(3)
        self.irrigated = tk.BooleanVar(self, value=False)
        watered = tk.Checkbutton(row, text="This plot is irrigated", variable=self.irrigated,
                                 font=self.font, bg=row.cget("bg"), fg=self.theme.colour1,
                                 activebackground=row.cget("bg"), selectcolor=self.theme.card)
        for words, widget in (("Use weather from", self.start_date), ("to", self.end_date),
                              ("Rotation length (years)", self.years), ("", watered)):
            if words:
                self.label(row, words).pack(side="left", padx=(0, 4))
            widget.pack(side="left", padx=(0, 14))

    def _build_numbers(self, frame: tk.Frame) -> None:
        """The optional table of the farmer's own price, yield and cost per crop."""
        table = tk.Frame(frame, bg=frame.cget("bg"))
        table.pack(anchor="w", pady=4)
        for column, heading in enumerate(["Crop"] + [words for _, words in NUMBER_COLUMNS]):
            tk.Label(table, text=heading, bg=table.cget("bg"), fg=self.theme.muted,
                     font=self.theme.small_font()).grid(row=0, column=column, padx=(0, 8), sticky="w")
        prefill = self.crops_to_prefill()
        self.number_rows = []
        for row in range(NUMBER_ROWS):
            cells = [self.entry(table, prefill[row] if row < len(prefill) else "", 16)]
            cells += [self.entry(table, "", 16) for _ in NUMBER_COLUMNS]
            for column, cell in enumerate(cells):
                cell.grid(row=row + 1, column=column, padx=(0, 8), pady=1)
            self.number_rows.append(cells)
        text(frame, NUMBER_NOTE, self.theme, font=self.theme.small_font(), fg=self.theme.muted)

    # ---- the answering page ----
    def _build_answering(self) -> None:
        self.answering = tk.Frame(self, bg=self.theme.background1)
        bar = tk.Frame(self.answering, bg=self.theme.background1)
        bar.pack(fill="x", padx=10, pady=(6, 0))
        action_button(bar, "←  Change what you asked", lambda: self.show_page(self.asking),
                      self.theme, main=False).pack(side="left")
        self.open_button = action_button(bar, "Open the full written report", self.open_report,
                                         self.theme, main=False)
        self.open_button.pack(side="right")
        self.outcome = tk.Label(bar, text="", bg=self.theme.background1, fg=self.theme.muted,
                                font=self.font, anchor="w")
        self.outcome.pack(side="left", padx=12)
        self.results = ResultsView(self.answering, self.theme)
        self.results.pack(fill="both", expand=True, pady=(4, 0))

    def show_page(self, page: tk.Widget) -> None:
        for other in (self.asking, self.answering):
            other.pack_forget()
        page.pack(fill="both", expand=True)
        self.page = page

    # ---- running ----
    def collect(self) -> Request:
        """Read every input and build the back-end call; ValueError if something is wrong."""
        common = common_inputs(self.plot, self.start_date.get(), self.end_date.get(),
                               self.priority.get(), self.years.get(), self.irrigated.get())
        numbers = farm_numbers(tuple(cell.get() for cell in row) for row in self.number_rows)
        return self.request(common, numbers)

    def run(self) -> None:
        if self.runner.busy:
            return
        try:
            request = self.collect()
        except ValueError as exc:
            self.show_status(str(exc), problem=True)
            return
        self.run_button.config(state="disabled")
        self.show_status("Starting...")
        self.runner.start(request.run, on_progress=self.show_status, on_done=self._done,
                          on_error=self._failed)

    def _done(self, recommendation) -> None:
        self.last_result = recommendation
        self.run_button.config(state="normal")
        found = f"{len(recommendation.rotations)} option(s) found"
        self.show_status(f"Done: {found}.")
        self.outcome.config(text=f"{found} for {self.plot.name}")
        self.back_button.pack(side="left", padx=(8, 0), before=self.status)
        self.results.show(recommendation.to_dict())
        self.show_page(self.answering)

    def open_report(self) -> None:
        """Show the last report as plain text in a window of its own (to read in full or copy)."""
        if self.last_result is None:
            return
        window = tk.Toplevel(self)
        window.title(f"{self.plot.name} - {self.title}")
        window.geometry("1100x750")
        box = ScrolledText(window, wrap="word", font=self.theme.report_text_font())
        box.insert("1.0", self.last_result.to_text())
        box.config(state="disabled")
        box.pack(fill="both", expand=True)

    def _failed(self, exc: Exception) -> None:
        self.run_button.config(state="normal")
        expected = isinstance(exc, (ValueError, RuntimeError))     # the back end's plain messages
        self.show_status(str(exc) if expected else f"Something went wrong: {exc!r}", problem=True)

    def show_status(self, message: str, problem: bool = False) -> None:
        self.status.config(text=message, fg=self.theme.problem if problem else self.theme.colour1)

    def set_plot(self, plot: Plot) -> None:
        """Called when the plot's details are saved."""
        self.plot = plot
