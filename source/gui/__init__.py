"""The desktop app, built on the home page in source/user_interface.py.

  theme.py      colours, fonts and cursor
  plots.py      the farmer's plots and where they are saved (no tkinter)
  widgets.py    shared pieces: scrolling area, card, wrapping text, buttons, fold-out section
  home.py       side bar of plot buttons + "Add plot", and the home page
  plot_view.py  one plot: its summary, its details and its tabs
  results.py    a recommendation as cards: calendar, scores, benefits, what to check
  runner.py     runs a back-end call in the background so the window never freezes
  tabs/         one file per tab; tabs/__init__.py lists the tabs shown
"""
