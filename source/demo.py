"""Command-line stand-in for the front end: pick a location and dates, get the top 3 rotations.

Run from the repo root:
    .venv\\Scripts\\python.exe source\\demo.py                                  (Iowa test field, last 10 years)
    .venv\\Scripts\\python.exe source\\demo.py --lat 42.065 --lon -93.73 --start 2015-01-01 --end 2024-12-31
    .venv\\Scripts\\python.exe source\\demo.py --priority build_soil
    .venv\\Scripts\\python.exe source\\demo.py --lat 51.45 --lon -2.58 --current wheat barley
    .venv\\Scripts\\python.exe source\\demo.py --previous corn                 (what should follow corn?)
    .venv\\Scripts\\python.exe source\\demo.py --must-grow rice soybean        (build a rotation around these)
    .venv\\Scripts\\python.exe source\\demo.py --price corn=180 --yield corn=12.5 --cost corn=900   (your own figures, USD)
    .venv\\Scripts\\python.exe source\\demo.py --json result.json             (also save the full result)

Everything goes through backend.recommend(); a graphical front end calls the same function.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from backend import PRIORITY_PRESETS, recommend
from data_pullers import TEST_FIELD


def _pair(text: str) -> tuple[str, float]:
    """'corn=180' -> ('corn', 180.0)"""
    name, sep, number = text.partition("=")
    try:
        return name.strip().replace("_", " "), float(number)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected CROP=NUMBER, got {text!r}") from None


def main(argv=None) -> int:
    last_year = date.today().year - 1
    p = argparse.ArgumentParser(description="Field Shift: crop rotation options for a location")
    p.add_argument("--lat", type=float, default=TEST_FIELD.lat, help="latitude (default: Iowa test field)")
    p.add_argument("--lon", type=float, default=TEST_FIELD.lon, help="longitude")
    p.add_argument("--start", default=f"{last_year - 9}-01-01", help="first day of data, YYYY-MM-DD")
    p.add_argument("--end", default=f"{last_year}-12-31", help="last day of data, YYYY-MM-DD")
    p.add_argument("--priority", default="balanced", choices=sorted(PRIORITY_PRESETS),
                   help="what matters most to the farmer")
    p.add_argument("--current", nargs="*", default=None,
                   help="current rotation, e.g. --current corn soybean (default: from CropScape)")
    p.add_argument("--previous", default=None,
                   help="crop grown last, e.g. --previous corn (default: latest CropScape year, "
                        "else the last crop of --current)")
    p.add_argument("--must-grow", nargs="+", default=None, metavar="CROP",
                   help="one or two crops every rotation must contain, e.g. --must-grow rice")
    p.add_argument("--price", nargs="+", default=[], metavar="CROP=USD_PER_TONNE", type=_pair,
                   help="your own crop prices, e.g. --price corn=180 soybean=420")
    p.add_argument("--yield", dest="yields", nargs="+", default=[], metavar="CROP=TONNES_PER_HECTARE",
                   type=_pair, help="your own yields, e.g. --yield corn=12.5")
    p.add_argument("--cost", nargs="+", default=[], metavar="CROP=USD_PER_HECTARE", type=_pair,
                   help="your costs per hectare, e.g. --cost corn=900")
    p.add_argument("--country", default=None,
                   help="country for FAOSTAT prices and yields (default: found from lat/lon)")
    p.add_argument("--years", type=int, default=3, help="length of suggested rotations (1-4)")
    p.add_argument("--irrigated", action="store_true", help="field is irrigated (ignore rainfall)")
    p.add_argument("--smap", action="store_true",
                   help="also use NASA SMAP soil moisture (needs EARTHDATA_USERNAME/PASSWORD)")
    p.add_argument("--json", default=None, help="save the full result as JSON to this file")
    args = p.parse_args(argv)
    farm_numbers: dict = {}
    for what, pairs in (("price", args.price), ("yield", args.yields), ("cost", args.cost)):
        for crop, number in pairs:
            farm_numbers.setdefault(crop, {})[what] = number

    try:
        rec = recommend(args.lat, args.lon, args.start, args.end, priorities=args.priority,
                        current_rotation=args.current, previous_crop=args.previous,
                        must_grow=args.must_grow, farm_numbers=farm_numbers or None,
                        country=args.country,
                        rotation_years=args.years,
                        irrigated=args.irrigated, use_smap=args.smap,
                        on_progress=lambda msg: print(f"[..] {msg}", file=sys.stderr))
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(rec.to_text())
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rec.to_dict(), fh, indent=2)
        print(f"\nSaved full result to {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
