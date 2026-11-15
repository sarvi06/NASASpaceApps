"""The app's home page: the plot side bar on the left, the open plot (or a welcome note) on
the right.

Run from the repo root:
    .venv\\Scripts\\python.exe source\\user_interface.py

The side bar, a plot's details and its tabs live in source/gui/ (see gui/__init__.py).
"""

import tkinter as tk

from gui.home import Sidebar, Welcome
from gui.plot_view import PlotView
from gui.plots import PlotStore
from gui.theme import Theme


def build(theme: Theme, store: PlotStore | None = None) -> tk.Tk:
    """Create the window (without starting it), so it can also be built in tests."""
    store = store or PlotStore()
    window = tk.Tk()
    window.title("Satellite Support for Farming")
    window.configure(bg=theme.background1, cursor=theme.cursor)
    window.geometry("1300x800")

    content = tk.Frame(window, bg=theme.background1)

    def open_plot(index: int) -> None:
        for old in content.winfo_children():
            old.destroy()
        PlotView(content, store, index, theme, on_change=sidebar.refresh).pack(fill="both", expand=True)

    sidebar = Sidebar(window, store, theme, on_select=open_plot)
    sidebar.pack(side="left", fill="y", padx=20, pady=20)
    content.pack(side="left", fill="both", expand=True, pady=20, padx=(0, 20))
    Welcome(content, theme).pack(fill="both", expand=True)

    window.sidebar, window.content, window.open_plot = sidebar, content, open_plot
    return window


def mainmenu(background1, background2, active_background, cursor, font, size, colour1):
    theme = Theme(background1=background1, background2=background2,
                  active_background=active_background, cursor=cursor, font=font, size=size,
                  colour1=colour1)
    build(theme).mainloop()


if __name__ == "__main__":
    mainmenu(background1="#E0EAF0", background2="#788ebd", active_background="#DEDDFF",
             cursor='star', font='Tw Cen MT', size=20,
             colour1="#0A1D2B")
