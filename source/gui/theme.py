"""The app's look in one place: the colours, fonts and cursor chosen for the home page."""

from __future__ import annotations

import tkinter.font as tkFont
from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    background1: str = "#E0EAF0"        # window
    background2: str = "#788ebd"        # panels and plot buttons
    active_background: str = "#DEDDFF"  # selected / pressed
    cursor: str = "star"
    font: str = "Tw Cen MT"
    size: int = 20
    colour1: str = "#0A1D2B"            # text
    light: str = "#acc0eb"              # the plot icon's light blue, used for button text
    report_font: str = "Consolas"       # fixed width: the rotation calendar needs aligned columns

    def title_font(self) -> tkFont.Font:
        return tkFont.Font(family=self.font, size=20, weight="bold")

    def big_font(self) -> tkFont.Font:
        return tkFont.Font(family=self.font, size=self.size)

    def text_font(self) -> tkFont.Font:
        return tkFont.Font(family=self.font, size=13)

    def report_text_font(self) -> tkFont.Font:
        return tkFont.Font(family=self.report_font, size=10)
