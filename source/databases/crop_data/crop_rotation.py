"""Find optimal crop rotations for a latitude/longitude using FAO EcoCrop data.

Pipeline
--------
1. Climate   : monthly climatology (mean temp, frost extreme, rainfall) for the
               point, from the free Open-Meteo archive API (cached locally),
               or from your own CSV.
2. Suitability: for every crop x planting month, score how well the growing
               window matches the crop's EcoCrop temperature / rainfall / pH
               ranges (0 = impossible, 1 = ideal).
3. Rotation  : beam search over sequences of crops across N years, rewarding
               land use and good agronomy (legumes, no same-family repeats).

Dependencies
------------
    pip install pandas pyarrow
    (ecocrop_loader.py must sit in the same folder)

Usage
-----
    python crop_rotation.py --lat 51.45 --lon -2.58
    python crop_rotation.py --lat 26.8 --lon 80.9 --years 2 --irrigated \
        --only rice wheat chickpea lentil mustard maize
    python crop_rotation.py --lat 51.45 --lon -2.58 --ph 6.5 --top 8
    python crop_rotation.py --lat 0 --lon 0 --climate-csv my_climate.csv
"""
from __future__ import annotations

import argparse
import json
import math
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from ecocroploader import (COLUMN_ALIASES, clean_dataframe, load_ecocrop,
                            resolve_columns)

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS_PER_MONTH = 30.4
LEGUME_FAMILIES = {"fabaceae", "leguminosae"}

# Rotation scoring weights (tweak to taste)
W_FIRST_LEGUME = 0.05     # rotation contains at least one legume
W_LEGUME_THEN_OTHER = 0.03  # nitrogen carry-over to the next non-legume crop
W_FAMILY_REPEAT = -0.03   # same family again (non-adjacent) in the rotation
W_SPECIES_REPEAT = -0.08  # same species again (non-adjacent) in the rotation


# ==========================================================================
# 1. CLIMATE
# ==========================================================================
@dataclass
class Climate:
    tmean: List[float]      # mean daily temperature per month (deg C)
    tmin_ext: List[float]   # average of each year's lowest daily min per month
    precip: List[float]     # mean monthly rainfall total (mm)

    def table(self) -> str:
        rows = [f"{'':<6}" + "".join(f"{m:>7}" for m in MONTHS),
                f"{'Tmean':<6}" + "".join(f"{v:7.1f}" for v in self.tmean),
                f"{'Tmin':<6}" + "".join(f"{v:7.1f}" for v in self.tmin_ext),
                f"{'Rain':<6}" + "".join(f"{v:7.0f}" for v in self.precip)]
        return "\n".join(rows)


def fetch_climate(lat: float, lon: float, years: int = 10,
                  cache_dir: Path = Path(".climate_cache")) -> Climate:
    """Monthly climatology from Open-Meteo's historical archive (no API key)."""
    end_year = date.today().year - 1
    start_year = end_year - years + 1
    cache_dir.mkdir(exist_ok=True)
    cache = cache_dir / f"om_{lat:.3f}_{lon:.3f}_{start_year}_{end_year}.json"

    if cache.exists():
        payload = json.loads(cache.read_text())
        print(f"[climate] using cached {cache}")
    else:
        params = {
            "latitude": lat, "longitude": lon,
            "start_date": f"{start_year}-01-01",
            "end_date": f"{end_year}-12-31",
            "daily": "temperature_2m_mean,temperature_2m_min,precipitation_sum",
            "timezone": "UTC",
        }
        url = ("https://archive-api.open-meteo.com/v1/archive?"
               + urllib.parse.urlencode(params))
        print(f"[climate] downloading {start_year}-{end_year} daily data "
              f"for ({lat}, {lon})")
        with urllib.request.urlopen(url, timeout=120) as resp:
            payload = json.loads(resp.read().decode())
        cache.write_text(json.dumps(payload))

    if "daily" not in payload:
        raise RuntimeError(f"Open-Meteo returned no data: {payload}")

    df = pd.DataFrame(payload["daily"])
    df["time"] = pd.to_datetime(df["time"])
    df["year"], df["month"] = df["time"].dt.year, df["time"].dt.month

    tmean = df.groupby("month")["temperature_2m_mean"].mean()
    tmin_ext = (df.groupby(["year", "month"])["temperature_2m_min"].min()
                .groupby("month").mean())
    precip = (df.groupby(["year", "month"])["precipitation_sum"].sum()
              .groupby("month").mean())
    idx = range(1, 13)
    return Climate(tmean=tmean.reindex(idx).tolist(),
                   tmin_ext=tmin_ext.reindex(idx).tolist(),
                   precip=precip.reindex(idx).tolist())


def load_climate_csv(path: str) -> Climate:
    """CSV with columns: month (1-12), tmean, tmin_ext, precip."""
    df = pd.read_csv(path).sort_values("month")
    if len(df) != 12:
        raise ValueError("climate CSV must have exactly 12 monthly rows")
    return Climate(df["tmean"].tolist(), df["tmin_ext"].tolist(),
                   df["precip"].tolist())


# ==========================================================================
# 2. CROPS
# ==========================================================================
@dataclass(frozen=True)
class Crop:
    key: int
    sci: str
    common: str
    family: str
    is_legume: bool
    tmin: float
    tmax: float
    topmn: float
    topmx: float
    ktmp: Optional[float]
    rmin: Optional[float]
    rmax: Optional[float]
    ropmn: Optional[float]
    ropmx: Optional[float]
    phmin: Optional[float]
    phmax: Optional[float]
    phopmn: Optional[float]
    phopmx: Optional[float]
    cycle_days: float

    @property
    def label(self) -> str:
        name = self.common if self.common and self.common != "nan" else self.sci
        return f"{name} ({self.sci})" if name != self.sci else self.sci

    @property
    def months(self) -> int:
        return max(1, math.ceil(self.cycle_days / DAYS_PER_MONTH))


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def build_crops(df: pd.DataFrame, max_cycle_days: float,
                only: Optional[Sequence[str]] = None,
                exclude: Optional[Sequence[str]] = None) -> List[Crop]:
    """Turn the raw EcoCrop table into Crop objects, dropping unusable rows."""
    resolved = resolve_columns(df, COLUMN_ALIASES)
    clean = clean_dataframe(df, resolved)
    for needed in ("scientific_name", "tmin", "tmax", "topmn", "topmx", "gmin"):
        if needed not in clean.columns:
            raise RuntimeError(
                f"EcoCrop table has no usable '{needed}' column. "
                f"Run `python ecocrop_loader.py inspect` and extend "
                f"COLUMN_ALIASES.")

    only_l = [s.lower() for s in only] if only else None
    excl_l = [s.lower() for s in exclude] if exclude else []

    crops: List[Crop] = []
    seen = set()
    for _, r in clean.iterrows():
        sci = str(r.get("scientific_name") or "").strip()
        common = str(r.get("common_name") or "").strip()
        if not sci or sci.lower() in seen:
            continue
        haystack = f"{sci} {common}".lower()
        if only_l and not any(p in haystack for p in only_l):
            continue
        if any(p in haystack for p in excl_l):
            continue

        tmin, tmax = _num(r.get("tmin")), _num(r.get("tmax"))
        topmn, topmx = _num(r.get("topmn")), _num(r.get("topmx"))
        gmin, gmax = _num(r.get("gmin")), _num(r.get("gmax"))
        if None in (tmin, tmax, topmn, topmx, gmin):
            continue
        if not (tmin <= topmn <= topmx <= tmax):
            continue
        cycle = (gmin + gmax) / 2 if gmax and gmax >= gmin else gmin
        if cycle <= 0 or cycle > max_cycle_days:
            continue

        family = str(r.get("family") or "").strip()
        category = str(r.get("category") or "").lower()
        is_legume = (family.lower() in LEGUME_FAMILIES
                     or "legume" in category or "pulse" in category)

        seen.add(sci.lower())
        crops.append(Crop(
            key=len(crops), sci=sci, common=common, family=family or sci,
            is_legume=is_legume, tmin=tmin, tmax=tmax, topmn=topmn,
            topmx=topmx, ktmp=_num(r.get("ktmp")),
            rmin=_num(r.get("rmin")), rmax=_num(r.get("rmax")),
            ropmn=_num(r.get("ropmn")), ropmx=_num(r.get("ropmx")),
            phmin=_num(r.get("ph_min")), phmax=_num(r.get("ph_max")),
            phopmn=_num(r.get("ph_opt_min")), phopmx=_num(r.get("ph_opt_max")),
            cycle_days=cycle))
    return crops


# ==========================================================================
# 3. SUITABILITY  (crop x planting month)
# ==========================================================================
def trapezoid(x: float, lo: Optional[float], opt_lo: Optional[float],
              opt_hi: Optional[float], hi: Optional[float]) -> float:
    """0 outside [lo, hi], 1 inside [opt_lo, opt_hi], linear ramps between.

    Missing bounds -> 1.0 (no constraint).
    """
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


@dataclass(frozen=True)
class Slot:
    crop: Crop
    start: int       # calendar month index 0-11
    months: int
    score: float
    limiter: str     # which factor limits the score


def score_slot(crop: Crop, start: int, clim: Climate, irrigated: bool,
               ph: Optional[float], rain_mode: str) -> Slot:
    n = crop.months
    window = [(start + i) % 12 for i in range(n)]

    # Temperature: the worst month limits (Liebig's law of the minimum)
    temp = min(trapezoid(clim.tmean[m], crop.tmin, crop.topmn,
                         crop.topmx, crop.tmax) for m in window)
    if crop.ktmp is not None and min(clim.tmin_ext[m] for m in window) < crop.ktmp:
        temp = 0.0  # killing frost inside the growing window

    # Rainfall
    rain = 1.0
    if not irrigated and crop.rmin is not None and crop.rmax is not None:
        total = sum(clim.precip[m] for m in window)
        if rain_mode == "annualised":
            total *= 365.0 / (n * DAYS_PER_MONTH)
        rain = trapezoid(total, crop.rmin, crop.ropmn, crop.ropmx, crop.rmax)

    # Soil pH (optional)
    ph_score = 1.0
    if ph is not None:
        ph_score = trapezoid(ph, crop.phmin, crop.phopmn,
                             crop.phopmx, crop.phmax)

    factors = {"temperature": temp, "rainfall": rain, "pH": ph_score}
    limiter = min(factors, key=factors.get)
    return Slot(crop, start, n, factors[limiter], limiter)


def build_slots(crops: List[Crop], clim: Climate, irrigated: bool,
                ph: Optional[float], rain_mode: str, min_suit: float,
                per_start: int, per_family: int) -> Dict[int, List[Slot]]:
    """For each calendar start month, keep the best viable crops."""
    by_start: Dict[int, List[Slot]] = {}
    for m in range(12):
        slots = [score_slot(c, m, clim, irrigated, ph, rain_mode) for c in crops]
        slots = sorted((s for s in slots if s.score >= min_suit),
                       key=lambda s: -s.score)
        kept, fam_n = [], defaultdict(int)
        for s in slots:
            if fam_n[s.crop.family] >= per_family:
                continue
            kept.append(s)
            fam_n[s.crop.family] += 1
            if len(kept) >= per_start:
                break
        by_start[m] = kept
    return by_start


# ==========================================================================
# 4. ROTATION SEARCH
# ==========================================================================
@dataclass
class State:
    placed: Tuple[Tuple[int, Slot], ...]   # (absolute start month, slot)
    end: int
    score: float


@dataclass
class Rotation:
    placed: Tuple[Tuple[int, Slot], ...]
    score: float
    horizon: int

    @property
    def utilisation(self) -> float:
        return sum(s.months for _, s in self.placed) / self.horizon

    @property
    def mean_suitability(self) -> float:
        return sum(s.score for _, s in self.placed) / len(self.placed)

    def canonical(self) -> Tuple:
        seq = [(s.crop.key, a % 12) for a, s in self.placed]
        return min(tuple(seq[i:] + seq[:i]) for i in range(len(seq)))


def _gain(state: State, slot: Slot, horizon: int) -> Optional[float]:
    """Score increment for appending `slot`, or None if it breaks a hard rule."""
    c = slot.crop
    gain = slot.score * slot.months / horizon      # suitability-weighted land use
    if state.placed:
        last = state.placed[-1][1].crop
        if last.family == c.family:
            return None                            # never same family back-to-back
        if last.is_legume and not c.is_legume:
            gain += W_LEGUME_THEN_OTHER
    for _, s in state.placed:
        if s.crop.key == c.key:
            gain += W_SPECIES_REPEAT
        elif s.crop.family == c.family:
            gain += W_FAMILY_REPEAT
    if c.is_legume and not any(s.crop.is_legume for _, s in state.placed):
        gain += W_FIRST_LEGUME
    return gain


def search_rotations(by_start: Dict[int, List[Slot]], years: int,
                     turnaround: int, max_idle: int, beam: int) -> List[Rotation]:
    """Time-ordered beam search; one pass per calendar start offset."""
    horizon = years * 12
    finals: Dict[Tuple, Rotation] = {}

    for s0 in range(12):
        end_t = s0 + horizon
        levels: Dict[int, List[State]] = defaultdict(list)
        levels[s0].append(State((), s0, 0.0))

        for t in range(s0, end_t + 1):
            states = levels.pop(t, [])
            if not states:
                continue
            states.sort(key=lambda s: -s.score)
            states = states[:beam]

            for st in states:
                # Does this state close the cycle cleanly?
                if st.placed and end_t - turnaround - max_idle <= t <= end_t - turnaround:
                    first, last = st.placed[0][1].crop, st.placed[-1][1].crop
                    if first.family != last.family:
                        bonus = (W_LEGUME_THEN_OTHER
                                 if last.is_legume and not first.is_legume else 0.0)
                        rot = Rotation(st.placed, st.score + bonus, horizon)
                        k = rot.canonical()
                        if k not in finals or finals[k].score < rot.score:
                            finals[k] = rot

                # Extend with the next crop
                gaps = [0] if not st.placed else range(turnaround,
                                                       turnaround + max_idle + 1)
                for gap in gaps:
                    start = t + gap
                    for slot in by_start[start % 12]:
                        end = start + slot.months
                        if end > end_t:
                            continue
                        g = _gain(st, slot, horizon)
                        if g is None:
                            continue
                        levels[end].append(State(
                            st.placed + ((start, slot),), end, st.score + g))

    return sorted(finals.values(), key=lambda r: -r.score)


def pick_diverse(rots: List[Rotation], top: int, max_overlap: float) -> List[Rotation]:
    """Skip near-duplicates (same crops, minor swaps) so the top-N differ."""
    chosen: List[Rotation] = []
    for r in rots:
        keys = {s.crop.key for _, s in r.placed}
        ok = True
        for c in chosen:
            ck = {s.crop.key for _, s in c.placed}
            if len(keys & ck) / len(keys | ck) > max_overlap:
                ok = False
                break
        if ok:
            chosen.append(r)
        if len(chosen) >= top:
            break
    return chosen


# ==========================================================================
# 5. REPORTING
# ==========================================================================
def print_best_singles(by_start: Dict[int, List[Slot]], n: int = 12) -> None:
    best: Dict[int, Slot] = {}
    for slots in by_start.values():
        for s in slots:
            if s.crop.key not in best or best[s.crop.key].score < s.score:
                best[s.crop.key] = s
    print("\nBest individual crops for this site (peak suitability, best planting month)")
    print("-" * 78)
    for s in sorted(best.values(), key=lambda s: -s.score)[:n]:
        print(f"  {s.score:4.2f}  {MONTHS[s.start]} -> {MONTHS[(s.start + s.months - 1) % 12]}"
              f"  {s.crop.label[:52]}")


def print_rotation(i: int, r: Rotation) -> None:
    fams = {s.crop.family for _, s in r.placed}
    has_leg = any(s.crop.is_legume for _, s in r.placed)
    print(f"\n#{i}  score {r.score:.3f}   crops {len(r.placed)}   "
          f"land use {r.utilisation:.0%}   mean suitability {r.mean_suitability:.2f}   "
          f"families {len(fams)}   legume {'yes' if has_leg else 'no'}")
    for a, s in r.placed:
        yr = a // 12 + 1
        m0 = a % 12
        m1 = (a + s.months - 1) % 12
        tag = " [legume]" if s.crop.is_legume else ""
        print(f"   Y{yr}  {MONTHS[m0]} -> {MONTHS[m1]}  ({s.months} mo)  "
              f"suit {s.score:.2f} (limit: {s.limiter})  "
              f"{s.crop.label[:46]}  <{s.crop.family}>{tag}")
    print(f"   (repeats after year {r.horizon // 12})")


# ==========================================================================
# 6. CLI
# ==========================================================================
def main() -> None:
    p = argparse.ArgumentParser(
        description="Optimal crop rotations for a lat/lon from FAO EcoCrop")
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--years", type=int, default=3,
                   help="length of the rotation cycle in years (default 3)")
    p.add_argument("--top", type=int, default=5, help="rotations to show")
    p.add_argument("--irrigated", action="store_true",
                   help="ignore rainfall limits")
    p.add_argument("--ph", type=float, default=None, help="soil pH, if known")
    p.add_argument("--only", nargs="*", default=None,
                   help="restrict to crops whose names contain these substrings")
    p.add_argument("--exclude", nargs="*", default=None,
                   help="drop crops whose names contain these substrings")
    p.add_argument("--max-cycle-days", type=float, default=300,
                   help="drop crops with longer cycles (perennials etc.)")
    p.add_argument("--min-suit", type=float, default=0.4,
                   help="minimum suitability for a crop to be considered")
    p.add_argument("--turnaround", type=int, default=1,
                   help="months between crops for harvest/land prep")
    p.add_argument("--max-idle", type=int, default=11,
                   help="max fallow months between crops (default 11 = one crop a year is fine)")
    p.add_argument("--rain-mode", choices=["annualised", "season"],
                   default="annualised",
                   help="compare EcoCrop rainfall to growing-season rain scaled "
                        "to a year (default) or the raw season total")
    p.add_argument("--beam", type=int, default=200)
    p.add_argument("--per-start", type=int, default=8,
                   help="max candidate crops per planting month")
    p.add_argument("--per-family", type=int, default=2,
                   help="max candidates from one family per planting month")
    p.add_argument("--diversity", type=float, default=0.6,
                   help="max crop-set overlap (Jaccard) between listed "
                        "rotations; 1.0 disables")
    p.add_argument("--climate-csv", default=None,
                   help="use your own monthly climate instead of Open-Meteo")
    p.add_argument("--climate-years", type=int, default=10)
    p.add_argument("--force-download", action="store_true",
                   help="re-download the EcoCrop parquet")
    args = p.parse_args()

    # ---- climate ----
    clim = (load_climate_csv(args.climate_csv) if args.climate_csv
            else fetch_climate(args.lat, args.lon, args.climate_years))
    print(f"\nClimate at ({args.lat}, {args.lon})")
    print(clim.table())

    # ---- crops ----
    df = load_ecocrop(force_download=args.force_download)
    crops = build_crops(df, args.max_cycle_days, args.only, args.exclude)
    print(f"\n[crops] {len(crops)} candidate crops after filtering")
    if not crops:
        print("No usable crops. Loosen --only/--max-cycle-days.")
        return

    # ---- suitability ----
    by_start = build_slots(crops, clim, args.irrigated, args.ph, args.rain_mode,
                           args.min_suit, args.per_start, args.per_family)
    n_slots = sum(len(v) for v in by_start.values())
    if n_slots == 0:
        print("No crop reaches the minimum suitability here. Try --irrigated, "
              "a lower --min-suit, or check the climate table above.")
        return
    print_best_singles(by_start)

    # ---- rotations ----
    rots = search_rotations(by_start, args.years, args.turnaround,
                            args.max_idle, args.beam)
    rots = pick_diverse(rots, args.top, args.diversity)
    if not rots:
        print("\nNo valid rotation found. Try more --years, a lower "
              "--min-suit, or a larger --max-idle.")
        return
    print(f"\n{'=' * 78}\nTop {len(rots)} {args.years}-year rotations\n{'=' * 78}")
    for i, r in enumerate(rots, 1):
        print_rotation(i, r)


if __name__ == "__main__":
    main()