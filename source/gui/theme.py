"""The app's look in one place: colours, fonts and cursor.

The blues and the typeface are the ones chosen for the original home page. The other colours
have one meaning each wherever they appear: green = good / a harvest crop, amber = check this,
brown = bare soil.
"""

from __future__ import annotations

import tkinter.font as tkFont
from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    background1: str = "#E0EAF0"        # window
    background2: str = "#788ebd"        # side bar, main buttons
    active_background: str = "#DEDDFF"  # selected / pressed
    cursor: str = "arrow"
    font: str = "Tw Cen MT"
    size: int = 20
    colour1: str = "#0A1D2B"            # text
    light: str = "#acc0eb"              # the plot icon's light blue
    report_font: str = "Consolas"       # fixed width, for the full text report

    card: str = "#FFFFFF"               # panels that hold content
    line: str = "#C5D2DC"               # thin borders
    muted: str = "#4F6272"              # secondary text
    good: str = "#2E7D4F"               # benefits, scores, the main action button
    good_soft: str = "#E3F2E8"
    warn: str = "#9A5B00"               # things to check
    warn_soft: str = "#FFF3D6"
    problem: str = "#A01818"            # error messages
    bare: str = "#E4D4BC"               # bare soil on the calendar
    cover: str = "#A9D8B8"              # cover crops on the calendar
    track: str = "#E6ECF1"              # the empty part of a score bar
    # harvest crops on the calendar, one colour per crop (dark enough for white text)
    crop_colours: tuple = ("#2E7D4F", "#B26A00", "#3A6EA5", "#8E4585", "#6B7A1F", "#A6452C")

    def _font(self, size: int, bold: bool = False) -> tkFont.Font:
        return tkFont.Font(family=self.font, size=size, weight="bold" if bold else "normal")

    def title_font(self) -> tkFont.Font:
        return self._font(20, bold=True)

    def big_font(self) -> tkFont.Font:
        return self._font(self.size)

    def heading_font(self) -> tkFont.Font:
        return self._font(15, bold=True)

    def text_font(self) -> tkFont.Font:
        return self._font(13)

    def bold_font(self) -> tkFont.Font:
        return self._font(13, bold=True)

    def small_font(self) -> tkFont.Font:
        return self._font(11)

    def report_text_font(self) -> tkFont.Font:
        return tkFont.Font(family=self.report_font, size=10)
