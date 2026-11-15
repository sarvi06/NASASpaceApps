"""Rotation tab: the best rotations for this plot, following its last crop if one is known."""

from __future__ import annotations

import backend

from ..plots import Plot
from .base import BaseTab, Request


def rotation_request(plot: Plot, common: dict, numbers: dict | None) -> Request:
    """Follow the plot's last crop when it is known; otherwise a general recommendation."""
    if plot.last_crop:
        return Request(backend.recommend_after_crop,
                       {**common, "last_crop": plot.last_crop, "farm_numbers": numbers})
    return Request(backend.recommend, {**common, "farm_numbers": numbers})


class RotationTab(BaseTab):
    title = "Best rotations"
    intro = ("The best three rotations for this plot's climate and soil. If the plot's last "
             "rotation is filled in, they are chosen and started to follow its last crop.")

    def request(self, common: dict, numbers: dict | None) -> Request:
        return rotation_request(self.plot, common, numbers)
