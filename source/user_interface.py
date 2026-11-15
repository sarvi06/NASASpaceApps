"""The app's window: the plot side bar on the left, and on the right either the home page or
the plot that is open.

Run from the repo root:
    .venv\\Scripts\\python.exe source\\user_interface.py

The side bar, the home page, a plot's details, its tabs and the results page live in
source/gui/ (see gui/__init__.py).
"""

import tkinter as tk

from gui.home import Home, Sidebar
from gui.plot_view import PlotView
from gui.plots import PlotStore
from gui.theme import Theme
from gui.widgets import enable_wheel

WINDOW_SIZE = (1300, 800)
SMALLEST_WINDOW = (1000, 600)


def build(theme: Theme, store: PlotStore | None = None) -> tk.Tk:
    """Create the window (without starting it), so it can also be built in tests."""
    store = store or PlotStore()
    window = tk.Tk()
    window.title("Satellite Support for Farming")
    window.configure(bg=theme.background1, cursor=theme.cursor)
    # as big as planned, but never bigger than the screen it is on
    width = min(WINDOW_SIZE[0], window.winfo_screenwidth() - 40)
    height = min(WINDOW_SIZE[1], window.winfo_screenheight() - 100)
    window.geometry(f"{width}x{height}")
    window.minsize(min(SMALLEST_WINDOW[0], width), min(SMALLEST_WINDOW[1], height))
    enable_wheel(window)

    content = tk.Frame(window, bg=theme.background1)

    def show(page: tk.Widget) -> None:
        for old in content.winfo_children():
            if old is not page:
                old.destroy()
        page.pack(fill="both", expand=True)

    def open_plot(index: int) -> None:
        sidebar.selected.set(index)
        show(PlotView(content, store, index, theme, on_change=sidebar.refresh))

    def show_home() -> None:
        sidebar.selected.set(-1)
        show(Home(content, store, theme, on_open=open_plot))

    sidebar = Sidebar(window, store, theme, on_select=open_plot, on_home=show_home)
    sidebar.pack(side="left", fill="y", padx=(16, 12), pady=16)
    content.pack(side="left", fill="both", expand=True, pady=16, padx=(0, 16))
    show_home()

    window.sidebar, window.content = sidebar, content
    window.open_plot, window.show_home = open_plot, show_home
    return window


def mainmenu(background1, background2, active_background, cursor, font, size, colour1):
    theme = Theme(background1=background1, background2=background2,
                  active_background=active_background, cursor=cursor, font=font, size=size,
                  colour1=colour1)
    build(theme).mainloop()


if __name__ == "__main__":
    mainmenu(background1="#E0EAF0", background2="#788ebd", active_background="#DEDDFF",
             cursor='arrow', font='Tw Cen MT', size=20,
             colour1="#0A1D2B")
