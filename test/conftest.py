"""Shared test data: an Iowa-like field (climate, soil, crop history) that needs no internet.

Tests that hit real web services are marked @pytest.mark.live:
    .venv\\Scripts\\python.exe -m pytest -m "not live"     fast, offline
    .venv\\Scripts\\python.exe -m pytest -m live           real APIs (a few minutes)
Tests using the EcoCrop table download it once (~1 MB) and then use the saved copy.
"""

import numpy as np
import pandas as pd
import pytest

from data_pullers import _common
from data_pullers.FAO_EcoCrop_pull import get_crop_requirements
from decision.crops import build_crops
from decision.economics import SOLD_CROPS, build_economy
from decision.suitability import Climate

# Monthly values from 10 years of NASA POWER at the Iowa test field (2015-2024).
IOWA_TMEAN = [-6.3, -4.2, 3.2, 9.3, 16.5, 22.8, 24.4, 23.3, 20.0, 11.2, 3.4, -2.4]
IOWA_TMIN_EXT = [-23.8, -19.7, -11.5, -4.8, 2.4, 9.9, 13.2, 11.9, 6.4, -3.2, -9.5, -16.6]
IOWA_PRECIP = [32, 25, 52, 63, 113, 111, 88, 100, 85, 72, 40, 42]
# Rough typical reference evapotranspiration (ET0, mm per month) for central Iowa.
IOWA_ET0 = [15, 25, 50, 90, 125, 150, 160, 135, 95, 60, 25, 15]


@pytest.fixture
def iowa_climate():
    return Climate(list(IOWA_TMEAN), list(IOWA_TMIN_EXT), list(IOWA_PRECIP))


@pytest.fixture
def iowa_site():
    """Nicollet loam, as site_profile() returns it."""
    return {"lat": 42.065, "lon": -93.73, "alt_m": 310, "soil_component": "Nicollet",
            "soil_component_pct": 85, "ph": 6.2, "text": "medium", "text_raw": "loam",
            "dra": "well (dry spells)", "dra_raw": "Somewhat poorly drained",
            "dep": "deep (>>150 cm)", "dep_raw_cm": 200, "sal": "low (<4 dS/m)",
            "sal_raw_dsm": 0, "fer": "high", "fer_raw_om_pct": 6.0, "slope_pct": 2,
            "erodibility_k": 0.28, "hydrologic_group": "B/D", "water_capacity": 0.21}


def fake_faostat() -> pd.DataFrame:
    """A few rows shaped like get_crop_economics() output (US-like numbers).
    Lentils have no local price; okra is not grown locally (world figures only)."""
    #        item             yield  price  world yield  world price  area (ha)
    rows = [("Maize (corn)", 11.0, 200, 10.0, 220, 33_000_000), ("Soya beans", 3.4, 450, 2.8, 480, 34_000_000),
            ("Wheat", 3.3, 250, 3.0, 260, 15_000_000), ("Oats", 2.4, 230, 2.2, 240, 400_000),
            ("Rye", 2.2, 210, 2.5, 220, 150_000), ("Barley", 4.0, 220, 3.1, 240, 1_000_000),
            ("Sunflower seed", 2.0, 500, 1.8, 520, 500_000), ("Beans, dry", 2.2, 800, 1.2, 1200, 500_000),
            ("Potatoes", 50.0, 220, 20.0, 300, 380_000), ("Tomatoes", 100.0, 120, 40.0, 500, 110_000),
            ("Rice", 8.5, 330, 4.5, 400, 1_100_000), ("Sugar beet", 70.0, 50, 55.0, 55, 450_000),
            ("Lentils, dry", 1.4, None, 1.1, 900, 250_000), ("Okra", None, None, 8.0, 700, None)]
    df = pd.DataFrame(rows, columns=["item", "yield_t_ha", "price_usd_t", "world_yield_t_ha",
                                     "world_price_usd_t", "area_ha"])
    df["price_low_usd_t"], df["price_high_usd_t"] = df["price_usd_t"] * 0.8, df["price_usd_t"] * 1.25
    df["yield_years"] = df["price_years"] = "2020-2024"
    return df


@pytest.fixture(scope="session")
def crops():
    """Every rotation crop in EcoCrop."""
    return build_crops(get_crop_requirements(), SOLD_CROPS)


@pytest.fixture(scope="session")
def economy(crops):
    """The crops priced with the fake FAOSTAT table."""
    return build_economy(fake_faostat(), crops, "Testland")


def fake_power_daily(first_year=2015, last_year=2024, rain_scale=1.0) -> pd.DataFrame:
    """Daily table shaped like NASA POWER, built from the Iowa monthly values."""
    days = pd.date_range(f"{first_year}-01-01", f"{last_year}-12-31", freq="D", name="date")
    m = days.month - 1
    rng = np.random.default_rng(0)
    tmean = np.array(IOWA_TMEAN)[m] + rng.normal(0, 1.0, len(days))
    # daily minimum ~8 degC below mean; one cold night per month reaching the typical extreme
    tmin = tmean - 8
    first_of_month = days.day == 15
    tmin[first_of_month] = np.array(IOWA_TMIN_EXT)[m[first_of_month]]
    rain = np.array(IOWA_PRECIP)[m] / days.days_in_month * rain_scale
    df = pd.DataFrame({"T2M": tmean, "T2M_MAX": tmean + 6, "T2M_MIN": tmin,
                       "PRECTOTCORR": rain, "RH2M": 70.0, "ALLSKY_SFC_SW_DWN": 15.0,
                       "WS2M": 3.0, "GWETTOP": 0.5, "GWETROOT": 0.5}, index=days)
    df.attrs["elevation_m"] = 310.0
    return df


def nicollet_soil() -> pd.DataFrame:
    return pd.DataFrame([
        {"mukey": "2834849", "muname": "Nicollet loam", "compname": "Nicollet", "comppct_r": 85,
         "majcompflag": "Yes", "slope_r": 2, "drainagecl": "Somewhat poorly drained",
         "hydgrp": "B/D", "hzdepb_r": 20, "om_r": 6.0, "sandtotal_r": 31, "silttotal_r": 43,
         "claytotal_r": 26, "awc_r": 0.21, "kwfact": 0.28, "ph1to1h2o_r": 6.2, "ec_r": 0,
         "soil_depth_cm": 200, "restriction_depth_cm": np.nan},
        {"mukey": "2834849", "muname": "Nicollet loam", "compname": "Clarion", "comppct_r": 10,
         "majcompflag": "No", "slope_r": 3, "drainagecl": "Well drained", "hydgrp": "B",
         "hzdepb_r": 23, "om_r": 3.5, "sandtotal_r": 45, "silttotal_r": 34, "claytotal_r": 21,
         "awc_r": 0.21, "kwfact": 0.24, "ph1to1h2o_r": 6.2, "ec_r": 0, "soil_depth_cm": 200,
         "restriction_depth_cm": np.nan},
    ])


def corn_soy_history(first_year=2015, last_year=2024) -> pd.DataFrame:
    rows = [{"year": y, "cdl_code": 1 if y % 2 else 5, "crop": "Corn" if y % 2 else "Soybeans",
             "error": None} for y in range(first_year, last_year + 1)]
    return pd.DataFrame(rows)


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Point every puller's save folder at a temporary directory."""
    monkeypatch.setattr(_common, "DATA_DIR", tmp_path)
    return tmp_path
