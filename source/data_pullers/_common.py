"""Shared settings and helpers used by every data puller.

  - TEST_FIELD, DATA_DIR, TIMEOUT      settings
  - check_location / to_date / check_date_range   input checks with clear error messages
  - location_dir                       where a location's downloads are saved
  - cached_csv                         "download the first time, read the saved copy after"
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import pandas as pd


@dataclass(frozen=True)
class Field:
    name: str
    lat: float
    lon: float


# Test field: a corn/soybean field in Story County, Iowa, ~7 km north-west of Ames.
# CropScape shows a clean corn <-> soybean alternation here, so it is a good baseline.
TEST_FIELD = Field(name="story_county_ia", lat=42.065, lon=-93.73)

# Where downloads are saved. Contents are gitignored and re-created automatically.
DATA_DIR = Path(__file__).resolve().parents[1] / "databases"

# Network timeout for every web request, in seconds.
TIMEOUT = 60


# --------------------------------------------------------------------------------------
# Input checks
# --------------------------------------------------------------------------------------
def check_location(lat, lon) -> tuple[float, float]:
    """Return (lat, lon) as floats, or raise ValueError with a plain message."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise ValueError(f"Latitude and longitude must be numbers, got {lat!r}, {lon!r}.") from None
    if not -90 <= lat <= 90:
        raise ValueError(f"Latitude must be between -90 and 90, got {lat}.")
    if not -180 <= lon <= 180:
        raise ValueError(f"Longitude must be between -180 and 180, got {lon}.")
    return lat, lon


def to_date(value, name: str = "date") -> date:
    """Accept 'YYYY-MM-DD', 'YYYYMMDD', a date/datetime or a pandas Timestamp."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"{name} must look like 2015-01-31, got {value!r}.")


def check_date_range(start, end, earliest: date, dataset: str) -> tuple[date, date]:
    """Return (start, end) as dates; start <= end, not before `earliest`, not in the future."""
    start, end = to_date(start, "start_date"), to_date(end, "end_date")
    if start > end:
        raise ValueError(f"start_date ({start}) is after end_date ({end}).")
    if end > date.today():
        raise ValueError(f"end_date ({end}) is in the future.")
    if start < earliest:
        raise ValueError(f"{dataset} data starts on {earliest}; start_date {start} is too early.")
    return start, end


# --------------------------------------------------------------------------------------
# Saving / re-using downloads
# --------------------------------------------------------------------------------------
def location_dir(lat: float, lon: float) -> Path:
    """Folder for one location's downloads, e.g. databases/42.065_-93.730/."""
    return DATA_DIR / f"{lat:.3f}_{lon:.3f}"


def cached_csv(path: Path, download: Callable[[], pd.DataFrame], refresh: bool = False,
               index: bool = False, save_if: Callable[[pd.DataFrame], bool] | None = None
               ) -> pd.DataFrame:
    """Return the table saved at `path`, or call `download()` and save its result there.

    index    True for date-indexed tables (saved and re-read with the dates as the index).
    save_if  optional check; the result is only saved when it returns True
             (e.g. don't keep a CropScape result that has failed years).
    df.attrs (e.g. elevation) are kept in a small .json file next to the CSV.
    """
    meta_path = path.with_suffix(".json")
    if not refresh and path.exists():
        try:
            df = pd.read_csv(path, index_col=0 if index else None, parse_dates=index)
        except pd.errors.EmptyDataError:
            df = pd.DataFrame()
        if meta_path.exists():
            df.attrs.update(json.loads(meta_path.read_text()))
        return df

    df = download()
    if save_if is None or save_if(df):
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=index)
        if df.attrs:
            meta_path.write_text(json.dumps(df.attrs, default=str))
    return df
