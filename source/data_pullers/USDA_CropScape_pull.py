"""USDA Cropland Data Layer (via CropScape): what was grown at a point, year by year.

Call:    get_crop_history(lat, lon, start_year=2008, end_year=None, refresh=False)
Inputs:  lat, lon      decimal degrees (contiguous US only)
         start_year    first year (2008 or later; the national map starts in 2008)
         end_year      last year (default: last year; this year's map isn't published yet)
         refresh       True to download again instead of using the saved copy
Output:  DataFrame, one row per year: year, cdl_code, crop, error
         ("error" is filled in for years the service couldn't answer).
         Outside the contiguous US: an empty table with those columns.
Saved:   databases/<lat>_<lon>/USDA_CropScape_<start>_<end>.csv (only if every year worked)

API docs: https://nassgeodata.gmu.edu/CropScape/devhelp/help.html
No login needed. The CDL is a 30 m map, so this is the crop on the 30 m square at the point.
"""

import re
from datetime import date

import pandas as pd
import requests
from pyproj import Transformer

from ._common import TIMEOUT, cached_csv, check_location, location_dir

URL = "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLValue"
FIRST_YEAR = 2008
COLUMNS = ["year", "cdl_code", "crop", "error"]

# Rough box around the contiguous US (the area the CDL covers).
_CONUS = {"lat": (24.0, 50.0), "lon": (-125.0, -66.0)}

# The CDL service expects coordinates in USA Contiguous Albers Equal Area (EPSG:5070),
# not latitude/longitude, so we convert first.
_to_albers = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)

_RESULT = re.compile(r'value:\s*(\d+),\s*category:\s*"([^"]*)"')


def in_contiguous_us(lat: float, lon: float) -> bool:
    return (_CONUS["lat"][0] <= lat <= _CONUS["lat"][1]
            and _CONUS["lon"][0] <= lon <= _CONUS["lon"][1])


def latest_year() -> int:
    return date.today().year - 1


def get_crop_history(lat: float, lon: float, start_year: int = FIRST_YEAR,
                     end_year: int | None = None, refresh: bool = False) -> pd.DataFrame:
    """One row per year with the crop CropScape shows at the point."""
    lat, lon = check_location(lat, lon)
    end_year = latest_year() if end_year is None else int(end_year)
    start_year = int(start_year)
    if start_year > end_year:
        raise ValueError(f"start_year ({start_year}) is after end_year ({end_year}).")
    if start_year < FIRST_YEAR or end_year > latest_year():
        raise ValueError(f"CropScape years must be between {FIRST_YEAR} and {latest_year()}, "
                         f"got {start_year}-{end_year}.")
    if not in_contiguous_us(lat, lon):
        return pd.DataFrame(columns=COLUMNS)
    path = location_dir(lat, lon) / f"USDA_CropScape_{start_year}_{end_year}.csv"
    return cached_csv(path, lambda: fetch_crop_history(lat, lon, range(start_year, end_year + 1)),
                      refresh=refresh, save_if=lambda df: df["error"].isna().all())


def fetch_crop_for_year(lat: float, lon: float, year: int) -> tuple[int, str]:
    """Download (no saving): (cdl_code, crop_name) for one year."""
    x, y = _to_albers.transform(lon, lat)
    resp = requests.get(URL, params={"year": year, "x": x, "y": y}, timeout=TIMEOUT)
    resp.raise_for_status()
    match = _RESULT.search(resp.text)
    if not match:
        raise ValueError(f"Unexpected CropScape response for {year}: {resp.text[:200]}")
    return int(match.group(1)), match.group(2)


def fetch_crop_history(lat: float, lon: float, years: range, attempts: int = 3) -> pd.DataFrame:
    """Download (no saving) one row per year. The server is sometimes slow, so each year
    is retried a few times; years that still fail are kept with an error note."""
    rows = []
    for year in years:
        for attempt in range(attempts):
            try:
                code, crop = fetch_crop_for_year(lat, lon, year)
                rows.append({"year": year, "cdl_code": code, "crop": crop, "error": None})
                break
            except (requests.RequestException, ValueError) as exc:
                if attempt == attempts - 1:
                    rows.append({"year": year, "cdl_code": None, "crop": None,
                                 "error": str(exc)[:200]})
    return pd.DataFrame(rows, columns=COLUMNS)
