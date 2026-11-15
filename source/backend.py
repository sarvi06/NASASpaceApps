"""What a front end calls. Two questions, one shared pipeline:

    recommend_after_crop(lat, lon, start_date, end_date, last_crop="corn")
        "I just grew this. What rotation should follow it?"
    recommend_around_crops(lat, lon, start_date, end_date, must_grow=["rice"])
        "I have to grow these one or two crops. Build a rotation around them."
    recommend_within_budget(lat, lon, start_date, end_date, budget_usd, plot_size_ha, farm_numbers)
        "I can spend this much a year on this plot. What can I afford?"
    recommend(lat, lon, start_date, end_date, ...)
        the pipeline both use (and the original entry point, still supported)

    from backend import recommend_after_crop
    rec = recommend_after_crop(42.065, -93.73, "2015-01-01", "2024-12-31", "corn",
                               farm_numbers={"corn": {"price": 180, "cost": 900}})
    print(rec.to_text())          # full plain-English report
    data = rec.to_dict()          # everything as JSON-safe dicts/lists, for a UI

What happens inside:
  1. check the inputs
  2. pull the data (data_pullers/; saved to disk the first time, reused after)
       NASA POWER climate  - required
       USDA SSURGO soil, USDA CropScape crop history, NASA SMAP (optional)
       FAO EcoCrop crop needs; FAOSTAT prices and yields for the United States
     The soil and crop-history data only exist for the USA, so the tool covers the
     contiguous United States (the 48 states); other locations are refused.
  3. decision/field_profile.py  -> one FieldProfile (climate, soil, trends, current rotation)
  4. decision/crops.py          -> candidate crops (every rotation crop in EcoCrop)
     decision/economics.py      -> one Economy: what each crop earns here and how widely it
                                   is grown (the only module that reads prices)
  5. decision/suitability.py    -> score every crop x planting month; first cut ranked by
                                   the Economy
  6. decision/rotations.py      -> search rotations, rate them, pick the top 3, score the current one,
                                   start each in the year that best follows the crop grown last
                                   (decision/sequence.py holds the "what can follow what" rules)
     decision/resilience.py     -> how each rotation shown holds up in each year's weather and
                                   in a hotter, drier climate (display only)
  7. decision/report.py         -> why / evidence / benefits / gaps / risks
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable

import pandas as pd

from data_pullers import (find_country, get_climate, get_crop_economics, get_crop_history,
                          get_crop_requirements, get_soil, get_soil_moisture)
from data_pullers._common import check_location, to_date
from data_pullers.USDA_CropScape_pull import FIRST_YEAR, in_contiguous_us, latest_year
from decision import report
from decision.crops import Crop, build_crops, find_crop
from decision.economics import SOLD_CROPS, Economy, build_economy
from decision.field_profile import CDL_TO_ECOCROP, FieldProfile, _json_safe, build_field_profile
from decision.resilience import check, yearly_climates
from decision.rotations import (CARD, PRIORITY_PRESETS, Rotation, baseline_rotation, pick_top,
                                resolve_priorities, search_rotations)
from decision.sequence import follow_score
from decision.suitability import Climate, Slot, best_single_crops, build_slots, score_harvest

MIN_DAYS = 365          # need a full year of climate to build monthly averages
RECOMMENDED_YEARS = 5   # fewer years -> one unusual year can skew the picture
MAX_MUST_GROW = 2       # crops a rotation can be built around
POOR_FIT = 0.4          # a must-grow crop below this suitability gets a warning


@dataclass
class Recommendation:
    field: FieldProfile
    rotations: list[Rotation]               # the top 3 (fewer if not enough were found)
    baseline: Rotation | None               # the current rotation, scored the same way
    best_crops: list[Slot]                  # best single harvest crops for the field
    weights: dict                           # how much each report-card item counted
    priority_name: str
    previous_crop: dict | None = None       # {"crop", "scientific_name", "source"}: grown last
    must_grow: list[str] = field(default_factory=list)   # crops every rotation had to contain
    country: dict | None = None             # {"name", "iso2", "m49"}: always the United States
    place: str | None = None                # what the farmer calls the spot, e.g. "Ames, Iowa (zip 50010)"
    economy: Economy = field(default_factory=Economy)    # what each crop earns and how it sells
    crops: dict = field(default_factory=dict)            # every candidate, {scientific name: Crop}
    budget: dict | None = None              # {"budget_usd", "plot_size_ha", "max_cost_usd_ha"}
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
            "previous_crop": self.previous_crop,
            "must_grow": self.must_grow,
            "budget": self.budget,
            "country": self.country,
            "place": self.place,
            "economy": {"typical_income_usd_ha": self.economy.typical_income,
                        "assumed_cost_share": self.economy.cost_share},
            "economics": self.economy.table(self.crops),
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
              on_progress: Callable[[str], None] | None = None,
              previous_crop: str | None = None, must_grow: list[str] | None = None,
              farm_numbers: dict | None = None,
              place: str | None = None, budget_usd: float | None = None,
              plot_size_ha: float | None = None) -> Recommendation:
    """Top 3 crop rotations for a location in the contiguous United States, using data
    between start_date and end_date.

    lat, lon          decimal degrees, inside the 48 contiguous states (a zip code can be
                      turned into them with data_pullers.get_zip_location)
    start_date, end_date   "YYYY-MM-DD"; at least 12 months apart (5+ years recommended)
    priorities        "balanced", "save_water", "build_soil", "extra_income", or a dict of
                      weights over fit/cover/nitrogen/diversity/sequence/water/income/market
    current_rotation  e.g. ["corn", "soybean"]; default = detected from USDA CropScape
    rotation_years    length of the suggested rotations, 1-4 years
    irrigated         True = ignore rainfall limits
    use_smap          also pull NASA SMAP soil moisture (needs an Earthdata login; slow)
    on_progress       optional function called with short status messages
    previous_crop     the crop grown last, e.g. "corn"; default = the latest year in USDA
                      CropScape, else the last crop of current_rotation. Each suggested
                      rotation starts in the year that best follows it.
    must_grow         one or two crops every rotation must contain, e.g. ["rice"]
    farm_numbers      the farmer's own figures per crop, each optional, e.g.
                      {"corn": {"price": 180, "yield": 12.5, "cost": 900}}
                      price = US dollars per tonne, yield = tonnes per hectare (both replace
                      FAOSTAT's national average), cost = US dollars per hectare (FAOSTAT has
                      none; once any cost is given, crops without one are assumed to cost the
                      same share of their income, so profit is compared with profit)
    place             optional name for the spot, shown in the report, e.g.
                      "Ames, Iowa (zip 50010)"
    budget_usd, plot_size_ha   given together: the most the farmer can spend on growing
                      costs per year for a plot of that size. Rotations costing more per
                      hectare are left out. Needs at least one cost in farm_numbers.
    """
    say = on_progress or (lambda msg: None)
    warnings: list[str] = []
    sources: list[str] = []

    # ---- 1. inputs ----
    lat, lon = check_location(lat, lon)
    if not in_contiguous_us(lat, lon):
        raise ValueError(f"Latitude {lat:g}, longitude {lon:g} is outside the contiguous United "
                         f"States (the 48 states), the area this tool covers: its soil and "
                         f"crop-history data are US only. Enter a US zip code, or a US latitude "
                         f"(north +) and longitude (west -), e.g. 42.065, -93.73 for Iowa.")
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
    must_grow = [must_grow] if isinstance(must_grow, str) else list(must_grow or [])
    if len(must_grow) > MAX_MUST_GROW:
        raise ValueError(f"must_grow takes one or two crop names, got {len(must_grow)}.")
    usa = find_country("US")
    budget = _check_budget(budget_usd, plot_size_ha, farm_numbers)

    # ---- 2. data ----
    say("Downloading NASA POWER climate...")
    try:
        climate = get_climate(lat, lon, start, end)
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not get NASA POWER climate data: {exc}") from exc
    _check_on_land(climate, lat, lon)
    sources.append("NASA POWER daily climate (power.larc.nasa.gov)")

    say("Downloading USDA SSURGO soil...")
    soil = None
    try:
        soil = get_soil(lat, lon)
    except Exception as exc:
        warnings.append(f"Soil data unavailable ({exc}); soil needs were not checked.")
    if soil is not None and soil.empty:
        raise ValueError(f"The USDA soil survey has nothing at latitude {lat:g}, longitude {lon:g}: "
                         f"the point is outside the United States or on land that was never "
                         f"surveyed. Move it onto your field.")
    if soil is None:
        soil = pd.DataFrame()
    else:
        sources.append("USDA NRCS SSURGO soil survey (Soil Data Access)")

    history = pd.DataFrame()
    first, last = max(start.year, FIRST_YEAR), min(end.year, latest_year())
    if first > last:
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
            warnings += _not_a_crop_field(history)
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
    crops = build_crops(raw_crops, SOLD_CROPS, extra=history_sci)

    say("Loading FAOSTAT crop prices and yields...")
    faostat = pd.DataFrame()
    try:
        faostat = get_crop_economics(usa["m49"])
        sources.append(f"FAOSTAT producer prices and crop yields for {usa['name']} (fao.org/faostat)")
    except Exception as exc:
        warnings.append(f"FAOSTAT prices and yields unavailable ({exc}); only crops you gave "
                        f"both a price and a yield for are priced.")
    economy = build_economy(faostat, crops, usa["name"], farm_numbers)
    if not economy.crops:
        warnings.append("No crop has a known price here, so income and market did not affect "
                        "the ranking.")

    # ---- 3. field profile ----
    say("Building the field profile...")
    given = _resolve_current(current_rotation, crops) if current_rotation else None
    must = _resolve_current(must_grow, crops)["scientific"] if must_grow else []
    previous = _previous_crop(previous_crop, history, given, crops)
    last_grown = crops[previous["scientific_name"]] if previous else None
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
    familiar = set(history_sci) | set((fp.current_rotation or {}).get("scientific", [])) or None
    by_start = build_slots(crops, clim, fp.site, irrigated, rank=economy.rank,
                           always=set(must) | (familiar or set()))
    for sci in must:
        warnings += _check_must_grow(crops[sci], by_start, clim, fp.site, irrigated)

    say("Searching for rotations...")
    found = search_rotations(by_start, clim, weights, rotation_years, fp.insights, economy,
                             must_grow=must, previous=last_grown)
    if must and not found:
        names = " and ".join(crops[s].name for s in must)
        raise ValueError(f"No {rotation_years}-year rotation can include {names}: crops of the same "
                         f"family cannot follow each other and each year needs a harvest crop. "
                         f"Try a longer rotation (rotation_years up to 4) or one must-grow crop.")
    if budget and found:
        found = _within_budget(found, budget)
    top = pick_top(found, 3, familiar, shared=must)
    if len(top) < 3:
        warnings.append(f"Only {len(top)} distinct rotation(s) suit this field's climate and soil"
                        + (" within the budget." if budget else "."))

    if last_grown:
        clash = [rot.name for rot in top if follow_score(last_grown, rot.harvests[0].crop)[0] == 0]
        if clash:
            warnings.append(f"Every starting point of {'; '.join(clash)} puts a crop of the same "
                            f"family right after {last_grown.name}, the crop grown last.")
    else:
        warnings.append("The crop grown last is unknown, so the rotations start in an arbitrary "
                        "year (pass previous_crop to fix this).")

    baseline = None
    if fp.current_rotation:
        current_crops = [crops[s] for s in fp.current_rotation["scientific"] if s in crops]
        baseline = baseline_rotation(current_crops, clim, weights, fp.site, irrigated,
                                     fp.insights, economy)
        if baseline:
            baseline.strategy = "your current rotation"

    # ---- how the rotations shown hold up in other weather (display only, scores unchanged) ----
    say("Checking each rotation against every year's weather...")
    yearly = yearly_climates(climate)
    for rot in top + ([baseline] if baseline else []):
        rot.resilience = check(rot, clim, yearly, fp.site, irrigated)

    # ---- 7. explanations ----
    for rot in top + ([baseline] if baseline else []):
        rot.explanation = report.explain(rot, fp, None if rot is baseline else baseline, weights,
                                         priority_name, familiar, used_smap=smap is not None,
                                         economy=economy, budget=budget)
    say("Done.")
    return Recommendation(
        field=fp, rotations=top, baseline=baseline, best_crops=best_single_crops(by_start),
        weights=weights, priority_name=priority_name, previous_crop=previous,
        must_grow=[crops[s].name for s in must], country=usa, place=place,
        economy=economy, crops=crops, budget=budget,
        warnings=warnings, data_sources=sources,
        inputs={"lat": lat, "lon": lon, "start_date": str(start), "end_date": str(end),
                "priorities": priorities, "current_rotation": current_rotation,
                "previous_crop": previous_crop, "must_grow": must_grow,
                "farm_numbers": farm_numbers, "place": place,
                "budget_usd": budget_usd, "plot_size_ha": plot_size_ha,
                "rotation_years": rotation_years, "irrigated": irrigated, "use_smap": use_smap},
    )


def recommend_after_crop(lat: float, lon: float, start_date, end_date, last_crop: str,
                         **options) -> Recommendation:
    """Top 3 rotations to follow `last_crop`, the crop this plot grew last (e.g. "corn").

    Each rotation is started in the year that best follows that crop, and how well it follows
    counts in the ranking. `options` are the same as recommend()'s (priorities, rotation_years,
    farm_numbers, ...)."""
    if not last_crop or not str(last_crop).strip():
        raise ValueError("last_crop is required: the crop this plot grew last, e.g. 'corn'.")
    return recommend(lat, lon, start_date, end_date, previous_crop=last_crop, **options)


def recommend_around_crops(lat: float, lon: float, start_date, end_date, must_grow,
                           last_crop: str | None = None, **options) -> Recommendation:
    """Top 3 rotations built around one or two crops the farmer must grow (e.g. ["rice"]).

    Every rotation contains each must-grow crop as a harvest crop; the rest of the rotation is
    chosen around them. `last_crop` is optional. `options` are the same as recommend()'s."""
    names = [must_grow] if isinstance(must_grow, str) else list(must_grow or [])
    if not 1 <= len(names) <= MAX_MUST_GROW:
        raise ValueError(f"must_grow takes one or two crop names, got {len(names)}.")
    return recommend(lat, lon, start_date, end_date, must_grow=names, previous_crop=last_crop,
                     **options)


def recommend_within_budget(lat: float, lon: float, start_date, end_date, budget_usd: float,
                            plot_size_ha: float, farm_numbers: dict, **options) -> Recommendation:
    """Top 3 rotations the farmer can afford: growing costs per year for the whole plot stay
    within `budget_usd`.

    FAOSTAT has no costs, so `farm_numbers` must hold a cost for at least one crop, e.g.
    {"corn": {"cost": 900}} (US dollars per hectare); other crops are assumed to cost the same
    share of their income. `options` are the same as recommend()'s."""
    if budget_usd is None or plot_size_ha is None:
        raise ValueError("A budget needs both budget_usd and plot_size_ha.")
    return recommend(lat, lon, start_date, end_date, budget_usd=budget_usd,
                     plot_size_ha=plot_size_ha, farm_numbers=farm_numbers, **options)


def _not_a_crop_field(history: pd.DataFrame) -> list[str]:
    """A warning when CropScape answered but shows no crop at the point (a town, pasture,
    woodland...), which is what the centre of a zip code area often is."""
    seen = history["crop"].dropna()
    if seen.empty or seen.isin(CDL_TO_ECOCROP).any():
        return []
    return [f"USDA CropScape shows '{seen.mode().iloc[0]}' at this exact point, not a crop field, "
            f"so the current rotation could not be detected and the soil may not be your "
            f"field's. Move the latitude and longitude onto your field."]


def _check_on_land(climate: pd.DataFrame, lat: float, lon: float) -> None:
    """ValueError if the point is in the sea or on an ice sheet: NASA POWER has no root-zone
    soil wetness there. Usually latitude and longitude were swapped or a sign is wrong."""
    if "GWETROOT" in climate and climate["GWETROOT"].isna().all():
        raise ValueError(f"Latitude {lat:g}, longitude {lon:g} is in the sea or on ice, not on "
                         f"farmland (NASA POWER has no soil data there). Check the order and the "
                         f"signs: latitude first (north +, south -), then longitude (east +, "
                         f"west -), e.g. 42.065, -93.73 for Iowa.")


def _check_budget(budget_usd, plot_size_ha, farm_numbers: dict | None) -> dict | None:
    """Validate the budget inputs -> {"budget_usd", "plot_size_ha", "max_cost_usd_ha"} or None."""
    if budget_usd is None and plot_size_ha is None:
        return None
    try:
        budget_usd, plot_size_ha = float(budget_usd), float(plot_size_ha)
    except (TypeError, ValueError):
        raise ValueError("A budget needs both budget_usd and plot_size_ha, as numbers.") from None
    if budget_usd <= 0 or plot_size_ha <= 0:
        raise ValueError("budget_usd and plot_size_ha must both be more than 0.")
    if not any("cost" in numbers for numbers in (farm_numbers or {}).values()
               if isinstance(numbers, dict)):
        raise ValueError("To plan within a budget, enter what at least one crop costs you per "
                         "hectare: there is no cost data to work from otherwise.")
    return {"budget_usd": budget_usd, "plot_size_ha": plot_size_ha,
            "max_cost_usd_ha": budget_usd / plot_size_ha}


def _within_budget(found: list[Rotation], budget: dict) -> list[Rotation]:
    """The rotations whose known yearly cost per hectare fits the budget (best first, as given)."""
    affordable = [rot for rot in found if rot.cost_usd_ha <= budget["max_cost_usd_ha"]]
    if not affordable:
        cheapest = min(rot.cost_usd_ha for rot in found) * budget["plot_size_ha"]
        raise ValueError(f"No rotation fits a budget of ${budget['budget_usd']:,.0f} a year for "
                         f"{budget['plot_size_ha']:g} ha: the cheapest one found costs about "
                         f"${cheapest:,.0f} a year.")
    return affordable


def _check_must_grow(crop: Crop, by_start: dict, clim: Climate, site: dict | None,
                     irrigated: bool) -> list[str]:
    """Warnings for a must-grow crop that fits poorly; ValueError if it cannot grow at all."""
    options = [s for slots in by_start.values() for s in slots
               if s.use == "harvest" and s.crop.sci == crop.sci]
    if not options:
        tried = [s for m in range(12) if (s := score_harvest(crop, m, clim, site, irrigated))]
        why = (f"limited by {max(tried, key=lambda s: s.score).limiter}" if tried
               else "its growing season does not fit the year")
        raise ValueError(f"{crop.name} cannot be grown to harvest at this location in any month "
                         f"({why}), so no rotation can be built around it.")
    best = max(options, key=lambda s: s.score)
    if best.score < POOR_FIT:
        return [f"{crop.name} is a poor fit here (suitability {best.score:.2f}, limited by "
                f"{best.limiter}); it is included because you asked for it."]
    return []


def _resolve_current(names, crops: dict) -> dict:
    found, unknown = [], []
    for name in [names] if isinstance(names, str) else names:
        crop = find_crop(name, crops)
        (found.append(crop) if crop else unknown.append(name))
    if unknown:
        raise ValueError(f"Unknown crop name(s) {unknown}. Use a common or scientific name, "
                         f"e.g. corn, soybean, wheat, rice, potato.")
    return {"crops": [c.name for c in found], "scientific": [c.sci for c in found],
            "source": "entered by you", "repeating": True}


def _previous_crop(name: str | None, history: pd.DataFrame, given: dict | None,
                   crops: dict) -> dict | None:
    """The crop grown last: the name passed in, else the latest CropScape year, else the last
    crop of the rotation the user entered. None if none of those is known."""
    def answer(sci: str, source: str) -> dict:
        return {"crop": crops[sci].name, "scientific_name": sci, "source": source}

    if name:
        return answer(_resolve_current([name], crops)["scientific"][0], "entered by you")
    known = history.dropna(subset=["crop"]) if "crop" in history else history
    if not known.empty:
        latest = known.sort_values("year").iloc[-1]
        sci = CDL_TO_ECOCROP.get(latest["crop"])
        if sci in crops:
            return answer(sci, f"USDA CropScape {int(latest['year'])}")
    if given and given["scientific"]:
        return answer(given["scientific"][-1], "last crop of the rotation you entered")
    return None


__all__ = ["recommend", "recommend_after_crop", "recommend_around_crops",
           "recommend_within_budget", "Recommendation",
           "PRIORITY_PRESETS"]
