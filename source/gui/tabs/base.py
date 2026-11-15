"""What every tab shares: the settings row, the "your numbers" table, the Run button, the
progress line and the results box.

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
from ..runner import Runner
from ..theme import Theme

YEARS_OF_DATA = 10
NUMBER_ROWS = 3
INTRO_WIDTH = 760     # pixels the intro line wraps at (the tab is about 800 wide)
NUMBER_COLUMNS = (("price", "Price (USD per tonne)"), ("yield", "Yield (tonnes per ha)"),
                  ("cost", "Cost (USD per ha)"))
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
    """The settings every back-end call takes, from the plot and the shared settings row."""
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
    """Rows of (crop, price, yield, cost) as typed -> the back end's farm_numbers, or None if
    nothing was entered. Empty cells are skipped."""
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
    return out or None


class BaseTab(tk.Frame):
    title = "Tab"
    intro = ""

    def __init__(self, parent, plot: Plot, theme: Theme) -> None:
        super().__init__(parent, bg=theme.background1)
        self.plot, self.theme = plot, theme
        self.font = theme.text_font()
        self.runner = Runner(self)
        self.last_result = None
        self._build()

    # ---- for subclasses ----
    def build_inputs(self, frame: tk.Frame) -> None:
        """Add this tab's own inputs to `frame` (default: none)."""

    def crops_to_prefill(self) -> list[str]:
        """Crop names to put in the 'Your numbers' table to start with."""
        return []

    def request(self, common: dict, numbers: dict | None) -> Request:
        raise NotImplementedError

    # ---- shared layout ----
    def label(self, parent, text: str, **options) -> tk.Label:
        return tk.Label(parent, text=text, bg=self.theme.background1, fg=self.theme.colour1,
                        font=self.font, **options)

    def entry(self, parent, value: str = "", width: int = 12) -> tk.Entry:
        box = tk.Entry(parent, width=width, font=self.font)
        box.insert(0, value)
        return box

    def _build(self) -> None:
        pad = {"padx": 10, "pady": 3}
        self.label(self, self.intro, wraplength=INTRO_WIDTH, justify="left", anchor="w").pack(anchor="w", **pad)

        own = tk.Frame(self, bg=self.theme.background1)
        own.pack(anchor="w", fill="x", **pad)
        self.build_inputs(own)

        settings = tk.Frame(self, bg=self.theme.background1)
        settings.pack(anchor="w", **pad)
        start, end = default_dates()
        self.start_date, self.end_date = self.entry(settings, start, 11), self.entry(settings, end, 11)
        self.priority = ttk.Combobox(settings, values=sorted(PRIORITY_PRESETS), state="readonly",
                                     width=13, font=self.font)
        self.priority.set("balanced")
        self.years = ttk.Spinbox(settings, from_=1, to=4, width=3, font=self.font)
        self.years.set(3)
        self.irrigated = tk.BooleanVar(value=False)
        watered = tk.Checkbutton(settings, text="Irrigated", variable=self.irrigated, font=self.font,
                                 bg=self.theme.background1, fg=self.theme.colour1,
                                 activebackground=self.theme.background1)
        for text, widget in (("Data from", self.start_date), ("to", self.end_date),
                             ("Priority", self.priority), ("Years", self.years), ("", watered)):
            if text:
                self.label(settings, text).pack(side="left", padx=(0, 4))
            widget.pack(side="left", padx=(0, 12))

        self._build_numbers().pack(anchor="w", **pad)

        actions = tk.Frame(self, bg=self.theme.background1)
        actions.pack(anchor="w", fill="x", **pad)
        self.run_button = tk.Button(actions, text="Find rotations", command=self.run, font=self.font,
                                    bg=self.theme.background2, fg="white",
                                    activebackground=self.theme.active_background, padx=12)
        self.run_button.pack(side="left")
        self.open_button = tk.Button(actions, text="Open report in its own window", font=self.font,
                                     command=self.open_report, state="disabled",
                                     bg=self.theme.background1, fg=self.theme.colour1)
        self.open_button.pack(side="right")
        self.status = self.label(actions, "", wraplength=420, justify="left")
        self.status.pack(side="left", padx=12)

        self.results = ScrolledText(self, wrap="word", font=self.theme.report_text_font(), height=10,
                                    state="disabled")
        self.results.pack(fill="both", expand=True, padx=10, pady=(3, 10))

    def _build_numbers(self) -> tk.Frame:
        """The optional table of the farmer's own price, yield and cost per crop."""
        frame = tk.LabelFrame(self, text="Your numbers (optional; they replace the national averages)",
                              bg=self.theme.background1, fg=self.theme.colour1, font=self.font)
        for column, heading in enumerate(["Crop"] + [text for _, text in NUMBER_COLUMNS]):
            self.label(frame, heading).grid(row=0, column=column, padx=6, sticky="w")
        prefill = self.crops_to_prefill()
        self.number_rows = []
        for row in range(NUMBER_ROWS):
            cells = [self.entry(frame, prefill[row] if row < len(prefill) else "", 16)]
            cells += [self.entry(frame, "", 16) for _ in NUMBER_COLUMNS]
            for column, cell in enumerate(cells):
                cell.grid(row=row + 1, column=column, padx=6, pady=1)
            self.number_rows.append(cells)
        return frame

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
        self.open_button.config(state="normal")
        self.show_status(f"Done: {len(recommendation.rotations)} option(s) below.")
        self.show_results(recommendation.to_text())

    def open_report(self) -> None:
        """Show the last report in a large window of its own, for easier reading."""
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
        self.status.config(text=message, fg="#a01818" if problem else self.theme.colour1)

    def show_results(self, text: str) -> None:
        self.results.config(state="normal")
        self.results.delete("1.0", "end")
        self.results.insert("1.0", text)
        self.results.config(state="disabled")

    def set_plot(self, plot: Plot) -> None:
        """Called when the plot's details are saved."""
        self.plot = plot
