"""FAO EcoCrop: growing requirements for ~2,500 crops.

Source: https://digital-atlas.s3.amazonaws.com/cdh/data/ecocrop/ecocrop.parquet
Downloaded once and cached locally. No login required.

Key columns (the field profile in source/matching/field_profile.py is built to match these):
  topmn, topmx / tmin, tmax    optimal / absolute temperature during the crop cycle (degC)
  ropmn, ropmx / rmin, rmax    optimal / absolute annual rainfall (mm)
  phopmn, phopmx / phmin, phmax  optimal / absolute soil pH
  latopmn, latopmx / latmn, latmx  optimal / absolute latitude
  altmx                        maximum altitude (m)
  ktmp / ktmpr                 killing temperature during growth / during rest (degC)
  gmin, gmax                   crop cycle length (days)
  text, dra, dep, sal, fer     optimal soil texture, drainage, depth, salinity, fertility
  textr, drar, depr, salr, ferr  the same, absolute (tolerated) range
"""

import pandas as pd
import requests

from .config import DATA_DIR, TIMEOUT

URL = "https://digital-atlas.s3.amazonaws.com/cdh/data/ecocrop/ecocrop.parquet"
CACHE_PATH = DATA_DIR / "ecocrop" / "ecocrop.parquet"


def load_ecocrop(refresh: bool = False) -> pd.DataFrame:
    """Return the EcoCrop table, downloading it first if it isn't cached yet."""
    if refresh or not CACHE_PATH.exists():
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        resp = requests.get(URL, timeout=TIMEOUT)
        resp.raise_for_status()
        CACHE_PATH.write_bytes(resp.content)
    return pd.read_parquet(CACHE_PATH)
