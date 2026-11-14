"""NASA POWER: daily agro-climate time series for a single point.

API docs: https://power.larc.nasa.gov/docs/services/api/temporal/daily/
No login or API key required.
"""

import pandas as pd
import requests

from .config import TIMEOUT

URL = "https://power.larc.nasa.gov/api/temporal/daily/point"

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


def fetch_power_daily(lat: float, lon: float, start: str, end: str) -> pd.DataFrame:
    """Return one row per day between start and end (YYYYMMDD, inclusive).

    The point's elevation (metres, from POWER's terrain model) is kept in
    df.attrs["elevation_m"].
    """
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
