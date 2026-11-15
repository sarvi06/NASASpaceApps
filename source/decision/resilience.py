"""How does a chosen rotation hold up in other weather than the average year?

Each rotation is picked and scored against the average climate of the whole period. This
module checks the rotations the app shows, for display only (it never changes which rotations
are picked or their scores):
  reliability   would each harvest crop have worked in the actual weather of each year on
                record (NASA POWER)? e.g. "8 of the last 10 years (weak: 2012, corn short of rain)"
  hotter/drier  the same rotation re-scored with WARMER_C more warmth and DRIER_FACTOR of the rain

    yearly = yearly_climates(power_daily)              # once per field
    rot.resilience = check(rot, clim, yearly, site)    # once per rotation shown
    rot.resilience["years_ok"], rot.resilience["scenario"]["fit"]

Simplifications:
  - Each calendar year's 12 months are used as if that weather repeated, so a crop that
    overwinters is tested against one year's autumn and the same year's spring.
  - Every crop keeps its planting month; a farmer would shift planting dates in a bad year.
  - The hotter/drier case shifts every month by the same amount; soil is unchanged.
  - Evaporative demand (ET0) is held constant in the hotter case; only fit is re-scored here.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from .field_profile import monthly_climatology
from .rotations import Rotation, fit_score
from .suitability import Climate, Slot, score_cover, score_harvest

WARMER_C = 2.0        # hotter/drier case: every month this much warmer (days and coldest nights)
DRIER_FACTOR = 0.8    # ... and this share of the rain (20% less)
WORKS_AT = 0.4        # a crop "works" at or above this score; same bar as build_slots(min_score=0.4)
CANNOT_GROW = "cannot grow"
SCENARIO = f"{WARMER_C:g} degC warmer and {1 - DRIER_FACTOR:.0%} less rain"


def hotter_drier(clim: Climate) -> Climate:
    """The same climate, WARMER_C warmer with DRIER_FACTOR of the rain. Any other fields
    Climate has are carried through unchanged."""
    return replace(clim,
                   tmean=[t + WARMER_C for t in clim.tmean],
                   tmin_ext=[t + WARMER_C for t in clim.tmin_ext],
                   precip=[p * DRIER_FACTOR for p in clim.precip])


def yearly_climates(power_daily: pd.DataFrame) -> dict[int, Climate]:
    """One Climate per full calendar year of NASA POWER daily data ({year: Climate}).
    A year that cannot give 12 complete months is skipped."""
    df = power_daily.copy()
    df.index = pd.to_datetime(df.index)
    out = {}
    for year in sorted(set(df.index.year)):
        try:
            out[int(year)] = Climate.from_monthly(monthly_climatology(df[df.index.year == year]))
        except ValueError:           # a part year: some month is missing or incomplete
            continue
    return out


def rescore(rot: Rotation, clim: Climate, site: dict | None = None,
            irrigated: bool = False) -> list[Slot | None]:
    """Each of the rotation's crops, planted in the same month, scored in `clim`
    (None = it cannot grow there). Cover crops keep their length."""
    out = []
    for s in rot.slots:
        if s.use == "harvest":
            out.append(score_harvest(s.crop, s.start, clim, site, irrigated))
        else:
            out.append(score_cover(s.crop, s.start, s.months, clim, site))
    return out


def _score(slot: Slot | None) -> float:
    return 0.0 if slot is None else slot.score


def _limiter(slot: Slot | None) -> str:
    return CANNOT_GROW if slot is None else slot.limiter


def check(rot: Rotation, clim: Climate, yearly: dict[int, Climate], site: dict | None = None,
          irrigated: bool = False) -> dict:
    """How `rot` holds up in each year's weather and in a hotter, drier climate (JSON-safe).

    A year is ok when every harvest crop scores at least WORKS_AT in that year's weather
    (cover crops do not decide it); a bad year names its worst harvest crop. The scenario
    gives the fit in the average climate (`fit_now`) and in the hotter/drier one (`fit`),
    and the harvest crop that loses the most (`weakest`, None if none loses)."""
    harvest = [i for i, s in enumerate(rot.slots) if s.use == "harvest"]

    bad_years = []
    for year, weather in sorted(yearly.items()) if harvest else ():
        redo = rescore(rot, weather, site, irrigated)
        worst = min(harvest, key=lambda i: _score(redo[i]))
        if _score(redo[worst]) < WORKS_AT:
            bad_years.append({"year": year, "crop": rot.slots[worst].crop.name,
                              "limited_by": _limiter(redo[worst]), "score": _score(redo[worst])})

    now = rescore(rot, clim, site, irrigated)
    hot = rescore(rot, hotter_drier(clim), site, irrigated)
    weakest = None
    if harvest:
        i = max(harvest, key=lambda i: _score(now[i]) - _score(hot[i]))
        if _score(now[i]) - _score(hot[i]) > 0:
            weakest = {"crop": rot.slots[i].crop.name, "score": _score(hot[i]),
                       "limited_by": _limiter(hot[i])}

    return {
        "years_checked": len(yearly),
        "years_ok": len(yearly) - len(bad_years),
        "bad_years": bad_years,
        "scenario": {
            "name": SCENARIO,
            "fit_now": round(fit_score(rot.slots, [_score(s) for s in now]), 3),
            "fit": round(fit_score(rot.slots, [_score(s) for s in hot]), 3),
            "weakest": weakest,
        },
    }
