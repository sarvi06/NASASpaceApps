"""The tabs shown for a plot, in order.

To add a tab: write a BaseTab subclass in a new file here (see rotation.py for the smallest
example) and add it to TABS.
"""

from .base import BaseTab
from .budget import BudgetTab
from .crops import CropPlantingTab
from .rotation import RotationTab

TABS: list[type[BaseTab]] = [RotationTab, CropPlantingTab, BudgetTab]

__all__ = ["TABS", "BaseTab", "BudgetTab", "CropPlantingTab", "RotationTab"]
