"""The one function a front end calls:  recommend(lat, lon, start_date, end_date, ...)

    from backend import recommend
    rec = recommend(42.065, -93.73, "2015-01-01", "2024-12-31", priorities="build_soil")
    print(rec.to_text())          # full plain-English report
    data = rec.to_dict()          # everything as JSON-safe dicts/lists, for a UI

What happens inside:
  1. check the inputs
  2. pull the data (data_pullers/; saved to disk the first time, reused after)
       NASA POWER climate  - required
       USDA SSURGO soil, USDA CropScape crop history (US only), NASA SMAP (optional)
       FAO EcoCrop crop needs
  3. decision/field_profile.py  -> one FieldProfile (climate, soil, trends, current rotation)
  4. decision/crops.py          -> candidate crops
  5. decision/suitability.py    -> score every crop x planting month
  6. decision/rotations.py      -> search rotations, rate them, pick the top 3, score the current one
  7. decision/report.py         -> why / evidence / benefits / gaps / risks
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable

import pandas as pd

from data_pullers import (get_climate, get_crop_history, get_crop_requirements, get_soil,
                          get_soil_moisture)
from data_pullers._common import check_location, to_date
from data_pullers.USDA_CropScape_pull import FIRST_YEAR, in_contiguous_us, latest_year
from decision import report
from decision.crops import build_crops, find_crop
from decision.field_profile import CDL_TO_ECOCROP, FieldProfile, _json_safe, build_field_profile
from decision.rotations import (CARD, PRIORITY_PRESETS, Rotation, baseline_rotation, pick_top,
                                resolve_priorities, search_rotations)
from decision.suitability import Climate, Slot, best_single_crops, build_slots

MIN_DAYS = 365          # need a full year of climate to build monthly averages
RECOMMENDED_YEARS = 5   # fewer years -> one unusual year can skew the picture


@dataclass
class Recommendation:
    field: FieldProfile
    rotations: list[Rotation]               # the top 3 (fewer if not enough were found)
    baseline: Rotation | None               # the current rotation, scored the same way
    best_crops: list[Slot]                  # best single harvest crops for the field
    weights: dict                           # how much each report-card item counted
    priority_name: str
    warnings: list[str] = field(default_factory=list)
    data_sources: list[str] = field(default_factory=list)
    inputs: dict = field(default_factory=dict)

    def to_text(self) -> str:
        return report.text_report(self)

    def to_dict(self) -> dict:
        return _json_safe({
            "inputs": self.inputs,
            "field": self.field.to_dict(),
            "priorities": {"name": self.priority_name, "weights": self.weights, "card_items": CARD},
            "current_rotation": self.baseline.to_dict() if self.baseline else None,
            "recommended_rotations": [r.to_dict() for r in self.rotations],
            "best_single_crops": [{"crop": s.crop.name, "scientific_name": s.crop.sci,
                                   "plant": s.span.split("-")[0], "season": s.span,
                                   "suitability": s.score, "limited_by": s.limiter}
                                  for s in self.best_crops],
            "warnings": self.warnings,
            "data_sources": self.data_sources,
            "glossary": report.GLOSSARY,
            "disclaimer": report.DISCLAIMER,
        })


def recommend(lat: float, lon: float, start_date, end_date, priorities="balanced",
              current_rotation: list[str] | None = None, rotation_years: int = 3,
              irrigated: bool = False, use_smap: bool = False,
              on_progress: Callable[[str], None] | None = None) -> Recommendation:
    """Top 3 crop rotations for a location, using data between start_date and end_date.

    lat, lon          decimal degrees
    start_date, end_date   "YYYY-MM-DD"; at least 12 months apart (5+ years recommended)
    priorities        "balanced", "save_water", "build_soil", "extra_income",
                      or a dict of weights over fit/cover/nitrogen/diversity/water/income
    current_rotation  e.g. ["corn", "soybean"]; default = detected from USDA CropScape
    rotation_years    length of the suggested rotations, 1-4 years
    irrigated         True = ignore rainfall limits
    use_smap          also pull NASA SMAP soil moisture (needs an Earthdata login; slow)
    on_progress       optional function called with short status messages
    """
    say = on_progress or (lambda msg: None)
    warnings: list[str] = []
    sources: list[str] = []

    # ---- 1. inputs ----
    lat, lon = check_location(lat, lon)
    start, end = to_date(start_date, "start_date"), to_date(end_date, "end_date")
    if start > end:
        raise ValueError(f"start_date ({start}) is after end_date ({end}).")
    if (end - start).days + 1 < MIN_DAYS:
        raise ValueError("The date range must cover at least 12 months so every month of the "
                         "year has climate data (5+ years recommended).")
    if (end - start).days + 1 < RECOMMENDED_YEARS * 365:
        warnings.append(f"Only {(end - start).days / 365.25:.1f} years of data: one unusual year can "
                        f"skew the averages ({RECOMMENDED_YEARS}+ years recommended).")
    if not 1 <= int(rotation_years) <= 4:
        raise ValueError("rotation_years must be between 1 and 4.")
    rotation_years = int(rotation_years)
    weights = resolve_priorities(priorities)   # validates early; re-done below with soil info

    # ---- 2. data ----
    say("Downloading NASA POWER climate...")
    try:
        climate = get_climate(lat, lon, start, end)
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not get NASA POWER climate data: {exc}") from exc
    sources.append("NASA POWER daily climate (power.larc.nasa.gov)")

    say("Downloading USDA SSURGO soil...")
    soil = pd.DataFrame()
    try:
        soil = get_soil(lat, lon)
        if soil.empty:
            warnings.append("No USDA SSURGO soil data here (it covers the US only); "
                            "soil needs were not checked.")
        else:
            sources.append("USDA NRCS SSURGO soil survey (Soil Data Access)")
    except Exception as exc:
        warnings.append(f"Soil data unavailable ({exc}); soil needs were not checked.")

    history = pd.DataFrame()
    first, last = max(start.year, FIRST_YEAR), min(end.year, latest_year())
    if not in_contiguous_us(lat, lon):
        warnings.append("Outside the contiguous US: no USDA CropScape crop history, so the current "
                        "rotation must be entered by hand to compare against it.")
    elif first > last:
        warnings.append(f"USDA CropScape covers {FIRST_YEAR}-{latest_year()}; your dates don't "
                        f"overlap it, so no crop history was used.")
    else:
        say(f"Downloading USDA CropScape crop history {first}-{last}...")
        try:
            history = get_crop_history(lat, lon, first, last)
            failed = history[history["error"].notna()]
            if len(failed):
                warnings.append(f"CropScape didn't answer for {', '.join(map(str, failed['year']))}.")
            sources.append("USDA NASS Cropland Data Layer via CropScape")
        except Exception as exc:
            warnings.append(f"Crop history unavailable ({exc}).")

    smap = None
    if use_smap:
        say("Requesting NASA SMAP soil moisture (can take several minutes)...")
        try:
            smap = get_soil_moisture(lat, lon, start, end)
            sources.append(f"NASA SMAP {smap.attrs.get('product', '')} soil moisture via AppEEARS")
        except Exception as exc:
            warnings.append(f"NASA SMAP not used: {exc}")

    say("Loading FAO EcoCrop crop requirements...")
    raw_crops = get_crop_requirements()
    sources.append("FAO EcoCrop crop requirements")
    history_sci = [CDL_TO_ECOCROP[c] for c in history.get("crop", pd.Series(dtype=str)).dropna()
                   if c in CDL_TO_ECOCROP]
    crops = build_crops(raw_crops, extra=history_sci)

    # ---- 3. field profile ----
    say("Building the field profile...")
    given = _resolve_current(current_rotation, crops) if current_rotation else None
    try:
        fp = build_field_profile(lat, lon, start, end, climate, soil, history,
                                 current_rotation=given, smap=smap)
    except ValueError as exc:
        raise ValueError(f"{exc} Try a date range made of whole years, e.g. "
                         f"{start.year}-01-01 to {end.year - 1}-12-31.") from exc
    clim = Climate.from_monthly(fp.climate_monthly)
    weights = resolve_priorities(priorities, fp.site)
    priority_name = priorities if isinstance(priorities, str) else "custom"

    # ---- 4-6. score crops, search rotations ----
    say("Scoring crops for each planting month...")
    by_start = build_slots(crops, clim, fp.site, irrigated)
    familiar = set(history_sci) | set((fp.current_rotation or {}).get("scientific", [])) or None

    say("Searching for rotations...")
    found = search_rotations(by_start, clim, weights, rotation_years, fp.insights, familiar)
    top = pick_top(found, 3, familiar)
    if len(top) < 3:
        warnings.append(f"Only {len(top)} distinct rotation(s) suit this field's climate and soil.")

    baseline = None
    if fp.current_rotation:
        current_crops = [crops[s] for s in fp.current_rotation["scientific"] if s in crops]
        baseline = baseline_rotation(current_crops, clim, weights, fp.site, irrigated,
                                     fp.insights, familiar)
        if baseline:
            baseline.strategy = "your current rotation"

    # ---- 7. explanations ----
    for rot in top + ([baseline] if baseline else []):
        rot.explanation = report.explain(rot, fp, None if rot is baseline else baseline, weights,
                                         priority_name, familiar, used_smap=smap is not None)
    say("Done.")
    return Recommendation(
        field=fp, rotations=top, baseline=baseline, best_crops=best_single_crops(by_start),
        weights=weights, priority_name=priority_name, warnings=warnings, data_sources=sources,
        inputs={"lat": lat, "lon": lon, "start_date": str(start), "end_date": str(end),
                "priorities": priorities, "current_rotation": current_rotation,
                "rotation_years": rotation_years, "irrigated": irrigated, "use_smap": use_smap},
    )


def _resolve_current(names: list[str], crops: dict) -> dict:
    found, unknown = [], []
    for name in names:
        crop = find_crop(name, crops)
        (found.append(crop) if crop else unknown.append(name))
    if unknown:
        known = ", ".join(sorted(c.name for c in crops.values()))
        raise ValueError(f"Unknown crop name(s) {unknown}. Known crops: {known}.")
    return {"crops": [c.name for c in found], "scientific": [c.sci for c in found],
            "source": "entered by you", "repeating": True}


__all__ = ["recommend", "Recommendation", "PRIORITY_PRESETS"]
