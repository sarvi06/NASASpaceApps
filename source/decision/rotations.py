"""Find crop rotations, score each on a report card, and pick the top 3 (plus the current one).

1. search_rotations()  tries many multi-year sequences of harvest crops and cover crops
                       (beam search: keep the best few hundred partial plans at each step).
   Hard rules:  what may follow what (sequence.can_follow), at least one harvest crop per
                year, and every "must grow" crop is in the rotation.
2. score_card()        rates a rotation 0-1 on eight things:
                       fit, soil cover, nitrogen, diversity, crop order, water, income, market.
                       Crop order = how well each harvest crop follows the crop before it
                       (sequence.follow_score). Income and market come from the Economy
                       (economics.py): income is the rotation's real dollars per hectare per
                       year, scored once; market is how widely its crops are grown here.
3. overall score       = weighted sum, weights set by the farmer's priority
                       (balanced / save_water / build_soil / extra_income).
4. pick_top()          best 3 rotations that are clearly different from each other.
5. start_after()       a rotation is a cycle: start it in the year that best follows the
                       crop the field grew last.
6. baseline_rotation() scores the field's current rotation on the same card for comparison.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Iterable

from .crops import Crop
from .economics import Economy
from .sequence import can_follow, follow_score
from .suitability import MONTHS, Climate, Slot, score_harvest

# --------------------------------------------------------------------------------------
# Report card and farmer priorities
# --------------------------------------------------------------------------------------
CARD = {
    "fit": "climate & soil fit",
    "cover": "soil covered (months not bare)",
    "nitrogen": "nitrogen from legumes",
    "diversity": "crop diversity (pest & disease break)",
    "sequence": "crop order (each crop suits the one before it)",
    "water": "low water demand",
    "income": "income per hectare per year (vs the country's typical hectare)",
    "market": "local market (how widely the crops are grown in this country)",
}

PRIORITY_PRESETS = {
    "balanced":     dict(fit=.20, cover=.15, nitrogen=.10, diversity=.10, sequence=.10, water=.10, income=.15, market=.10),
    "save_water":   dict(fit=.25, cover=.10, nitrogen=.10, diversity=.05, sequence=.05, water=.30, income=.10, market=.05),
    "build_soil":   dict(fit=.20, cover=.30, nitrogen=.15, diversity=.10, sequence=.10, water=.05, income=.05, market=.05),
    "extra_income": dict(fit=.20, cover=.10, nitrogen=.05, diversity=.05, sequence=.05, water=.05, income=.35, market=.15),
}

MUST_GROW_BONUS = 1.0        # search bonus for placing a must-grow crop (larger than any plan's score)
ERODIBLE_SLOPE_PCT = 4       # SSURGO slope at/above this ...
ERODIBLE_K = 0.37            # ... or erodibility K at/above this -> soil cover matters more


def resolve_priorities(priorities=None, site: dict | None = None) -> dict:
    """Preset name or {card item: weight} -> weights that add up to 1.
    On steep or easily eroded soil, soil cover gets a little extra weight."""
    if priorities is None:
        priorities = "balanced"
    if isinstance(priorities, str):
        if priorities not in PRIORITY_PRESETS:
            raise ValueError(f"priorities must be one of {sorted(PRIORITY_PRESETS)} or a dict, "
                             f"got {priorities!r}")
        weights = dict(PRIORITY_PRESETS[priorities])
    else:
        unknown = set(priorities) - set(CARD)
        if unknown:
            raise ValueError(f"unknown priority keys {sorted(unknown)}; use {sorted(CARD)}")
        weights = {**PRIORITY_PRESETS["balanced"], **{k: float(v) for k, v in priorities.items()}}
    if site and ((site.get("slope_pct") or 0) >= ERODIBLE_SLOPE_PCT
                 or (site.get("erodibility_k") or 0) >= ERODIBLE_K):
        weights["cover"] += 0.05
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("priority weights must add up to more than 0")
    return {k: v / total for k, v in weights.items()}


def harvests_per_year(clim: Climate) -> int:
    """1 harvest crop a year where the warm season is short; 2 (double cropping) where
    at least 8 months average 10 degC or more."""
    return 2 if sum(t >= 10 for t in clim.tmean) >= 8 else 1


def water_score(crop: Crop, available_rain: float) -> float:
    """1 = needs much less rain than falls, 0 = needs more than falls (EcoCrop optimum minimum)."""
    need = crop.ropmn if crop.ropmn is not None else crop.rmin
    if need is None or available_rain <= 0:
        return 0.5
    return max(0.0, min(1.0, 1.3 - need / available_rain))


def expected_rain(clim: Climate, insights: dict | None = None) -> float:
    """Average yearly rain; if it has been falling, allow for half a decade more of that
    trend (but never less than 80% of the average - short records are noisy)."""
    rain = clim.annual_rain
    trend = (insights or {}).get("rain_trend_mm_per_decade") or 0.0
    return max(0.8 * rain, rain + min(0.0, trend) / 2)


def _legume_n(slot: Slot) -> float:
    """Nitrogen credit: grain legumes export most of their N in the harvest, so count half."""
    if not slot.crop.legume:
        return 0.0
    return 0.5 if slot.use == "harvest" and "forage" not in slot.crop.roles else 1.0


# --------------------------------------------------------------------------------------
# Rotation
# --------------------------------------------------------------------------------------
@dataclass
class Rotation:
    placed: tuple                  # ((absolute start month, Slot), ...); month 0 = Jan of year 1
    years: int
    card: dict = field(default_factory=dict)
    overall: float = 0.0
    income_usd_ha: float = 0.0     # estimated US dollars per hectare per year (priced crops only)
    trusted_income_usd_ha: float = 0.0   # the part of it the income score counts
    cost_usd_ha: float = 0.0       # known growing costs, US dollars per hectare per year
    is_baseline: bool = False
    strategy: str = ""             # why it was picked, e.g. "best for your priority"
    start_note: str = ""           # why it starts with this crop, given the field's last crop
    explanation: dict = field(default_factory=dict)

    @property
    def horizon(self) -> int:
        return self.years * 12

    @property
    def slots(self) -> list[Slot]:
        return [s for _, s in self.placed]

    @property
    def harvests(self) -> list[Slot]:
        return [s for s in self.slots if s.use == "harvest"]

    @property
    def covers(self) -> list[Slot]:
        return [s for s in self.slots if s.use == "cover"]

    def hand_overs(self) -> list[tuple[Slot, Slot]]:
        """(crop before, harvest crop) for every harvest crop; the first follows the last."""
        slots = self.slots
        return [(slots[i - 1], s) for i, s in enumerate(slots) if s.use == "harvest"]

    def covered_months(self) -> set[int]:
        out = set()
        for a, s in self.placed:
            out.update((a + i) % self.horizon for i in range(s.months))
        return out

    def bare_months(self) -> list[int]:
        """Months (0..horizon-1) with nothing growing."""
        covered = self.covered_months()
        return [m for m in range(self.horizon) if m not in covered]

    @property
    def name(self) -> str:
        parts = [s.crop.name + (" (cover)" if s.use == "cover" else "") for s in self.slots]
        return " -> ".join(parts)

    def canonical(self) -> tuple:
        seq = [(s.crop.sci, s.use, a % 12, s.months) for a, s in self.placed]
        return min(tuple(seq[i:] + seq[:i]) for i in range(len(seq)))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "years": self.years,
            "is_current_rotation": self.is_baseline,
            "strategy": self.strategy,
            "start_note": self.start_note,
            "overall": round(self.overall, 3),
            "income_usd_ha_per_year": round(self.income_usd_ha),
            "trusted_income_usd_ha_per_year": round(self.trusted_income_usd_ha),
            "cost_usd_ha_per_year": round(self.cost_usd_ha),
            "card": {k: round(v, 3) for k, v in self.card.items()},
            "steps": [{
                "year": a // 12 % self.years + 1,
                "crop": s.crop.name, "scientific_name": s.crop.sci, "use": s.use,
                "plant": MONTHS[a % 12], "end": MONTHS[(a + s.months - 1) % 12],
                "months": s.months, "suitability": s.score, "limited_by": s.limiter,
                "legume": s.crop.legume, "family": s.crop.family,
                "evidence": list(s.evidence), "risks": list(s.flags),
            } for a, s in self.placed],
            "bare_months": len(self.bare_months()),
            "explanation": self.explanation,
        }


def yearly_income(rot: Rotation, economy: Economy, trusted: bool = False) -> float:
    """Estimated US dollars per hectare per year: each harvest crop's income at an average
    yield, scaled by how well it suits the field, spread over the rotation's years.
    trusted=True gives the figure the ranking counts (Economy.trusted_income)."""
    income = economy.trusted_income if trusted else economy.income
    return sum(income(s.crop) * s.score for s in rot.harvests) / rot.years


def yearly_cost(rot: Rotation, economy: Economy) -> float:
    """Known growing costs in US dollars per hectare per year: the harvest crops' costs
    (entered by the farmer or estimated from them) spread over the rotation's years.
    Cover-crop costs are not known and not included."""
    return sum(economy.cost(s.crop) for s in rot.harvests) / rot.years


def score_card(rot: Rotation, clim: Climate, economy: Economy | None = None,
               insights: dict | None = None, previous: Crop | None = None) -> dict:
    """0-1 scores on each CARD item. With `previous` (the crop the field grew last), crop
    order also counts how well the rotation's first harvest crop follows it."""
    economy = economy or Economy()
    insights = insights or {}
    slots, harvests = rot.slots, rot.harvests
    weights = [s.months * (1.0 if s.use == "harvest" else 0.5) for s in slots]
    fit = sum(s.score * w for s, w in zip(slots, weights)) / sum(weights) if slots else 0.0
    cover = len(rot.covered_months()) / rot.horizon
    nitrogen = min(1.0, sum(_legume_n(s) for s in slots) / (rot.years * 0.5))
    diversity = min(1.0, (len({s.crop.family for s in slots}) - 1) / 3)
    order = [follow_score(a.crop, b.crop)[0] for a, b in rot.hand_overs()]
    if previous is not None and harvests:
        order.append(follow_score(previous, harvests[0].crop)[0])
    sequence = sum(order) / len(order) if order else 0.0
    rain = expected_rain(clim, insights)
    water = sum(water_score(s.crop, rain) for s in harvests) / len(harvests) if harvests else 0.0
    income = economy.score(yearly_income(rot, economy, trusted=True))
    market = sum(economy.market(s.crop) for s in harvests) / len(harvests) if harvests else 0.0
    return {"fit": fit, "cover": cover, "nitrogen": nitrogen, "diversity": diversity,
            "sequence": sequence, "water": water, "income": income, "market": market}


def rate(rot: Rotation, clim: Climate, weights: dict, economy: Economy | None = None,
         insights: dict | None = None, previous: Crop | None = None) -> Rotation:
    economy = economy or Economy()
    rot.card = score_card(rot, clim, economy, insights, previous)
    rot.income_usd_ha = yearly_income(rot, economy)
    rot.trusted_income_usd_ha = yearly_income(rot, economy, trusted=True)
    rot.cost_usd_ha = yearly_cost(rot, economy)
    rot.overall = sum(weights[k] * rot.card[k] for k in CARD)
    return rot


# --------------------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------------------
@dataclass
class _State:
    placed: tuple
    end: int          # next free month
    score: float      # running heuristic (approximate report card)
    s0: int           # calendar month of the first crop


def _last_harvest(placed) -> Slot | None:
    for _, s in reversed(placed):
        if s.use == "harvest":
            return s
    return None


def _gain(placed: tuple, slot: Slot, horizon: int, years: int, weights: dict, rain: float,
          economy: Economy, max_harvests: int = 99,
          must_grow: frozenset = frozenset()) -> float | None:
    """Approximate report-card increase from adding `slot` after the crops in `placed`
    (empty for the first crop of a plan), or None if it breaks a rule."""
    last = placed[-1][1] if placed else None
    c = slot.crop
    if last is not None and not can_follow(last, _last_harvest(placed), slot):
        return None
    n_same = sum(1 for _, s in placed if s.crop.sci == c.sci)
    if slot.use == "harvest" and sum(1 for _, s in placed if s.use == "harvest") >= max_harvests:
        return None

    g = weights["fit"] * slot.score * slot.months / horizon
    g += weights["cover"] * slot.months / horizon
    g += weights["nitrogen"] * _legume_n(slot) / (years * 0.5) * 0.7
    if slot.use == "harvest":
        g += weights["income"] * economy.value(c) * slot.score / years
        g += weights["market"] * economy.market(c) / years
        g += weights["water"] * water_score(c, rain) / years
        if last is not None:
            g += weights["sequence"] * follow_score(last.crop, c)[0] / years
        if c.sci in must_grow and n_same == 0:
            g += MUST_GROW_BONUS                        # keeps these plans in the beam
    g -= 0.05 * n_same                                  # same crop again (harvest or cover)
    if c.family not in {s.crop.family for _, s in placed}:
        g += weights["diversity"] / 3
    return g


def _close(st: _State, horizon: int, years: int, max_idle: int,
           must_grow: frozenset = frozenset()) -> bool:
    """Can this plan repeat (its last crop leads back into its first), and does it hold
    every must-grow crop as a harvest crop?"""
    wrap_gap = st.s0 + horizon - st.end
    if wrap_gap < 0:
        return False
    first, last = st.placed[0][1], st.placed[-1][1]
    harvests = [s for _, s in st.placed if s.use == "harvest"]
    if len(harvests) < years or not must_grow <= {s.crop.sci for s in harvests}:
        return False
    if harvests[-1].crop.family == first.crop.family:
        return False
    if last.use == "cover":
        return wrap_gap <= 2 and last.crop.family != first.crop.family
    return wrap_gap <= max_idle


def _prune(states: list[_State], beam: int, per_sequence: int = 3) -> list[_State]:
    """Keep the best `beam` plans for each starting month (plans that started earlier have
    had longer to collect points, so they are only compared with each other), and at most
    `per_sequence` with the same harvest crops in the same order, so cover-crop variations
    don't crowd out different crop line-ups."""
    kept, per_start, seen = [], defaultdict(int), defaultdict(int)
    for st in sorted(states, key=lambda s: -s.score):
        key = (st.s0, tuple(s.crop.sci for _, s in st.placed if s.use == "harvest"))
        if seen[key] < per_sequence and per_start[st.s0] < beam:
            kept.append(st)
            seen[key] += 1
            per_start[st.s0] += 1
    return kept


def search_rotations(by_start: dict[int, list[Slot]], clim: Climate, weights: dict, years: int = 3,
                     insights: dict | None = None, economy: Economy | None = None,
                     max_idle: int = 11, beam: int = 60, must_grow: Iterable[str] = (),
                     previous: Crop | None = None) -> list[Rotation]:
    """All distinct complete rotations found, rated and sorted best first.

    economy    what each crop earns and how well it sells here (default: no price data)
    must_grow  scientific names every rotation must contain as a harvest crop
    previous   the crop the field grew last: each rotation starts in the year that best
               follows it, and that hand-over counts in its crop-order score
    """
    horizon = years * 12
    rain = expected_rain(clim, insights)
    max_harvests = years * harvests_per_year(clim)
    must_grow = frozenset(must_grow)
    economy = economy or Economy()
    levels: dict[int, list[_State]] = defaultdict(list)
    for s0 in range(12):
        for slot in by_start.get(s0, []):
            if slot.use == "harvest" and slot.months <= horizon:
                g = _gain((), slot, horizon, years, weights, rain, economy, max_harvests, must_grow)
                levels[s0 + slot.months].append(_State(((s0, slot),), s0 + slot.months, g, s0))

    finals: dict[tuple, Rotation] = {}
    for t in range(0, 12 + horizon + 1):
        states = _prune(levels.pop(t, []), beam)
        for st in states:
            if _close(st, horizon, years, max_idle, must_grow):
                rot = Rotation(st.placed, years)
                key = rot.canonical()
                if key not in finals:
                    finals[key] = rot
            last = st.placed[-1][1]
            if last.use == "harvest":
                options = [("harvest", g) for g in range(max_idle + 1)] + [("cover", 0), ("cover", 1)]
            else:
                options = [("harvest", g) for g in range(3)]
            for use, gap in options:
                start = t + gap
                if start >= st.s0 + horizon:
                    continue
                for slot in by_start.get(start % 12, []):
                    if slot.use != use:
                        continue
                    end = start + slot.months
                    if end > st.s0 + horizon:
                        continue
                    g = _gain(st.placed, slot, horizon, years, weights, rain, economy,
                              max_harvests, must_grow)
                    if g is None:
                        continue
                    levels[end].append(_State(st.placed + ((start, slot),), end, st.score + g, st.s0))

    found = [start_after(r, previous) if previous else r for r in finals.values()]
    rated = [rate(r, clim, weights, economy, insights, previous) for r in found]
    return sorted(rated, key=lambda r: -r.overall)


def _overlap(a: Rotation, b: Rotation, shared: Iterable[str] = ()) -> float:
    """Share of crops (and their use) two rotations have in common, 0-1, not counting the
    `shared` crops that every rotation was required to contain."""
    shared = set(shared)
    ka = {(s.crop.sci, s.use) for s in a.slots if s.crop.sci not in shared}
    kb = {(s.crop.sci, s.use) for s in b.slots if s.crop.sci not in shared}
    return len(ka & kb) / len(ka | kb) if ka | kb else 1.0


def pick_top(rotations: list[Rotation], n: int = 3, familiar: set | None = None,
             max_overlap: float = 0.5, shared: Iterable[str] = ()) -> list[Rotation]:
    """Pick `n` clearly different strategies from rotations sorted best first:
      1. the best rotation for the farmer's priorities
      2. the best one built mostly on crops the field already grows (if history is known)
      3+ the next best that differ from those already picked
    `shared` = must-grow crops, which are in every rotation and so don't count as overlap.
    """
    chosen: list[Rotation] = []

    def distinct(r):
        return all(_overlap(r, c, shared) <= max_overlap for c in chosen)

    def take(r, strategy):
        r.strategy = strategy
        chosen.append(r)

    if rotations:
        take(rotations[0], "best match for your priorities")
    if familiar and len(chosen) < n:
        close_to_current = [r for r in rotations[1:]
                            if len({s.crop.sci for s in r.harvests} - familiar) <= 1]
        pick = next((r for r in close_to_current if distinct(r)), None) or next(
            (r for r in close_to_current if all(_overlap(r, c, shared) < 1 for c in chosen)), None)
        if pick is not None:
            take(pick, "builds on the crops you already grow")
    for r in rotations:
        if len(chosen) >= n:
            break
        if r not in chosen and distinct(r):
            take(r, "a different direction worth comparing")
    return chosen


# --------------------------------------------------------------------------------------
# Where to start the cycle, given what the field grew last
# --------------------------------------------------------------------------------------
def start_after(rot: Rotation, previous: Crop) -> Rotation:
    """The same rotation, started in the year whose first harvest crop best follows `previous`.

    A rotation repeats, so its scores don't depend on where it starts; the field's last crop
    only decides which year of the cycle to begin with. Ties keep the earlier year."""
    def from_year(k: int) -> tuple:
        return tuple(sorted((((a - 12 * k) % rot.horizon, s) for a, s in rot.placed),
                            key=lambda p: p[0]))

    def first_harvest(placed: tuple) -> Crop:
        return next(s.crop for _, s in placed if s.use == "harvest")

    options = [from_year(k) for k in range(rot.years)]
    best = max(options, key=lambda placed: follow_score(previous, first_harvest(placed))[0])
    reason = follow_score(previous, first_harvest(best))[1]
    return replace(rot, placed=best, start_note=f"Starts this way because the field last grew "
                                                f"{previous.name} ({reason}).")


# --------------------------------------------------------------------------------------
# The current rotation, scored the same way
# --------------------------------------------------------------------------------------
def baseline_rotation(crops: list[Crop], clim: Climate, weights: dict, site: dict | None = None,
                      irrigated: bool = False, insights: dict | None = None,
                      economy: Economy | None = None) -> Rotation | None:
    """One crop per year, each planted in its best month; no cover crops (as CropScape shows)."""
    placed, prev_end = [], 0
    for year, crop in enumerate(crops):
        options = [s for m in range(12) if (s := score_harvest(crop, m, clim, site, irrigated))]
        if not options:
            continue
        slot = max(options, key=lambda s: (s.score, -s.start))
        start = max(12 * year + slot.start, prev_end)
        placed.append((start, slot))
        prev_end = start + slot.months
    if not placed:
        return None
    rot = Rotation(tuple(placed), max(1, len(crops)), is_baseline=True)
    return rate(rot, clim, weights, economy, insights)


def calendar_grid(rot: Rotation) -> str:
    """Year-by-month grid of what is in the ground. CAPITALS = harvest crop,
    lower case = cover crop, '.' = bare soil."""
    codes: dict[str, str] = {}
    cells = [" . "] * rot.horizon
    for a, s in rot.placed:
        code = codes.setdefault(s.crop.sci, s.crop.name.replace(" ", "")[:3])
        code = code.upper() if s.use == "harvest" else code.lower()
        for i in range(s.months):
            cells[(a + i) % rot.horizon] = f"{code:^3}"
    lines = ["      " + " ".join(f"{m:^3}" for m in MONTHS)]
    for y in range(rot.years):
        lines.append(f"  Y{y + 1}  " + " ".join(cells[12 * y:12 * y + 12]))
    names = {}
    for s in rot.slots:
        names.setdefault(codes[s.crop.sci].upper(), s.crop.name)
    return "\n".join(lines) + "\n  " + ", ".join(f"{k} = {v}" for k, v in names.items())
