"""Small building blocks the pages share: a scrolling area, a white card, text that wraps to
the space it has, a main action button, and a section that opens and closes."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from .theme import Theme


class ScrollFrame(tk.Frame):
    """A frame that scrolls up and down. Put content in `.body`."""

    def __init__(self, parent, theme: Theme, bg: str | None = None) -> None:
        bg = bg or theme.background1
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        bar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))

    def wheel(self, event) -> None:
        """Called by enable_wheel() when the mouse wheel turns over this area."""
        if self.body.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def scroll_to(self, fraction: float) -> None:
        self.update_idletasks()
        self.canvas.yview_moveto(fraction)

    def clear(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        self.canvas.yview_moveto(0)


def enable_wheel(window) -> None:
    """Make the mouse wheel scroll whichever ScrollFrame the pointer is over. Call once."""
    def route(event) -> None:
        widget = window.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if isinstance(widget, ScrollFrame):
                widget.wheel(event)
                return
            widget = widget.master
    window.bind_all("<MouseWheel>", route)


def card(parent, theme: Theme, bg: str | None = None, **pack) -> tk.Frame:
    """A bordered panel, already packed. Returns the padded inside to put content in."""
    bg = bg or theme.card
    outer = tk.Frame(parent, bg=bg, highlightbackground=theme.line, highlightthickness=1)
    outer.pack(**{"fill": "x", "padx": 10, "pady": 6, **pack})
    inner = tk.Frame(outer, bg=bg)
    inner.pack(fill="both", expand=True, padx=14, pady=10)
    return inner


def text(parent, words: str, theme: Theme, font=None, fg: str | None = None, **pack) -> tk.Label:
    """A left-aligned label that re-wraps to the width it is given. Already packed."""
    label = tk.Label(parent, text=words, bg=parent.cget("bg"), fg=fg or theme.colour1,
                     font=font or theme.text_font(), justify="left", anchor="w")
    label.pack(**{"fill": "x", "anchor": "w", **pack})
    label.bind("<Configure>", lambda e: label.configure(wraplength=max(e.width - 4, 80)))
    return label


def action_button(parent, words: str, command: Callable[[], None], theme: Theme,
                  main: bool = True) -> tk.Button:
    """Main = the one thing to press next (green); otherwise a quiet secondary button."""
    if main:
        return tk.Button(parent, text=words, command=command, font=theme.bold_font(), bg=theme.good,
                         fg="white", activebackground=theme.good_soft, relief="flat", padx=16,
                         pady=4, cursor="hand2")
    return tk.Button(parent, text=words, command=command, font=theme.text_font(), bg=theme.card,
                     fg=theme.colour1, activebackground=theme.active_background, relief="groove",
                     padx=10, pady=2, cursor="hand2")


def entry_box(parent, theme: Theme, value: str = "", width: int = 12) -> tk.Entry:
    """A box to type in, with a border that shows on any background."""
    box = tk.Entry(parent, width=width, font=theme.text_font(), relief="flat", highlightthickness=1,
                   highlightbackground=theme.muted, highlightcolor=theme.good)
    box.insert(0, value)
    return box


class Foldout(tk.Frame):
    """A heading that shows or hides what is under it. Put content in `.body`."""

    def __init__(self, parent, title: str, theme: Theme, is_open: bool = False) -> None:
        super().__init__(parent, bg=parent.cget("bg"))
        self.title, self.is_open = title, is_open
        self.button = tk.Button(self, command=self.toggle, font=theme.text_font(), bg=self.cget("bg"),
                                fg=theme.colour1, activebackground=theme.active_background,
                                relief="flat", anchor="w", cursor="hand2", padx=0)
        self.button.pack(fill="x")
        self.body = tk.Frame(self, bg=self.cget("bg"))
        self._show()

    def toggle(self) -> None:
        self.is_open = not self.is_open
        self._show()

    def _show(self) -> None:
        self.button.config(text=("▼  " if self.is_open else "▶  ") + self.title)
        if self.is_open:
            self.body.pack(fill="x", padx=(18, 0))
        else:
            self.body.pack_forget()
