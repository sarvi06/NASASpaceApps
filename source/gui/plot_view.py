"""One plot: its details (size, location, last rotation) and the tabs that work on it."""

from __future__ import annotations

import tkinter as tk
import tkinter.ttk as ttk
from typing import Callable

from .plots import PlotStore
from .tabs import TABS
from .theme import Theme

# (attribute of Plot, label, entry width)
DETAILS = (("name", "Name", 14), ("size_ha", "Size (ha)", 7), ("lat", "Latitude", 9),
           ("lon", "Longitude", 9), ("last_rotation", "Last rotation, oldest first", 26))


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

        details = tk.LabelFrame(self, text="Plot details", bg=theme.background1, fg=theme.colour1, font=font)
        details.pack(anchor="w", fill="x", padx=10, pady=(0, 4))
        self.boxes: dict[str, tk.Entry] = {}
        for column, (attribute, text, width) in enumerate(DETAILS):
            tk.Label(details, text=text, bg=theme.background1, fg=theme.colour1, font=font).grid(
                row=0, column=column, padx=6, sticky="w")
            box = tk.Entry(details, width=width, font=font)
            box.insert(0, _shown(getattr(plot, attribute)))
            box.grid(row=1, column=column, padx=6, pady=(0, 6))
            self.boxes[attribute] = box
        tk.Button(details, text="Save", command=self.save, font=font, bg=theme.background2,
                  fg="white", padx=10).grid(row=1, column=len(DETAILS), padx=8, pady=(0, 6))
        self.message = tk.Label(details, text="e.g. latitude 42.065, longitude -93.73; last rotation: corn, soybean",
                                bg=theme.background1, fg=theme.colour1, font=font,
                                wraplength=820, justify="left")
        self.message.grid(row=2, column=0, columnspan=len(DETAILS) + 1, padx=6, pady=(0, 4), sticky="w")

        style = ttk.Style(self)
        style.configure("Plot.TNotebook.Tab", font=font, padding=(14, 4))
        self.notebook = ttk.Notebook(self, style="Plot.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.tabs = [tab(self.notebook, plot, theme) for tab in TABS]
        for tab in self.tabs:
            self.notebook.add(tab, text=tab.title)

    def save(self) -> None:
        """Store the details typed in; show a plain message if something is wrong."""
        try:
            plot = self.store.update(self.index, **{name: box.get() for name, box in self.boxes.items()})
        except ValueError as exc:
            self.message.config(text=str(exc), fg="#a01818")
            return
        self.message.config(text="Saved.", fg=self.theme.colour1)
        for tab in self.tabs:
            tab.set_plot(plot)
        self.on_change()
