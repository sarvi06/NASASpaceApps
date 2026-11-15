"""The home page's side bar: one button per plot, and "Add plot" (up to the maximum)."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable

from .plots import DEFAULT_SIZE_HA, MAX_PLOTS, PlotStore
from .theme import Theme

ICON_FILE = Path(__file__).resolve().parents[2] / "images" / "plot1icon.png"
ICON_BOX = (13, 10, 72, 69)      # where the icon sits inside the "Plot 1" button picture
SIDEBAR_WIDTH = 400


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
    """"Plot Selection": click a plot to open it."""

    def __init__(self, parent, store: PlotStore, theme: Theme, on_select: Callable[[int], None]) -> None:
        super().__init__(parent, bg=theme.background2, width=SIDEBAR_WIDTH)
        self.pack_propagate(False)                   # keep the set width whatever is inside
        self.store, self.theme, self.on_select = store, theme, on_select
        self.icon = load_icon(self)                  # kept here so it is not garbage-collected
        self.selected = tk.IntVar(self, value=-1)    # index of the open plot; -1 = home page
        self.font = theme.big_font()

        tk.Label(self, text="Plot Selection", bg=theme.background2, fg=theme.colour1,
                 font=theme.title_font()).pack(pady=(14, 8), padx=10)
        self.buttons = tk.Frame(self, bg=theme.background2)
        self.buttons.pack(fill="x")
        self.add_button = tk.Button(self, command=self._add_plot, font=theme.text_font(),
                                    bg=theme.background1, fg=theme.colour1,
                                    activebackground=theme.active_background)
        self.add_button.pack(pady=8)
        self.refresh()

    def refresh(self) -> None:
        """Redraw the plot buttons from the store."""
        for old in self.buttons.winfo_children():
            old.destroy()
        for index, plot in enumerate(self.store.plots):
            tk.Radiobutton(
                self.buttons, text=f"  {plot.name}  ({plot.size_ha:g} ha)", image=self.icon or "",
                compound="left", anchor="w", variable=self.selected, value=index,
                indicatoron=False, command=lambda i=index: self.on_select(i), font=self.font,
                bg=self.theme.background2, fg=self.theme.light, selectcolor=self.theme.colour1,
                activebackground=self.theme.active_background, bd=0, highlightthickness=0,
                cursor="hand2",
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
        self.name, self.size = tk.Entry(self, font=font, width=22), tk.Entry(self, font=font, width=22)
        self.name.insert(0, store.next_name())
        self.size.insert(0, f"{DEFAULT_SIZE_HA:g}")
        for row, (text, box) in enumerate((("Name", self.name), ("Size (hectares)", self.size))):
            tk.Label(self, text=text, bg=theme.background1, fg=theme.colour1, font=font).grid(
                row=row, column=0, padx=12, pady=6, sticky="w")
            box.grid(row=row, column=1, padx=12, pady=6)
        self.problem = tk.Label(self, text="", bg=theme.background1, fg="#a01818", font=font,
                                wraplength=360, justify="left")
        self.problem.grid(row=2, column=0, columnspan=2, padx=12, sticky="w")
        tk.Button(self, text="Add plot", command=self.add, font=font, bg=theme.background2,
                  fg="white").grid(row=3, column=0, columnspan=2, pady=10)
        self.bind("<Return>", lambda event: self.add())
        self.name.focus_set()

    def add(self) -> None:
        try:
            self.store.add(self.name.get(), self.size.get())
        except ValueError as exc:
            self.problem.config(text=str(exc))
            return
        self.on_added()
        self.destroy()


class Welcome(tk.Frame):
    """What the main area shows before a plot is opened."""

    def __init__(self, parent, theme: Theme) -> None:
        super().__init__(parent, bg=theme.background1)
        tk.Label(self, text="Satellite Support for Farming", bg=theme.background1, fg=theme.colour1,
                 font=theme.title_font()).pack(anchor="w", padx=30, pady=(40, 10))
        tk.Label(self, bg=theme.background1, fg=theme.colour1, font=theme.text_font(), justify="left",
                 text=("Choose a plot on the left to open it.\n\n"
                       "For each plot you can set its size and location, then:\n"
                       "   Budget  -  find rotations that fit what you can spend a year\n"
                       "   Crop planting  -  build a rotation around crops you want to grow\n"
                       "   Rotation  -  see the best rotations for the plot\n\n"
                       f"Use \"Add plot\" for more plots, up to {MAX_PLOTS}.")
                 ).pack(anchor="w", padx=30)
