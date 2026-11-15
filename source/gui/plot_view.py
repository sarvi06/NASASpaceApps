"""One plot: its details (size, location, last rotation) and the tabs that work on it.

Location: the farmer types a zip code and presses "Find location", which fills in the latitude
and longitude of the centre of that zip area. Both boxes stay editable, because soil and crop
history are looked up at one exact point: a farmer who knows where the field is can correct them.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.ttk as ttk
from typing import Callable

from data_pullers.US_ZipCode_pull import check_zip, describe, get_zip_location

from .plots import PlotStore
from .runner import Runner
from .tabs import TABS
from .theme import Theme

# Two lines of boxes, each (attribute of Plot, label, entry width): what the plot is, then where.
DETAILS = ((("name", "Name", 14), ("size_ha", "Size (ha)", 7),
            ("last_rotation", "Last rotation, oldest first", 30)),
           (("zip_code", "US zip code", 9), ("lat", "Latitude", 10),
            ("lon", "Longitude (west is -)", 10)))
HINT = ("Type the plot's zip code and press 'Find location', or enter its latitude and longitude "
        "(e.g. 42.065, -93.73). Last rotation: e.g. corn, soybean. Then press Save.")
FOUND = ("{place}. The latitude and longitude are the centre of that zip area: change them to "
         "your field's exact position for field-level soil and crop history. Then press Save.")
PROBLEM_COLOUR = "#a01818"


def _shown(value) -> str:
    """A Plot value as text for an entry box."""
    if value is None:
        return ""
    if isinstance(value, tuple):
        return ", ".join(value)
    return f"{value:g}" if isinstance(value, float) else str(value)


class PlotView(tk.Frame):
    def __init__(self, parent, store: PlotStore, index: int, theme: Theme,
                 on_change: Callable[[], None]) -> None:
        super().__init__(parent, bg=theme.background1)
        self.store, self.index, self.theme, self.on_change = store, index, theme, on_change
        font = theme.text_font()
        plot = store.plots[index]
        self.place = plot.place          # the name the zip code lookup gave, kept with the plot
        self.runner = Runner(self)

        details = tk.LabelFrame(self, text="Plot details", bg=theme.background1, fg=theme.colour1, font=font)
        details.pack(anchor="w", fill="x", padx=10, pady=(0, 4))
        self.boxes: dict[str, tk.Entry] = {}
        for line_number, line in enumerate(DETAILS):
            row = tk.Frame(details, bg=theme.background1)
            row.pack(anchor="w")
            column = 0
            for attribute, text, width in line:
                tk.Label(row, text=text, bg=theme.background1, fg=theme.colour1, font=font).grid(
                    row=0, column=column, padx=6, sticky="w")
                box = tk.Entry(row, width=width, font=font)
                box.insert(0, _shown(getattr(plot, attribute)))
                box.grid(row=1, column=column, padx=6, pady=(0, 6), sticky="w")
                self.boxes[attribute] = box
                column += 1
                if attribute == "zip_code":
                    self.find_button = tk.Button(row, text="Find location", command=self.find_location,
                                                 font=font, bg=theme.background1, fg=theme.colour1, padx=6)
                    self.find_button.grid(row=1, column=column, padx=(0, 12), pady=(0, 6))
                    column += 1
            if line_number == len(DETAILS) - 1:
                tk.Button(row, text="Save", command=self.save, font=font, bg=theme.background2,
                          fg="white", padx=10).grid(row=1, column=column, padx=12, pady=(0, 6))
        self.message = tk.Label(details, text=HINT, bg=theme.background1, fg=theme.colour1, font=font,
                                wraplength=800, justify="left")
        self.message.pack(anchor="w", padx=6, pady=(0, 4))

        style = ttk.Style(self)
        style.configure("Plot.TNotebook.Tab", font=font, padding=(14, 4))
        self.notebook = ttk.Notebook(self, style="Plot.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.tabs = [tab(self.notebook, plot, theme) for tab in TABS]
        for tab in self.tabs:
            self.notebook.add(tab, text=tab.title)

    def say(self, text: str, problem: bool = False) -> None:
        self.message.config(text=text, fg=PROBLEM_COLOUR if problem else self.theme.colour1)

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
        if f"(zip {typed['zip_code'].strip()})" not in self.place:   # zip changed since the lookup
            self.place = ""
        try:
            plot = self.store.update(self.index, **typed, place=self.place)
        except ValueError as exc:
            self.say(str(exc), problem=True)
            return
        self.say("Saved.")
        for tab in self.tabs:
            tab.set_plot(plot)
        self.on_change()
