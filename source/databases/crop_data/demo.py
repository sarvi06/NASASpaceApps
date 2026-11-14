"""Demo: show the optimal crop rotation for a location.

Two modes
---------
OFFLINE (default) - built-in sample crops + a built-in climate for a preset
                    place. Needs no network, runs instantly.

    python demo.py                      # Bristol, UK
    python demo.py --place lucknow      # Lucknow, India (irrigated)

LIVE              - real FAO EcoCrop data + real climate for any lat/lon
                    (downloads EcoCrop and queries Open-Meteo; needs internet).

    python demo.py --lat 51.45 --lon -2.58 --only wheat barley pea bean potato
    python demo.py --lat 26.85 --lon 80.95 --irrigated --only rice wheat chickpea lentil mustard maize

Keep this file next to crop_rotation.py and ecocrop_loader.py.
"""
from __future__ import annotations

import argparse
from typing import List

import pandas as pd

import crop_rotation as cr
from ecocroploader import load_ecocrop


# ==========================================================================
# Offline sample data (illustrative values, NOT official EcoCrop numbers)
# ==========================================================================
_COLS = ["scientific_name", "common_name", "family", "category",
         "tmin", "tmax", "topmn", "topmx", "ktmp",
         "rmin", "rmax", "ropmn", "ropmx", "gmin", "gmax"]
_ROWS = [
    ("Triticum aestivum",   "wheat",    "Poaceae",      "cereals",  3, 32, 12, 22, -10,  250, 1750,  450,  900,  90, 180),
    ("Hordeum vulgare",     "barley",   "Poaceae",      "cereals",  3, 30, 12, 22,  -8,  250, 2000,  400,  800,  90, 150),
    ("Zea mays",            "maize",    "Poaceae",      "cereals", 10, 35, 18, 25,   2,  400, 2500,  600, 1200,  90, 140),
    ("Oryza sativa",        "rice",     "Poaceae",      "cereals", 10, 40, 20, 30,   5, 1000, 3000, 1500, 2000, 100, 150),
    ("Pisum sativum",       "pea",      "Fabaceae",     "legumes",  4, 28, 13, 18,  -5,  300, 2000,  500, 1000,  60, 100),
    ("Vicia faba",          "faba bean","Fabaceae",     "legumes",  4, 28, 10, 18,  -8,  400, 2000,  600, 1200, 100, 160),
    ("Cicer arietinum",     "chickpea", "Fabaceae",     "legumes",  5, 35, 15, 25,  -3,  300, 1500,  400,  800,  90, 150),
    ("Lens culinaris",      "lentil",   "Fabaceae",     "legumes",  5, 32, 12, 22,  -4,  250, 1500,  350,  700,  80, 130),
    ("Glycine max",         "soybean",  "Fabaceae",     "legumes", 10, 38, 20, 30,   2,  450, 1800,  600, 1000,  90, 130),
    ("Brassica napus",      "rapeseed", "Brassicaceae", "oil",      3, 30, 10, 20, -12,  300, 2000,  500, 1000, 120, 200),
    ("Brassica juncea",     "mustard",  "Brassicaceae", "oil",      5, 35, 15, 25,  -3,  300, 1800,  400,  900,  90, 140),
    ("Solanum tuberosum",   "potato",   "Solanaceae",   "roots",    7, 25, 10, 15,   0,  400, 2000,  600, 1200,  90, 150),
]
SAMPLE_CROPS = pd.DataFrame(_ROWS, columns=_COLS)

#            Jan   Feb   Mar   Apr   May   Jun   Jul   Aug   Sep   Oct   Nov   Dec
PLACES = {
    "bristol": dict(
        name="Bristol, UK (51.45N, 2.58W)", irrigated=False,
        tmean=[5.0, 5.5, 7.5, 9.5, 12.5, 15.5, 17.5, 17.0, 14.5, 11.5, 8.0, 5.5],
        tmin_ext=[-4, -4, -3, -1, 2, 5, 8, 7, 4, 0, -2, -4],
        precip=[85, 65, 60, 55, 60, 60, 55, 65, 65, 90, 95, 95]),
    "lucknow": dict(
        name="Lucknow, India (26.85N, 80.95E)", irrigated=True,
        tmean=[15.5, 18.5, 24.0, 29.5, 32.5, 33.0, 30.0, 29.5, 28.5, 25.0, 20.0, 16.0],
        tmin_ext=[3, 6, 11, 17, 22, 24, 24, 24, 22, 15, 9, 4],
        precip=[20, 17, 10, 6, 18, 95, 300, 300, 190, 40, 5, 6]),
}


# ==========================================================================
# Pretty output
# ==========================================================================
def calendar_grid(rot: cr.Rotation) -> str:
    """Year-by-month grid of what is in the ground. Columns start at the first
    planting month, so each row is exactly one year of the cycle."""
    years = rot.horizon // 12
    base = rot.placed[0][0]
    codes: dict = {}
    grid = [[" . "] * 12 for _ in range(years)]
    for a, s in rot.placed:
        name = s.crop.common if s.crop.common not in ("", "nan") else s.crop.sci
        code = codes.setdefault(s.crop.key, name[:3].upper())
        for i in range(s.months):
            t = a + i - base
            if 0 <= t < rot.horizon:
                grid[t // 12][t % 12] = f"{code:^3}"
    cols = [cr.MONTHS[(base + c) % 12] for c in range(12)]
    lines = ["      " + " ".join(f"{m:^3}" for m in cols)]
    lines += [f"  Y{y + 1}  " + " ".join(row) for y, row in enumerate(grid)]
    legend = {}
    for _, s in rot.placed:
        legend[codes[s.crop.key]] = s.crop.common or s.crop.sci
    return "\n".join(lines) + "\n  " + ", ".join(f"{k} = {v}" for k, v in legend.items())


# ==========================================================================
# Main
# ==========================================================================
def main() -> None:
    p = argparse.ArgumentParser(description="Crop rotation demo")
    p.add_argument("--place", choices=sorted(PLACES), default="bristol",
                   help="offline preset (used when --lat/--lon not given)")
    p.add_argument("--lat", type=float)
    p.add_argument("--lon", type=float)
    p.add_argument("--years", type=int, default=3)
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--only", nargs="*", default=None,
                   help="live mode: restrict to crops matching these names")
    p.add_argument("--irrigated", action=argparse.BooleanOptionalAction,
                   default=None, help="override the preset's irrigation setting")
    args = p.parse_args()

    live = args.lat is not None and args.lon is not None
    if (args.lat is None) != (args.lon is None):
        p.error("give both --lat and --lon for live mode")

    # ---- inputs ----
    if live:
        title = f"({args.lat}, {args.lon})  [LIVE: real EcoCrop + Open-Meteo]"
        clim = cr.fetch_climate(args.lat, args.lon)
        crops = cr.build_crops(load_ecocrop(), 300, only=args.only)
        irrigated = bool(args.irrigated)
    else:
        place = PLACES[args.place]
        title = f"{place['name']}  [OFFLINE sample data]"
        clim = cr.Climate(place["tmean"], place["tmin_ext"], place["precip"])
        crops = cr.build_crops(SAMPLE_CROPS, 300)
        irrigated = place["irrigated"] if args.irrigated is None else args.irrigated

    print(f"\n{'=' * 78}\n  CROP ROTATION DEMO - {title}")
    print(f"  {len(crops)} candidate crops | {args.years}-year cycle | "
          f"{'irrigated' if irrigated else 'rain-fed'}\n{'=' * 78}\n")
    print("Climate (monthly)")
    print(clim.table())

    if not crops:
        print("\nNo candidate crops after filtering.")
        return

    # ---- score + search ----
    by_start = cr.build_slots(crops, clim, irrigated, None, "annualised",
                              min_suit=0.4, per_start=8, per_family=2)
    cr.print_best_singles(by_start, n=8)
    rots = cr.pick_diverse(
        cr.search_rotations(by_start, args.years, turnaround=1,
                            max_idle=11, beam=200),
        args.top, max_overlap=0.6)

    if not rots:
        print("\nNo valid rotation found (try --irrigated, or more --years).")
        return

    # ---- results ----
    best = rots[0]
    print(f"\n{'=' * 78}\n  OPTIMAL {args.years}-YEAR ROTATION\n{'=' * 78}")
    cr.print_rotation(1, best)
    print("\n  Calendar (crop in the ground each month; . = fallow)")
    print(calendar_grid(best))

    if len(rots) > 1:
        print(f"\n{'-' * 78}\n  Alternatives\n{'-' * 78}")
        for i, r in enumerate(rots[1:], 2):
            cr.print_rotation(i, r)
    print("\nNote: climate-only model. Soil, pests, markets and yields are not "
          "considered.\n")


if __name__ == "__main__":
    main()