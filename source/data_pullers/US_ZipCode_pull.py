"""US zip codes: where a zip code is, so a farmer can type one instead of coordinates.

Call:    get_zip_location(zip_code, refresh=False)
Inputs:  zip_code      a US zip code, "50010" or "50010-1234" (only the first five digits count)
         refresh       True to look it up again instead of using the saved copy
Output:  {"zip": "50010", "place": "Ames", "state": "Iowa", "state_code": "IA",
          "lat": 42.0379, "lon": -93.6003}
Saved:   databases/zip/<zip>.csv

Source: Zippopotam.us, https://api.zippopotam.us/us/<zip> (free, no login).
Limit: the point is the centre of the whole zip area, often its town, not a field. Soil and
crop history are looked up at a single point, so a farmer who knows their field's own latitude
and longitude should use those instead.
"""

import re

import pandas as pd
import requests

from . import _common
from ._common import TIMEOUT, cached_csv

URL = "https://api.zippopotam.us/us/{zip}"
_ZIP = re.compile(r"^(\d{5})(-\d{4})?$")


def check_zip(zip_code) -> str:
    """The five-digit zip code as text, or ValueError with a plain message."""
    match = _ZIP.match(str(zip_code).strip())
    if not match:
        raise ValueError(f"A US zip code is five digits, e.g. 50010; got {zip_code!r}.")
    return match.group(1)


def get_zip_location(zip_code, refresh: bool = False) -> dict:
    """The place name, state and centre point of a US zip code."""
    code = check_zip(zip_code)
    path = _common.DATA_DIR / "zip" / f"{code}.csv"
    row = cached_csv(path, lambda: pd.DataFrame([fetch_zip_location(code)]), refresh).iloc[0]
    return {"zip": code, "place": str(row["place"]), "state": str(row["state"]),
            "state_code": str(row["state_code"]), "lat": float(row["lat"]), "lon": float(row["lon"])}


def fetch_zip_location(code: str) -> dict:
    """Look one zip code up (no saving)."""
    resp = requests.get(URL.format(zip=code), timeout=TIMEOUT)
    if resp.status_code == 404:
        raise ValueError(f"There is no US zip code {code}.")
    resp.raise_for_status()
    places = resp.json().get("places") or []
    if not places:
        raise ValueError(f"There is no US zip code {code}.")
    place = places[0]
    return {"zip": code, "place": place["place name"], "state": place["state"],
            "state_code": place["state abbreviation"],
            "lat": float(place["latitude"]), "lon": float(place["longitude"])}


def describe(location: dict) -> str:
    """'Ames, Iowa (zip 50010)'"""
    return f"{location['place']}, {location['state']} (zip {location['zip']})"
