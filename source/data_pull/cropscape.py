"""USDA Cropland Data Layer (via CropScape): what was grown at a point, year by year.

API docs: https://nassgeodata.gmu.edu/CropScape/devhelp/help.html
No login required. The CDL is a 30 m raster, so a point query returns the
crop of the single 30 m pixel containing that point.
"""

import re

import pandas as pd
import requests
from pyproj import Transformer

from .config import TIMEOUT

URL = "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLValue"

# The CDL service expects coordinates in USA Contiguous Albers Equal Area (EPSG:5070),
# not latitude/longitude, so we convert first.
_to_albers = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)

_RESULT = re.compile(r'value:\s*(\d+),\s*category:\s*"([^"]*)"')


def fetch_crop_for_year(lat: float, lon: float, year: int) -> tuple[int, str]:
    """Return (cdl_code, crop_name) for one year."""
    x, y = _to_albers.transform(lon, lat)
    resp = requests.get(URL, params={"year": year, "x": x, "y": y}, timeout=TIMEOUT)
    resp.raise_for_status()
    match = _RESULT.search(resp.text)
    if not match:
        raise ValueError(f"Unexpected CropScape response for {year}: {resp.text[:200]}")
    return int(match.group(1)), match.group(2)


def fetch_crop_history(lat: float, lon: float, years: range, attempts: int = 3) -> pd.DataFrame:
    """Return one row per year. Years the service can't answer are kept with an error note.

    The CropScape server is occasionally slow, so each year is retried a few times.
    """
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
    return pd.DataFrame(rows)
