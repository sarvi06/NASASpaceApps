"""The side bar (one button per plot, "Add plot") and the home page shown before a plot is opened.

The home page says what the tool does in three steps, shows every plot as a card with what is
known about it, and says where the numbers come from.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable

from .plots import (DEFAULT_SIZE_HA, MAX_PLOTS, PlotStore, acres_text, last_grown_text, parse_acres,
                    size_text, where_text)
from .theme import Theme
from .widgets import ScrollFrame, action_button, card, entry_box, text

ICON_FILE = Path(__file__).resolve().parents[2] / "images" / "plot1icon.png"
ICON_BOX = (13, 10, 72, 69)      # where the icon sits inside the "Plot 1" button picture
SIDEBAR_WIDTH = 300
CARD_COLUMNS = 2

STEPS = (("1", "Add your field", "Open a plot and type its zip code. The tool looks up the weather "
                                 "(NASA), the soil and what has been grown there (USDA)."),
         ("2", "Say what matters", "Saving water, building soil, earning more, a budget to stay "
                                   "within, or crops you want to keep growing."),
         ("3", "Compare rotations", "See three rotations next to what you grow now: a calendar, "
                                    "scores, income, what you gain and what to check first."))
SOURCES = ("Weather: NASA POWER.  Soil: USDA soil survey (SSURGO).  Crop history: USDA CropScape.  "
           "Crop needs: FAO EcoCrop.  Prices and yields: FAOSTAT, United States.  "
           "Covers the 48 contiguous US states.")
SUPPORT = ("This tool points out patterns and options. It does not replace your own judgement or "
           "local advice: check any change with an agronomist or extension service first.")


def _sentence(words: str) -> str:
    """First letter in capitals, the rest untouched (place names keep theirs)."""
    return words[:1].upper() + words[1:]


def load_icon(master) -> tk.PhotoImage | None:
    """The plot icon cut out of the button picture, so each button can carry its own name
    as text. None if the picture is missing (buttons then show text only)."""
    try:
        picture = tk.PhotoImage(master=master, file=str(ICON_FILE))
    except tk.TclError:
        return None
    icon = tk.PhotoImage(master=master)
    icon.tk.call(icon, "copy", picture, "-from", *ICON_BOX)
    return icon


class Sidebar(tk.Frame):
    """"Your plots": click a plot to open it, "Home" to go back to the first page."""

    def __init__(self, parent, store: PlotStore, theme: Theme, on_select: Callable[[int], None],
                 on_home: Callable[[], None] | None = None) -> None:
        super().__init__(parent, bg=theme.background2, width=SIDEBAR_WIDTH)
        self.pack_propagate(False)                   # keep the set width whatever is inside
        self.store, self.theme, self.on_select = store, theme, on_select
        self.on_home = on_home or (lambda: None)
        self.icon = load_icon(self)                  # kept here so it is not garbage-collected
        self.selected = tk.IntVar(self, value=-1)    # index of the open plot; -1 = home page

        tk.Button(self, text="⌂  Home", command=self.go_home, font=theme.text_font(),
                  bg=theme.background2, fg="white", activebackground=theme.active_background,
                  relief="flat", anchor="w", cursor="hand2").pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(self, text="Your plots", bg=theme.background2, fg=theme.colour1,
                 font=theme.title_font()).pack(pady=(6, 8), padx=14, anchor="w")
        self.buttons = tk.Frame(self, bg=theme.background2)
        self.buttons.pack(fill="x")
        self.add_button = tk.Button(self, command=self._add_plot, font=theme.text_font(),
                                    bg=theme.background1, fg=theme.colour1,
                                    activebackground=theme.active_background, cursor="hand2")
        self.add_button.pack(pady=10)
        self.refresh()

    def go_home(self) -> None:
        self.selected.set(-1)
        self.on_home()

    def refresh(self) -> None:
        """Redraw the plot buttons from the store."""
        for old in self.buttons.winfo_children():
            old.destroy()
        for index, plot in enumerate(self.store.plots):
            tk.Radiobutton(
                self.buttons, text=f" {plot.name}\n {acres_text(plot.size_ha)} acres", image=self.icon or "",
                compound="left", anchor="w", justify="left", variable=self.selected, value=index,
                indicatoron=False, command=lambda i=index: self.on_select(i),
                font=self.theme.heading_font(), bg=self.theme.background2, fg="white",
                selectcolor=self.theme.colour1, activebackground=self.theme.active_background,
                bd=0, highlightthickness=0, cursor="hand2",
            ).pack(fill="x", padx=12, pady=1)
        left = MAX_PLOTS - len(self.store.plots)
        self.add_button.config(text=f"+ Add plot ({left} more allowed)" if left else f"Maximum of {MAX_PLOTS} plots",
                               state="normal" if left else "disabled")

    def _add_plot(self) -> None:
        AddPlotDialog(self, self.store, self.theme, on_added=self.refresh)


class AddPlotDialog(tk.Toplevel):
    """Asks for the new plot's name and size."""

    def __init__(self, parent, store: PlotStore, theme: Theme, on_added: Callable[[], None]) -> None:
        super().__init__(parent, bg=theme.background1)
        self.store, self.on_added = store, on_added
        self.title("Add plot")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        font = theme.text_font()
        self.name = entry_box(self, theme, store.next_name(), 22)
        self.size = entry_box(self, theme, acres_text(DEFAULT_SIZE_HA), 22)
        for row, (words, box) in enumerate((("Name", self.name), ("Size (acres)", self.size))):
            tk.Label(self, text=words, bg=theme.background1, fg=theme.colour1, font=font).grid(
                row=row, column=0, padx=12, pady=6, sticky="w")
            box.grid(row=row, column=1, padx=12, pady=6)
        self.problem = tk.Label(self, text="", bg=theme.background1, fg=theme.problem, font=font,
                                wraplength=360, justify="left")
        self.problem.grid(row=2, column=0, columnspan=2, padx=12, sticky="w")
        action_button(self, "Add plot", self.add, theme).grid(row=3, column=0, columnspan=2, pady=10)
        self.bind("<Return>", lambda event: self.add())
        self.name.focus_set()

    def add(self) -> None:
        try:
            self.store.add(self.name.get(), parse_acres(self.size.get()))
        except ValueError as exc:
            self.problem.config(text=str(exc))
            return
        self.on_added()
        self.destroy()


class Home(ScrollFrame):
    """The first page: what the tool does, the plots, and where the numbers come from."""

    def __init__(self, parent, store: PlotStore, theme: Theme, on_open: Callable[[int], None]) -> None:
        super().__init__(parent, theme)
        self.store, self.theme, self.on_open = store, theme, on_open
        body = self.body

        text(body, "Satellite Support for Farming", theme, font=theme.title_font(), padx=12, pady=(4, 0))
        text(body, "Field Shift: crop rotations for your fields, worked out from NASA weather data, the "
                   "USDA soil survey and what your land has grown before.", theme, padx=12, pady=(0, 6))

        steps = tk.Frame(body, bg=body.cget("bg"))
        steps.pack(fill="x", padx=4)
        for column, (number, title, words) in enumerate(STEPS):
            steps.columnconfigure(column, weight=1, uniform="step")
            holder = tk.Frame(steps, bg=body.cget("bg"))
            holder.grid(row=0, column=column, sticky="nsew")
            box = card(holder, theme, padx=6, expand=True, fill="both")
            head = tk.Frame(box, bg=box.cget("bg"))
            head.pack(fill="x")
            tk.Label(head, text=number, bg=theme.good, fg="white", font=theme.heading_font(),
                     width=2).pack(side="left", padx=(0, 8))
            tk.Label(head, text=title, bg=box.cget("bg"), fg=theme.colour1,
                     font=theme.heading_font()).pack(side="left")
            text(box, words, theme, pady=(6, 0))

        text(body, "Your plots", theme, font=theme.heading_font(), padx=12, pady=(10, 0))
        self.plots = tk.Frame(body, bg=body.cget("bg"))
        self.plots.pack(fill="x", padx=4)
        self.refresh()

        foot = card(body, theme, bg=theme.background1)
        text(foot, SUPPORT, theme, font=theme.bold_font())
        text(foot, SOURCES, theme, font=theme.small_font(), fg=theme.muted, pady=(6, 0))

    def refresh(self) -> None:
        """Redraw the plot cards from the store."""
        for old in self.plots.winfo_children():
            old.destroy()
        for index, plot in enumerate(self.store.plots):
            column = index % CARD_COLUMNS
            self.plots.columnconfigure(column, weight=1, uniform="plot")
            holder = tk.Frame(self.plots, bg=self.plots.cget("bg"))
            holder.grid(row=index // CARD_COLUMNS, column=column, sticky="nsew")
            box = card(holder, self.theme, padx=6, expand=True, fill="both")
            head = tk.Frame(box, bg=box.cget("bg"))
            head.pack(fill="x")
            ready = plot.located
            action_button(head, "Open" if ready else "Set up", lambda i=index: self.on_open(i),
                          self.theme, main=ready).pack(side="right")
            tk.Label(head, text=plot.name, bg=box.cget("bg"), fg=self.theme.colour1,
                     font=self.theme.heading_font(), anchor="w").pack(side="left")
            text(box, size_text(plot), self.theme, fg=self.theme.muted, pady=(2, 0))
            text(box, _sentence(where_text(plot)), self.theme,
                 fg=self.theme.colour1 if ready else self.theme.warn)
            text(box, _sentence(last_grown_text(plot)), self.theme, fg=self.theme.muted)
