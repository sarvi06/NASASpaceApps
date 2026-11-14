"""Smoke tests: each puller reaches its API and returns sensible data for the test field.

These hit the live APIs, so they need internet access. Run from the repo root:
    .venv\\Scripts\\python.exe -m pytest
"""

from data_pull.config import TEST_FIELD
from data_pull.cropscape import fetch_crop_history
from data_pull.power import PARAMETERS, fetch_power_daily
from data_pull.soils import fetch_soil_at_point

LAT, LON = TEST_FIELD.lat, TEST_FIELD.lon


def test_power_returns_one_row_per_day():
    df = fetch_power_daily(LAT, LON, "20230101", "20230131")
    assert len(df) == 31
    assert set(PARAMETERS) <= set(df.columns)
    # Iowa in January: mean temperature should be cold but physically plausible.
    assert -35 < df["T2M"].mean() < 10


def test_cropscape_shows_corn_soy_rotation():
    df = fetch_crop_history(LAT, LON, range(2021, 2024))
    assert df["error"].isna().all(), df["error"].tolist()
    assert set(df["crop"]) == {"Corn", "Soybeans"}


def test_ssurgo_returns_topsoil_properties():
    df = fetch_soil_at_point(LAT, LON)
    assert not df.empty
    assert df["comppct_r"].max() > 0
    assert df["om_r"].notna().any()  # at least one component has organic matter data
