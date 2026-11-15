"""US farm units <-> the metric units the back end takes. No tkinter here.

A US farmer quotes land in acres, grain in bushels and most other crops in hundredweight (cwt,
100 lb: how potatoes and vegetables are sold). The back end works in hectares and tonnes, so the
window converts on the way in and out and the back end never sees US units.

data/bushel_weights.csv holds the USDA standard weight of a bushel for each everyday crop name.
It is a table of units, not a list of allowed crops: a crop that is not in it is simply
quoted by the hundredweight.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

ACRES_PER_HA = 2.471
LB_PER_TONNE = 2204.62
CWT_LB = 100
WEIGHTS_PATH = Path(__file__).parent / "data" / "bushel_weights.csv"


@lru_cache(maxsize=1)
def _bushel_weights() -> dict[str, float]:
    with open(WEIGHTS_PATH, newline="", encoding="utf-8") as file:
        return {row["crop"].strip().lower(): float(row["lb_per_bushel"]) for row in csv.DictReader(file)}


def unit_for(crop: str) -> tuple[str, float]:
    """('bushel', lb per bushel) for a crop sold by the bushel, else ('cwt', 100.0)."""
    weight = _bushel_weights().get(str(crop).strip().lower())
    return ("bushel", weight) if weight else ("cwt", float(CWT_LB))


def acres_to_ha(acres: float) -> float:
    return acres / ACRES_PER_HA


def ha_to_acres(ha: float) -> float:
    return ha * ACRES_PER_HA


def to_metric(crop: str, numbers: dict) -> dict:
    """One crop's price (USD per bushel or cwt), yield (bushels or cwt per acre) and cost (USD per
    acre) -> USD per tonne, tonnes per hectare and USD per hectare. Other keys are left alone."""
    _, lb = unit_for(crop)
    out = dict(numbers)
    if "price" in out:
        out["price"] = out["price"] * LB_PER_TONNE / lb
    if "yield" in out:
        out["yield"] = out["yield"] * lb / LB_PER_TONNE * ACRES_PER_HA
    if "cost" in out:
        out["cost"] = out["cost"] * ACRES_PER_HA
    return out
