"""One plot: a one-line summary, its details (folded away once they are filled in), and the
tabs that work on it.

Location: the farmer types a zip code and presses "Find location", which fills in the latitude
and longitude of the centre of that zip area. Both boxes stay editable, because soil and crop
history are looked up at one exact point: a farmer who knows where the field is can correct them.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.ttk as ttk
from typing import Callable

from data_pullers.US_ZipCode_pull import check_zip, describe, get_zip_location

from .plots import Plot, PlotStore, acres_text, last_grown_text, parse_acres, size_text, where_text
from .runner import Runner
from .tabs import TABS
from .theme import Theme
from .widgets import action_button, card, entry_box, text

# Two lines of boxes, each (attribute of Plot, label, entry width): what the plot is, then where.
DETAILS = ((("name", "Name", 16), ("size_ha", "Size (acres)", 10),
            ("last_rotation", "What it grew last, oldest first (e.g. corn, soybean)", 34)),
           (("zip_code", "US zip code", 9), ("lat", "Latitude", 10),
            ("lon", "Longitude (west is -)", 10)))
HINT = ("Type the plot's zip code and press 'Find location'. If you know the field's own latitude "
        "and longitude, type those in instead. Then press Save.")
FOUND = ("{place}. The latitude and longitude are the centre of that zip area: change them to "
         "your field's exact position for field-level soil and crop history. Then press Save.")


def _shown(value) -> str:
    """A Plot value as text for an entry box."""
    if value is None:
        return ""
    if isinstance(value, tuple):
        return ", ".join(value)
    return f"{value:g}" if isinstance(value, float) else str(value)


def _shown_value(plot: Plot, attribute: str) -> str:
    """What the entry for this detail starts with (the size is shown in acres, stored in hectares)."""
    if attribute == "size_ha":
        return acres_text(plot.size_ha)
    return _shown(getattr(plot, attribute))


def summary(plot: Plot) -> str:
    """'30 acres (12 ha)  |  near Ames, Iowa (zip 50010)  |  last grew corn, then soybean'"""
    return "   |   ".join((size_text(plot), where_text(plot), last_grown_text(plot)))


class PlotView(tk.Frame):
    def __init__(self, parent, store: PlotStore, index: int, theme: Theme,
                 on_change: Callable[[], None]) -> None:
        super().__init__(parent, bg=theme.background1)
        self.store, self.index, self.theme, self.on_change = store, index, theme, on_change
        plot = store.plots[index]
        self.place = plot.place          # the name the zip code lookup gave, kept with the plot
        self.runner = Runner(self)

        head = tk.Frame(self, bg=theme.background1)
        head.pack(fill="x", padx=10)
        self.edit_button = action_button(head, "", self.toggle_details, theme, main=False)
        self.edit_button.pack(side="right", anchor="n", pady=4)
        self.title = tk.Label(head, text=plot.name, bg=theme.background1, fg=theme.colour1,
                              font=theme.title_font(), anchor="w")
        self.title.pack(fill="x")
        self.summary = text(head, summary(plot), theme, fg=theme.muted)

        self.details_open = not plot.located          # nothing to do until the plot has a location
        self.details = tk.Frame(self, bg=theme.background1)
        box = card(self.details, theme)
        self.boxes: dict[str, tk.Entry] = {}
        for line_number, line in enumerate(DETAILS):
            row = tk.Frame(box, bg=box.cget("bg"))
            row.pack(anchor="w")
            column = 0
            for attribute, words, width in line:
                tk.Label(row, text=words, bg=row.cget("bg"), fg=theme.muted, font=theme.small_font()).grid(
                    row=0, column=column, padx=(0, 12), sticky="w")
                entry = entry_box(row, theme, _shown_value(plot, attribute), width)
                entry.grid(row=1, column=column, padx=(0, 12), pady=(0, 6), sticky="w")
                self.boxes[attribute] = entry
                column += 1
                if attribute == "zip_code":
                    self.find_button = action_button(row, "Find location", self.find_location, theme, main=False)
                    self.find_button.grid(row=1, column=column, padx=(0, 16), pady=(0, 6))
                    column += 1
            if line_number == len(DETAILS) - 1:
                action_button(row, "Save", self.save, theme).grid(row=1, column=column, padx=8, pady=(0, 6))
        self.message = text(box, HINT, theme, fg=theme.muted)

        style = ttk.Style(self)
        style.configure("Plot.TNotebook.Tab", font=theme.bold_font(), padding=(16, 6))
        self.notebook = ttk.Notebook(self, style="Plot.TNotebook")
        self.tabs = [tab(self.notebook, plot, theme) for tab in TABS]
        for tab in self.tabs:
            self.notebook.add(tab, text=tab.title)
        self._arrange()

    def _arrange(self) -> None:
        """Show the details form or fold it away, keeping the tabs underneath."""
        self.edit_button.config(text="Hide plot details" if self.details_open else "Edit plot details")
        self.details.pack_forget()
        self.notebook.pack_forget()
        if self.details_open:
            self.details.pack(fill="x")
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(6, 6))

    def toggle_details(self) -> None:
        self.details_open = not self.details_open
        self._arrange()

    def say(self, words: str, problem: bool = False) -> None:
        self.message.config(text=words, fg=self.theme.problem if problem else self.theme.colour1)

    # ---- zip code -> latitude and longitude ----
    def find_location(self) -> None:
        """Look the zip code up (in the background) and fill in latitude and longitude."""
        if self.runner.busy:
            return
        try:
            code = check_zip(self.boxes["zip_code"].get())
        except ValueError as exc:
            self.say(str(exc), problem=True)
            return
        self.find_button.config(state="disabled")
        self.say(f"Looking up zip code {code}...")
        self.runner.start(lambda report: get_zip_location(code), on_progress=self.say,
                          on_done=self.show_location, on_error=self._lookup_failed)

    def show_location(self, location: dict) -> None:
        self.find_button.config(state="normal")
        self.place = describe(location)
        for attribute in ("zip_code", "lat", "lon"):
            self.boxes[attribute].delete(0, "end")
        self.boxes["zip_code"].insert(0, location["zip"])
        self.boxes["lat"].insert(0, f"{location['lat']:g}")
        self.boxes["lon"].insert(0, f"{location['lon']:g}")
        self.say(FOUND.format(place=self.place))

    def _lookup_failed(self, exc: Exception) -> None:
        self.find_button.config(state="normal")
        expected = isinstance(exc, ValueError)                      # e.g. no such zip code
        self.say(str(exc) if expected else f"Could not look the zip code up ({exc}). Check your "
                 f"internet connection, or enter the latitude and longitude yourself.", problem=True)

    # ---- saving ----
    def save(self) -> None:
        """Store the details typed in; show a plain message if something is wrong."""
        typed = {name: box.get() for name, box in self.boxes.items()}
        try:
            typed["size_ha"] = parse_acres(typed["size_ha"])      # typed in acres, stored in hectares
        except ValueError as exc:
            self.say(str(exc), problem=True)
            return
        if f"(zip {typed['zip_code'].strip()})" not in self.place:   # zip changed since the lookup
            self.place = ""
        try:
            plot = self.store.update(self.index, **typed, place=self.place)
        except ValueError as exc:
            self.say(str(exc), problem=True)
            return
        self.say("Saved." if plot.located else "Saved. Add a location to get rotations for this plot.")
        self.title.config(text=plot.name)
        self.summary.config(text=summary(plot))
        for tab in self.tabs:
            tab.set_plot(plot)
        self.on_change()
