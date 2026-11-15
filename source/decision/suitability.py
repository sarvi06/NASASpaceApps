"""How well does each crop suit this field if planted in a given month?  (0 = impossible, 1 = ideal)

For every crop x planting month this checks, against the crop's EcoCrop needs:
  temperature   each growing month's mean temp vs optimal/absolute range (NASA POWER);
                the planting and last months only need to be a little above the minimum
  frost         coldest nights while growing vs the crop's killing temperature
  winter        overwintering crops (e.g. winter wheat, rye) go dormant in cold months;
                coldest dormant nights vs how cold they survive
  rain          rain over the season (scaled to a year) vs optimal/absolute range
  soil          pH, texture, drainage, depth, salinity, fertility (USDA SSURGO)
The lowest of these is the score (a crop is held back by its weakest factor), and the
factor that set it is kept as the "limiter". Every check also writes a sentence of
evidence (actual numbers and their source) used in the final report.

Two ways to use a crop:
  harvest  grown to maturity (cash grain, or forage cut for hay)
  cover    planted after a harvest to protect the soil and ended before the next crop;
           only needs to establish (and survive winter if it is meant to)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable

import pandas as pd

from .crops import Crop

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS_PER_MONTH = 30.4

TOLERATED = 0.7        # soil label only in the crop's tolerated (absolute) range
OUTSIDE = 0.2          # soil label outside even the tolerated range
WINTER_MARGIN_C = 10   # colder than a crop's hardiness by up to this much = risk, not certain death
COVER_LENGTHS = range(3, 9)   # cover crops stay in for 3-8 months
EDGE_MARGIN_C = 3      # planting and ripening months only need to be this far above the crop's minimum
MIN_HARVEST_MONTHS = 3       # field crops need at least 3 months to a harvest

_DEPTH = ["very shallow (<20 cm)", "shallow (20-50 cm)", "medium (50-150 cm)", "deep (>>150 cm)"]
_SALINITY = ["none", "low (<4 dS/m)", "medium (4-10 dS/m)", "high (>10 dS/m))"]
_FERTILITY = ["low", "moderate", "high"]


# --------------------------------------------------------------------------------------
# Climate the scoring uses: 12 monthly values
# --------------------------------------------------------------------------------------
@dataclass
class Climate:
    tmean: list[float]      # mean daily temperature per month (degC)
    tmin_ext: list[float]   # typical coldest night per month (degC)
    precip: list[float]     # typical monthly rainfall (mm)
    et0: list[float] | None = None   # reference evapotranspiration per month (mm), water.py; None = unknown

    @classmethod
    def from_monthly(cls, df: pd.DataFrame) -> "Climate":
        """From field_profile.monthly_climatology() output (month, tmean, tmin_ext, precip,
        and et0 when build_field_profile() could work it out)."""
        df = df.sort_values("month")
        if len(df) != 12:
            raise ValueError("monthly climate must have exactly 12 rows")
        et0 = df["et0"].tolist() if "et0" in df and df["et0"].notna().all() else None
        return cls(df["tmean"].tolist(), df["tmin_ext"].tolist(), df["precip"].tolist(), et0)

    @property
    def annual_rain(self) -> float:
        return float(sum(self.precip))

    def table(self) -> str:
        rows = [f"{'':<8}" + "".join(f"{m:>7}" for m in MONTHS),
                f"{'Tmean':<8}" + "".join(f"{v:7.1f}" for v in self.tmean),
                f"{'Coldest':<8}" + "".join(f"{v:7.1f}" for v in self.tmin_ext),
                f"{'Rain':<8}" + "".join(f"{v:7.0f}" for v in self.precip)]
        return "\n".join(rows)


# --------------------------------------------------------------------------------------
# One scored option: crop x planting month x use
# --------------------------------------------------------------------------------------
RESIDUE_MONTHS = 2   # dead cover-crop residue keeps protecting the soil for about this long


@dataclass(frozen=True)
class Slot:
    crop: Crop
    start: int                  # planting month, 0 = Jan .. 11 = Dec
    months: int                 # months in the ground (including dormant months)
    use: str                    # "harvest" or "cover"
    score: float                # 0-1, lowest factor
    limiter: str                # factor that set the score
    factors: dict = field(default_factory=dict, compare=False, hash=False)
    evidence: tuple = ()        # sentences with the numbers behind each factor
    flags: tuple = ()           # risks worth a local check
    gaps: tuple = ()            # data that was missing for this crop / field
    covering: int | None = None  # months the soil is really covered; None = all of `months`

    @property
    def covered(self) -> int:
        """Months the soil is protected (a killed cover crop only leaves residue for a while)."""
        return self.months if self.covering is None else self.covering

    @property
    def end(self) -> int:
        """Last calendar month in the ground (0-11)."""
        return (self.start + self.months - 1) % 12

    @property
    def span(self) -> str:
        return f"{MONTHS[self.start]}-{MONTHS[self.end]}"


def trapezoid(x: float, lo, opt_lo, opt_hi, hi) -> float:
    """0 outside [lo, hi], 1 inside [opt_lo, opt_hi], straight-line ramps in between.
    Missing outer bounds -> 1.0 (no constraint)."""
    if lo is None or hi is None:
        return 1.0
    opt_lo = lo if opt_lo is None else max(opt_lo, lo)
    opt_hi = hi if opt_hi is None else min(opt_hi, hi)
    if opt_lo > opt_hi:
        opt_lo = opt_hi = (opt_lo + opt_hi) / 2
    if x <= lo or x >= hi:
        return 0.0
    if x < opt_lo:
        return (x - lo) / (opt_lo - lo)
    if x > opt_hi:
        return (hi - x) / (hi - opt_hi)
    return 1.0


def _span(months: list[int]) -> str:
    return f"{MONTHS[months[0]]}-{MONTHS[months[-1]]}" if len(months) > 1 else MONTHS[months[0]]


def _kill_temp(crop: Crop) -> float:
    """Temperature that kills the crop while growing. Unknown -> 0 degC for frost-tender
    crops; overwintering crops tolerate frosts down to at least -8 degC while growing."""
    kill = crop.ktmp if crop.ktmp is not None else 0.0
    return min(kill, -8.0) if crop.hardy_to is not None else kill


# --------------------------------------------------------------------------------------
# Factor checks
# --------------------------------------------------------------------------------------
def soil_factor(crop: Crop, site: dict | None) -> tuple[float, str, list[str], list[str]]:
    """(score, worst part, evidence, gaps) for pH, texture, drainage, depth, salinity, fertility."""
    if site is None:
        return 1.0, "soil", [], ["no soil data for this location (SSURGO covers the US only)"]
    parts: dict[str, float] = {}
    notes, gaps = [], []

    ph = site.get("ph")
    if ph is not None and crop.phmin is not None and crop.phmax is not None:
        parts["pH"] = trapezoid(ph, crop.phmin, crop.phopmn, crop.phopmx, crop.phmax)
        notes.append(f"pH {ph:.1f} vs optimum {crop.phopmn:g}-{crop.phopmx:g}")
    else:
        gaps.append("pH")

    def label_set(name, value, opt, ab, raw=""):
        if value is None or not (opt or ab):
            gaps.append(name)
            return
        if value in opt or "wide" in opt:
            parts[name] = 1.0
        elif value in ab or "wide" in ab:
            parts[name] = TOLERATED
        else:
            parts[name] = OUTSIDE
        notes.append(f"{name} {value}{raw}: " + {1.0: "optimal", TOLERATED: "tolerated",
                                                  OUTSIDE: "outside range"}[parts[name]])

    def label_order(name, value, opt, ab, order, higher_is_better):
        if value is None or value not in order or not (opt in order or ab in order):
            gaps.append(name)
            return
        v = order.index(value)

        def ok(limit):
            if limit not in order:
                return False
            return v >= order.index(limit) if higher_is_better else v <= order.index(limit)

        parts[name] = 1.0 if ok(opt) else TOLERATED if ok(ab) else OUTSIDE
        notes.append(f"{name} {value}: " + {1.0: "optimal", TOLERATED: "tolerated",
                                             OUTSIDE: "outside range"}[parts[name]])

    raw_text = f" ({site['text_raw']})" if site.get("text_raw") else ""
    label_set("texture", site.get("text"), crop.text_opt, crop.text_abs, raw_text)
    label_set("drainage", site.get("dra"), crop.dra_opt, crop.dra_abs)
    label_order("depth", site.get("dep"), crop.dep_opt, crop.dep_abs, _DEPTH, True)
    label_order("salinity", site.get("sal"), crop.sal_opt, crop.sal_abs, _SALINITY, False)
    label_order("fertility", site.get("fer"), crop.fer_opt, crop.fer_abs, _FERTILITY, True)

    if not parts:
        return 1.0, "soil", [], [f"soil needs of {crop.name}" + (f" ({', '.join(gaps)})" if gaps else "")]
    worst = min(parts, key=parts.get)
    evidence = [f"Soil (USDA SSURGO vs EcoCrop): " + "; ".join(notes)]
    gap_list = [f"{crop.name}: no EcoCrop/SSURGO data for soil {', '.join(gaps)}"] if gaps else []
    return parts[worst], worst, evidence, gap_list


def winter_factor(crop: Crop, dormant: list[int], clim: Climate) -> tuple[float, list[str], list[str]]:
    """(score, evidence, flags) for surviving the dormant months."""
    if not dormant:
        return 1.0, [], []
    coldest = min(clim.tmin_ext[m] for m in dormant)
    deficit = crop.hardy_to - coldest
    if deficit <= 0:
        score = 1.0
    elif deficit <= WINTER_MARGIN_C:
        score = 1.0 - 0.6 * deficit / WINTER_MARGIN_C
    else:
        score = 0.0
    evidence = [f"Winter: dormant {_span(dormant)}, coldest nights about {coldest:.0f} degC "
                f"(NASA POWER); survives to about {crop.hardy_to:g} degC"]
    flags = [f"{crop.name}: winter-kill risk (nights {coldest:.0f} degC vs hardy to "
             f"{crop.hardy_to:g} degC; depends on snow cover and variety)"] if 0 < score < 1 else []
    return score, evidence, flags


# --------------------------------------------------------------------------------------
# Scoring a harvest crop
# --------------------------------------------------------------------------------------
def _season_options(crop: Crop) -> list[int]:
    """Growing months to try: a typical season and a shorter variety."""
    typical = crop.gmin + (crop.gmax - crop.gmin) / 3
    shorter = (crop.gmin + typical) / 2
    return sorted({min(10, max(MIN_HARVEST_MONTHS, round(d / DAYS_PER_MONTH)))
                   for d in (typical, shorter)},
                  reverse=True)


def _walk_season(crop: Crop, start: int, active_needed: int, clim: Climate):
    """Calendar months from planting until `active_needed` growing months are done.
    Overwintering crops pause (go dormant) in months colder than their minimum."""
    active, dormant, m = [], [], start
    while len(active) < active_needed and len(active) + len(dormant) < 11:
        mm = m % 12
        too_cold = clim.tmean[mm] < crop.tmin
        if too_cold and active and crop.hardy_to is not None:
            dormant.append(mm)
        else:
            active.append(mm)
        m += 1
    if len(active) < active_needed:
        return None
    return active, dormant, len(active) + len(dormant)


def score_harvest(crop: Crop, start: int, clim: Climate, site: dict | None = None,
                  irrigated: bool = False) -> Slot | None:
    """Best season length for this crop planted in `start` (0-11), or None if impossible."""
    best = None
    for active_needed in _season_options(crop):
        walked = _walk_season(crop, start, active_needed, clim)
        if walked is None:
            continue
        active, dormant, months = walked
        slot = _score_window(crop, start, months, active, dormant, clim, site, irrigated)
        if best is None or slot.score > best.score + 0.05:
            best = slot
    return best


def _month_temp_score(crop: Crop, t: float, edge: bool) -> float:
    """One growing month's temperature score. The planting month and the last (ripening)
    month only need to be EDGE_MARGIN_C above the crop's minimum, not in its optimum range:
    the crop is emerging or drying down, not making its yield. Too hot still counts."""
    opt_lo = min(crop.topmn, crop.tmin + EDGE_MARGIN_C) if edge else crop.topmn
    return trapezoid(t, crop.tmin, opt_lo, crop.topmx, crop.tmax)


def _score_window(crop, start, months, active, dormant, clim, site, irrigated) -> Slot:
    factors, evidence, flags, gaps = {}, [], [], []

    temps = [clim.tmean[m] for m in active]
    month_scores = [_month_temp_score(crop, t, i in (0, len(temps) - 1))
                    for i, t in enumerate(temps)]
    # average month, pulled down by the worst month (one very marginal month matters)
    worst, mean = min(month_scores), sum(month_scores) / len(month_scores)
    factors["temperature"] = 0.0 if worst == 0 else 0.5 * mean + 0.5 * worst
    evidence.append(f"Temperature: growing months {_span(active)} average {min(temps):.0f}-"
                    f"{max(temps):.0f} degC (NASA POWER) vs optimum {crop.topmn:g}-{crop.topmx:g}, "
                    f"limits {crop.tmin:g}-{crop.tmax:g} degC (EcoCrop)")

    kill = _kill_temp(crop)
    growing = active[:-1] or active          # the harvest month may see frost safely
    coldest = min(clim.tmin_ext[m] for m in growing)
    factors["frost"] = 1.0 if coldest >= kill else max(0.0, 1 - (kill - coldest) / 4)
    if factors["frost"] < 1:
        flags.append(f"{crop.name}: frost risk while growing (nights about {coldest:.0f} degC, "
                     f"damaged below about {kill:g} degC)")
        evidence.append(f"Frost: coldest growing-season nights about {coldest:.0f} degC vs "
                        f"killing temperature {kill:g} degC")

    if dormant:
        factors["winter"], ev, fl = winter_factor(crop, dormant, clim)
        evidence += ev
        flags += fl

    window = [(start + i) % 12 for i in range(months)]
    if irrigated:
        factors["rain"] = 1.0
    elif crop.rmin is not None and crop.rmax is not None:
        season_rain = sum(clim.precip[m] for m in window)
        yearly_equiv = season_rain * 12 / months
        factors["rain"] = trapezoid(yearly_equiv, crop.rmin, crop.ropmn, crop.ropmx, crop.rmax)
        evidence.append(f"Rain: {season_rain:.0f} mm over its season = {yearly_equiv:.0f} mm/yr "
                        f"equivalent (NASA POWER) vs optimum {crop.ropmn:g}-{crop.ropmx:g} mm (EcoCrop)")
    else:
        gaps.append(f"{crop.name}: no EcoCrop rainfall range")

    factors["soil"], soil_part, ev, gp = soil_factor(crop, site)
    evidence += ev
    gaps += gp
    if factors["soil"] <= OUTSIDE:
        flags.append(f"{crop.name}: soil {soil_part} is outside what it tolerates")

    limiter = min(factors, key=factors.get)
    if limiter == "soil":
        limiter = f"soil ({soil_part})"
    return Slot(crop, start, months, "harvest", round(min(factors.values()), 3),
                limiter, factors, tuple(evidence), tuple(flags), tuple(gaps))


# --------------------------------------------------------------------------------------
# Scoring a cover crop
# --------------------------------------------------------------------------------------
def score_cover(crop: Crop, start: int, months: int, clim: Climate,
                site: dict | None = None) -> Slot | None:
    """Cover crop planted in `start` and ended after `months` months (None if it can't establish).
    Also None beyond the furthest latitude EcoCrop says the crop is grown at: a cover crop
    nobody grows that far from the equator has no local seed or know-how. (Harvest crops are
    not cut this way; EcoCrop's limits for them are too tight, e.g. 48 N for corn.)"""
    lat = (site or {}).get("lat")
    if lat is not None and crop.lat_limit is not None and abs(lat) > crop.lat_limit:
        return None
    window = [(start + i) % 12 for i in range(months)]
    first = window[0]
    if trapezoid(clim.tmean[first], crop.tmin, crop.topmn, crop.topmx, crop.tmax) == 0:
        return None
    factors, evidence, flags, gaps = {}, [], [], []
    kill = _kill_temp(crop)

    # Month by month: growing, dormant (hardy crops in cold months) or killed (then residue).
    growth, dormant, killed_in = [], [], None
    for m in window:
        cold = clim.tmean[m] < crop.tmin or clim.tmin_ext[m] < kill
        hot = clim.tmean[m] >= crop.tmax
        if not cold and not hot:
            growth.append(m)
        elif cold and crop.hardy_to is not None:
            dormant.append(m)
        else:
            killed_in = m
            break
    if not growth or growth[0] != first:
        return None             # can't establish in the planting month
    establish = growth[:2]
    scores = [trapezoid(clim.tmean[m], crop.tmin, crop.topmn, crop.topmx, crop.tmax) for m in establish]
    factors["establishment"] = sum(scores) / len(scores) * (1.0 if len(establish) >= 2 else 0.8)
    evidence.append(f"Establishment: {', '.join(MONTHS[m] for m in establish)} average "
                    + "/".join(f"{clim.tmean[m]:.0f}" for m in establish)
                    + f" degC (NASA POWER) vs optimum {crop.topmn:g}-{crop.topmx:g} degC (EcoCrop)")
    if killed_in is not None:
        evidence.append(f"Killed by cold in {MONTHS[killed_in]}; its residue covers the soil "
                        f"for about {RESIDUE_MONTHS} more months")
    if dormant:
        factors["winter"], ev, fl = winter_factor(crop, dormant, clim)
        evidence += ev
        flags += fl

    factors["soil"], soil_part, ev, gp = soil_factor(crop, site)
    evidence += ev
    gaps += gp
    limiter = min(factors, key=factors.get)
    if limiter == "soil":
        limiter = f"soil ({soil_part})"
    # Alive months plus the residue months; a crop that was never killed covers the whole slot.
    covering = None
    if killed_in is not None:
        covering = min(months, len(growth) + len(dormant) + RESIDUE_MONTHS)
    return Slot(crop, start, months, "cover", round(min(factors.values()), 3),
                limiter, factors, tuple(evidence), tuple(flags), tuple(gaps), covering)


# --------------------------------------------------------------------------------------
# All options for a field
# --------------------------------------------------------------------------------------
def build_slots(crops, clim: Climate, site: dict | None = None, irrigated: bool = False,
                min_score: float = 0.4, per_start: int = 10, per_family: int = 3,
                covers_per_start: int = 4, always: Iterable[str] = (),
                rank: Callable[[Slot], float] | None = None) -> dict[int, list[Slot]]:
    """For each planting month: the best harvest options and the best cover-crop options.

    Harvest options are the first cut of the whole crop list: crops that suit the field
    (suitability >= min_score), ordered by `rank`, keeping the top `per_start` with at most
    `per_family` from one family.
    rank    scores a harvest option, higher = better; options ranked 0 or less are dropped.
            Default: suitability alone. The caller passes Economy.rank to rank by money too.
    always  scientific names kept as harvest options wherever they can grow at all, whatever
            their rank (must-grow crops, crops the field already grows).
    """
    crops = list(crops.values()) if isinstance(crops, dict) else list(crops)
    always = set(always)
    rank = rank or (lambda slot: slot.score)
    by_start: dict[int, list[Slot]] = {}
    for m in range(12):
        harvest = [s for c in crops if c.can_harvest or c.sci in always
                   if (s := score_harvest(c, m, clim, site, irrigated))
                   and (s.score >= min_score or (c.sci in always and s.score > 0))]
        kept, per_fam = [s for s in harvest if s.crop.sci in always], {}
        ranked = sorted((s for s in harvest if s.crop.sci not in always and rank(s) > 0),
                        key=lambda s: -rank(s))
        for s in ranked:
            if per_fam.get(s.crop.family, 0) < per_family and sum(per_fam.values()) < per_start:
                kept.append(s)
                per_fam[s.crop.family] = per_fam.get(s.crop.family, 0) + 1

        covers = {}
        for c in crops:
            if not c.can_cover:
                continue
            options = [s for n in COVER_LENGTHS
                       if (s := score_cover(c, m, n, clim, site)) and s.score >= min_score]
            if options:
                covers[c.sci] = options
        # best cover crop from each family (a grass cover suits a following legume and
        # vice versa), best families first
        best_by_family: dict[str, list[Slot]] = {}
        for opts in sorted(covers.values(), key=lambda o: -max(s.score for s in o)):
            best_by_family.setdefault(opts[0].crop.family, opts)
        for opts in list(best_by_family.values())[:covers_per_start]:
            kept.extend(opts)
        by_start[m] = kept
    return by_start


def best_single_crops(by_start: dict[int, list[Slot]], n: int = 10) -> list[Slot]:
    """Each harvest crop's best planting month, best first."""
    best: dict[str, Slot] = {}
    for slots in by_start.values():
        for s in slots:
            if s.use == "harvest" and (s.crop.sci not in best or best[s.crop.sci].score < s.score):
                best[s.crop.sci] = s
    return sorted(best.values(), key=lambda s: -s.score)[:n]
