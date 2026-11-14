"""NASA POWER: daily agro-climate data for one point.

Call:    get_climate(lat, lon, start_date, end_date, refresh=False)
Inputs:  lat, lon      decimal degrees (worldwide)
         start_date    first day, "YYYY-MM-DD" (1981-01-01 or later)
         end_date      last day, "YYYY-MM-DD" (not in the future)
         refresh       True to download again instead of using the saved copy
Output:  DataFrame, one row per day (index "date"), columns = PARAMETERS below.
         df.attrs["elevation_m"] = the point's elevation (m).
Saved:   databases/<lat>_<lon>/NASA_POWER_<start>_<end>.csv

API docs: https://power.larc.nasa.gov/docs/services/api/temporal/daily/
No login needed. POWER is a ~0.5 degree grid, so it describes the area around a field,
not the field itself. The last few days before today may still be blank.
"""

from datetime import date

import pandas as pd
import requests

from ._common import TIMEOUT, cached_csv, check_date_range, check_location, location_dir

URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
EARLIEST = date(1981, 1, 1)

# Parameter -> plain-English meaning (units).
PARAMETERS = {
    "T2M": "mean air temperature at 2 m (degC)",
    "T2M_MAX": "max air temperature at 2 m (degC)",
    "T2M_MIN": "min air temperature at 2 m (degC)  -> frost risk",
    "PRECTOTCORR": "precipitation, bias-corrected (mm/day)",
    "RH2M": "relative humidity at 2 m (%)",
    "ALLSKY_SFC_SW_DWN": "solar radiation reaching the surface (MJ/m^2/day)",
    "WS2M": "wind speed at 2 m (m/s)",
    "GWETTOP": "surface soil wetness, 0-5 cm (0 = dry, 1 = saturated)",
    "GWETROOT": "root-zone soil wetness, 0-100 cm (0 = dry, 1 = saturated)",
}

FILL_VALUE = -999.0  # POWER's marker for "no data"


def get_climate(lat: float, lon: float, start_date, end_date,
                refresh: bool = False) -> pd.DataFrame:
    """Daily NASA POWER climate between start_date and end_date (inclusive)."""
    lat, lon = check_location(lat, lon)
    start, end = check_date_range(start_date, end_date, EARLIEST, "NASA POWER")
    path = location_dir(lat, lon) / f"NASA_POWER_{start:%Y%m%d}_{end:%Y%m%d}.csv"
    return cached_csv(path, lambda: fetch_power_daily(lat, lon, f"{start:%Y%m%d}", f"{end:%Y%m%d}"),
                      refresh=refresh, index=True)


def fetch_power_daily(lat: float, lon: float, start: str, end: str) -> pd.DataFrame:
    """Download (no saving). start/end as YYYYMMDD strings."""
    params = {
        "parameters": ",".join(PARAMETERS),
        "community": "AG",
        "latitude": lat,
        "longitude": lon,
        "start": start,
        "end": end,
        "format": "JSON",
    }
    resp = requests.get(URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    body = resp.json()
    data = body["properties"]["parameter"]

    df = pd.DataFrame(data)  # columns = parameters, index = "YYYYMMDD"
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df.index.name = "date"
    df = df.replace(FILL_VALUE, float("nan"))
    df.attrs["elevation_m"] = body["geometry"]["coordinates"][2]  # [lon, lat, elevation]
    return df
