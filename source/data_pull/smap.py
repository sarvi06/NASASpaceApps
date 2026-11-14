"""NASA SMAP: daily soil-moisture time series for a single point.

Same shape as power.py (lat, lon, start, end -> DataFrame indexed by date), so the two
can be merged with merge_with_power() below.

How it works: SMAP's global files are far too big to download for a multi-year pull
(SPL4SMGP is 8 granules/day), so the point is extracted server-side by NASA's AppEEARS
service (https://appeears.earthdatacloud.nasa.gov/api/). Unlike POWER, this needs a free
NASA Earthdata Login account (https://urs.earthdata.nasa.gov/). Set two environment
variables before running:

    EARTHDATA_USERNAME, EARTHDATA_PASSWORD

AppEEARS runs jobs in a queue, so a pull takes from about a minute to some tens of
minutes. Product versions and layer names are looked up from the service at run time
(SMAP products get re-released, e.g. SPL4SMGP v7 -> v8 in 2025), so nothing is pinned.
"""

import io
import os
import re
import time
import warnings

import pandas as pd
import requests

from .config import TIMEOUT

URL = "https://appeears.earthdatacloud.nasa.gov/api"

# Product -> {our column name: AppEEARS layer name}.
PRODUCT_LAYERS = {
    # L4: SMAP radiometer data assimilated into a land model. Gap-free, 9 km, 3-hourly
    # (averaged to daily here). Best default for agronomy: it includes root-zone moisture.
    "SPL4SMGP": {
        "SM_SURFACE": "sm_surface",
        "SM_ROOTZONE": "sm_rootzone",
        "SM_SURFACE_WETNESS": "sm_surface_wetness",
        "SM_ROOTZONE_WETNESS": "sm_rootzone_wetness",
        "SOIL_TEMP_LAYER1": "soil_temp_layer1",
    },
    # L3 enhanced: actual satellite retrievals, 9 km, daily, with gaps (clouds-free but
    # frozen/snow/dense-vegetation/overpass gaps). Surface (top ~5 cm) only.
    "SPL3SMP_E": {
        "SM_AM": "Soil_Moisture_Retrieval_Data_AM_soil_moisture",
        "SM_PM": "Soil_Moisture_Retrieval_Data_PM_soil_moisture",
    },
}

# Column name -> plain-English meaning (units). Same idea as power.PARAMETERS.
PARAMETERS = {
    "SM_SURFACE": "surface soil moisture, 0-5 cm (m^3/m^3)",
    "SM_ROOTZONE": "root-zone soil moisture, 0-100 cm (m^3/m^3)  -> drought stress",
    "SM_SURFACE_WETNESS": "surface soil wetness, 0-5 cm (0 = dry, 1 = saturated)",
    "SM_ROOTZONE_WETNESS": "root-zone soil wetness, 0-100 cm (0 = dry, 1 = saturated)",
    "SOIL_TEMP_LAYER1": "soil temperature, top model layer (degC)",
    "SM_AM": "L3 observed surface soil moisture, 6 am pass (m^3/m^3)",
    "SM_PM": "L3 observed surface soil moisture, 6 pm pass (m^3/m^3)",
}
KELVIN_COLUMNS = {"SOIL_TEMP_LAYER1"}

FILL_VALUE = -9999.0  # SMAP's marker for "no data" (anything below -999 is treated as such)


class SmapError(RuntimeError):
    """Raised for login, job, or data problems with the SMAP pull."""


def _login() -> dict:
    user = os.environ.get("EARTHDATA_USERNAME")
    password = os.environ.get("EARTHDATA_PASSWORD")
    if not (user and password):
        raise SmapError(
            "SMAP needs a free NASA Earthdata Login. Create one at "
            "https://urs.earthdata.nasa.gov/ and set the EARTHDATA_USERNAME and "
            "EARTHDATA_PASSWORD environment variables."
        )
    resp = requests.post(f"{URL}/login", auth=(user, password), timeout=TIMEOUT)
    if resp.status_code == 401:
        raise SmapError("Earthdata Login rejected the username/password.")
    resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _version_key(version: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", version))


def _latest_product(short_name: str, headers: dict) -> str:
    """Return e.g. 'SPL4SMGP.008': the newest available version of a product."""
    resp = requests.get(f"{URL}/product", headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    candidates = [p for p in resp.json()
                  if p.get("Product") == short_name and not p.get("Deleted", False)]
    if not candidates:
        raise SmapError(f"AppEEARS does not list a product called {short_name}.")
    best = max(candidates, key=lambda p: _version_key(p["Version"]))
    return best["ProductAndVersion"]


def _resolve_layers(product_version: str, wanted: dict, headers: dict) -> dict:
    """Map our column names to the layer names AppEEARS actually uses (skips missing)."""
    resp = requests.get(f"{URL}/product/{product_version}", headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    available = list(resp.json())
    resolved = {}
    for column, raw in wanted.items():
        match = next((a for a in available if a == raw), None) or next(
            (a for a in available if a.lower().endswith(raw.lower())), None)
        if match:
            resolved[column] = match
        else:
            warnings.warn(f"{product_version} has no layer matching '{raw}'; skipping {column}.")
    if not resolved:
        raise SmapError(f"None of the expected layers exist in {product_version}. "
                        f"Available: {available[:20]}")
    return resolved


def _run_task(task: dict, headers: dict, poll_seconds: float, max_wait_seconds: float) -> pd.DataFrame:
    """Submit an AppEEARS task, wait for it, and return its results CSV."""
    resp = requests.post(f"{URL}/task", json=task, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    task_id = resp.json()["task_id"]

    waited = 0.0
    while True:
        resp = requests.get(f"{URL}/task/{task_id}", headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        status = resp.json().get("status", "")
        if status == "done":
            break
        if status in {"error", "failed", "deleted"}:
            raise SmapError(f"AppEEARS task {task_id} ended with status '{status}'.")
        if waited >= max_wait_seconds:
            raise SmapError(f"AppEEARS task {task_id} still '{status}' after "
                            f"{max_wait_seconds:.0f} s; check it later at "
                            "https://appeears.earthdatacloud.nasa.gov/explore")
        time.sleep(poll_seconds)
        waited += poll_seconds

    resp = requests.get(f"{URL}/bundle/{task_id}", headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    files = resp.json()["files"]
    results = next((f for f in files if f["file_name"].lower().endswith("results.csv")), None)
    if results is None:
        raise SmapError(f"AppEEARS task {task_id} produced no results CSV: "
                        f"{[f['file_name'] for f in files]}")
    resp = requests.get(f"{URL}/bundle/{task_id}/{results['file_id']}",
                        headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    return pd.read_csv(io.BytesIO(resp.content))


def _find_column(df: pd.DataFrame, product_version: str, layer: str) -> str:
    exact = f"{product_version.replace('.', '_')}_{layer}"
    if exact in df.columns:
        return exact
    match = next((c for c in df.columns if c.endswith(layer) and not c.endswith("_QA")), None)
    if match is None:
        raise SmapError(f"Layer {layer} not found in results. Columns: {list(df.columns)}")
    return match


def fetch_smap_daily(lat: float, lon: float, start: str, end: str,
                     product: str = "SPL4SMGP", poll_seconds: float = 20,
                     max_wait_seconds: float = 3600) -> pd.DataFrame:
    """Return one row per day between start and end (YYYYMMDD, inclusive).

    Same call shape as power.fetch_power_daily. Sub-daily values (L4 is 3-hourly) are
    averaged per UTC day; days with no data are NaN. The product version actually used
    (e.g. "SPL4SMGP.008") is kept in df.attrs["product"].
    """
    if product not in PRODUCT_LAYERS:
        raise ValueError(f"product must be one of {sorted(PRODUCT_LAYERS)}")
    start_ts = pd.to_datetime(start, format="%Y%m%d")
    end_ts = pd.to_datetime(end, format="%Y%m%d")

    headers = _login()
    product_version = _latest_product(product, headers)
    layers = _resolve_layers(product_version, PRODUCT_LAYERS[product], headers)

    task = {
        "task_type": "point",
        "task_name": f"fieldshift_{product}_{start}_{end}_{lat:.3f}_{lon:.3f}",
        "params": {
            "dates": [{"startDate": start_ts.strftime("%m-%d-%Y"),
                       "endDate": end_ts.strftime("%m-%d-%Y")}],
            "layers": [{"product": product_version, "layer": layer} for layer in layers.values()],
            "coordinates": [{"id": "field", "category": "field",
                             "latitude": lat, "longitude": lon}],
        },
    }
    raw = _run_task(task, headers, poll_seconds, max_wait_seconds)

    dates = pd.to_datetime(raw["Date"]).dt.tz_localize(None).dt.floor("D")
    out = pd.DataFrame({
        column: pd.to_numeric(raw[_find_column(raw, product_version, layer)], errors="coerce")
        for column, layer in layers.items()
    })
    out = out.where(out > -999)  # fill values -> NaN, before any unit conversion
    for column in KELVIN_COLUMNS & set(out.columns):
        out[column] = out[column] - 273.15
    out.index = dates
    out = out.groupby(level=0).mean()
    out = out.reindex(pd.date_range(start_ts, end_ts, freq="D"))
    out.index.name = "date"
    out.attrs["product"] = product_version
    return out


def merge_with_power(power: pd.DataFrame, smap: pd.DataFrame) -> pd.DataFrame:
    """Join POWER and SMAP daily tables on date (keeps every POWER day)."""
    merged = power.join(smap, how="left")
    merged.attrs.update(power.attrs)
    merged.attrs["smap_product"] = smap.attrs.get("product")
    return merged
