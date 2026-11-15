"""Crop planting tab: the farmer names the crops they want; rotations are built around them."""

from __future__ import annotations

import tkinter as tk

import backend

from ..plots import Plot, parse_crops
from .base import BaseTab, Request


def crops_request(plot: Plot, crops_text: str, common: dict, numbers: dict | None) -> Request:
    wanted = parse_crops(crops_text)
    if not 1 <= len(wanted) <= backend.MAX_MUST_GROW:
        raise ValueError(f"Enter one or two crops you want to grow, separated by a comma "
                         f"(you entered {len(wanted)}).")
    return Request(backend.recommend_around_crops,
                   {**common, "must_grow": list(wanted), "last_crop": plot.last_crop,
                    "farm_numbers": numbers})


class CropPlantingTab(BaseTab):
    title = "Crop planting"
    intro = ("Enter one or two crops you want to grow. Every rotation suggested will contain "
             "them, with the other crops chosen to suit them and the plot.")

    def build_inputs(self, frame: tk.Frame) -> None:
        self.label(frame, "Crops to grow (one or two, comma between)").pack(side="left", padx=(0, 6))
        self.crops = self.entry(frame, "", 32)
        self.crops.pack(side="left")

    def request(self, common: dict, numbers: dict | None) -> Request:
        return crops_request(self.plot, self.crops.get(), common, numbers)
