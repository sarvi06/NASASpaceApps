"""FAO EcoCrop: growing requirements for ~2,500 crops (one global table).

Call:    get_crop_requirements(refresh=False)
Inputs:  refresh       True to download again instead of using the saved copy
Output:  DataFrame, one row per crop (raw EcoCrop columns, see below).
Saved:   databases/ecocrop/ecocrop.parquet

Source: https://digital-atlas.s3.amazonaws.com/cdh/data/ecocrop/ecocrop.parquet (no login).

Key columns (decision/crops.py turns these into a clean Crop list):
  scientificname, comname, famname   names and botanical family
  topmn, topmx / tmin, tmax          optimal / absolute temperature during growth (degC)
  ropmn, ropmx / rmin, rmax          optimal / absolute annual rainfall (mm)
  phopmn, phopmx / phmin, phmax      optimal / absolute soil pH
  ktmp / ktmpr                       killing temperature during growth / during rest (degC)
  gmin, gmax                         crop cycle length (days)
  text, dra, dep, sal, fer           optimal soil texture, drainage, depth, salinity, fertility
  textr, drar, depr, salr, ferr      the same, absolute (tolerated) range
"""

import os

import pandas as pd
import requests

from ._common import DATA_DIR, TIMEOUT

URL = "https://digital-atlas.s3.amazonaws.com/cdh/data/ecocrop/ecocrop.parquet"
CACHE_PATH = DATA_DIR / "ecocrop" / "ecocrop.parquet"


def get_crop_requirements(refresh: bool = False) -> pd.DataFrame:
    """The raw EcoCrop table, downloading it first if it isn't saved yet."""
    if refresh or not CACHE_PATH.exists():
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        resp = requests.get(URL, timeout=TIMEOUT)
        resp.raise_for_status()
        tmp = CACHE_PATH.with_name(CACHE_PATH.name + ".part")
        tmp.write_bytes(resp.content)
        pd.read_parquet(tmp)          # raises if the download is truncated/corrupt
        os.replace(tmp, CACHE_PATH)   # only then replace the saved copy
    return pd.read_parquet(CACHE_PATH)
