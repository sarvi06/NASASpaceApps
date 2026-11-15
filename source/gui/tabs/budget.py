"""Budget tab: the best rotations whose growing costs fit what the farmer can spend a year.

It starts from the plot's last rotation (the crops the farmer knows the costs of) and uses the
plot's size to turn the budget into a limit per hectare. There is no cost dataset, so at least
one crop's cost has to be entered in "Your numbers".
"""

from __future__ import annotations

import tkinter as tk

import backend

from ..plots import Plot
from .base import BaseTab, Request


def budget_request(plot: Plot, budget_text: str, common: dict, numbers: dict | None) -> Request:
    try:
        budget = float(budget_text.replace(",", "").replace("$", "").strip())
    except ValueError:
        raise ValueError(f"Enter your budget as a number of US dollars a year, got {budget_text!r}.") from None
    if budget <= 0:
        raise ValueError("Your budget must be more than 0.")
    if not any("cost" in figures for figures in (numbers or {}).values()):
        raise ValueError("Enter what at least one crop costs you per hectare in 'Your numbers': "
                         "there is no cost data to plan a budget from otherwise.")
    return Request(backend.recommend_within_budget,
                   {**common, "budget_usd": budget, "plot_size_ha": plot.size_ha,
                    "farm_numbers": numbers, "previous_crop": plot.last_crop})


class BudgetTab(BaseTab):
    title = "Budget"
    intro = ("Enter what you can spend on growing costs a year for the whole plot. The rotations "
             "suggested follow your last rotation and cost no more than that. Fill in the cost "
             "per hectare of at least one crop you know below; other crops are assumed to cost "
             "the same share of their income.")

    def build_inputs(self, frame: tk.Frame) -> None:
        self.label(frame, "Budget (US dollars a year, whole plot)").pack(side="left", padx=(0, 6))
        self.budget = self.entry(frame, "", 14)
        self.budget.pack(side="left")
        self.size_note = self.label(frame, self._size_text())
        self.size_note.pack(side="left", padx=12)

    def _size_text(self) -> str:
        return f"Plot size: {self.plot.size_ha:g} ha"

    def crops_to_prefill(self) -> list[str]:
        return list(dict.fromkeys(self.plot.last_rotation))     # each crop once, in order

    def set_plot(self, plot: Plot) -> None:
        super().set_plot(plot)
        self.size_note.config(text=self._size_text())

    def request(self, common: dict, numbers: dict | None) -> Request:
        return budget_request(self.plot, self.budget.get(), common, numbers)
