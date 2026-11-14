"""Tests for the SMAP puller.

Most tests run offline against a fake AppEEARS service. The final test hits the real
service and only runs if EARTHDATA_USERNAME / EARTHDATA_PASSWORD are set.
"""

import os
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from data_pull import smap
from data_pull.config import TEST_FIELD


class FakeResponse:
    def __init__(self, payload=None, content=b"", status_code=200):
        self._payload, self.content, self.status_code = payload, content, status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def make_fake_service(results_csv: str, products=None, layers=None, statuses=("pending", "done")):
    """Build a stand-in for the `requests` module that behaves like AppEEARS."""
    products = products or [
        {"Product": "SPL4SMGP", "Version": "007", "ProductAndVersion": "SPL4SMGP.007"},
        {"Product": "SPL4SMGP", "Version": "008", "ProductAndVersion": "SPL4SMGP.008"},
    ]
    layers = layers or {f"Geophysical_Data_{n}": {} for n in
                        ["sm_surface", "sm_rootzone", "sm_surface_wetness",
                         "sm_rootzone_wetness", "soil_temp_layer1"]}
    calls = SimpleNamespace(submitted=None, status_polls=0)

    def post(url, **kw):
        if url.endswith("/login"):
            return FakeResponse({"token": "tok"})
        calls.submitted = kw["json"]
        return FakeResponse({"task_id": "t1"})

    def get(url, **kw):
        if url.endswith("/product"):
            return FakeResponse(products)
        if "/product/" in url:
            return FakeResponse(layers)
        if url.endswith("/task/t1"):
            status = statuses[min(calls.status_polls, len(statuses) - 1)]
            calls.status_polls += 1
            return FakeResponse({"status": status})
        if url.endswith("/bundle/t1"):
            return FakeResponse({"files": [{"file_id": "f0", "file_name": "readme.txt"},
                                           {"file_id": "f1", "file_name": "x-SPL4SMGP-008-results.csv"}]})
        if url.endswith("/bundle/t1/f1"):
            return FakeResponse(content=results_csv.encode())
        raise AssertionError(f"unexpected URL {url}")

    return SimpleNamespace(post=post, get=get), calls


CSV = (
    "ID,Category,Latitude,Longitude,Date,"
    "SPL4SMGP_008_Geophysical_Data_sm_surface,SPL4SMGP_008_Geophysical_Data_sm_rootzone,"
    "SPL4SMGP_008_Geophysical_Data_sm_surface_wetness,SPL4SMGP_008_Geophysical_Data_sm_rootzone_wetness,"
    "SPL4SMGP_008_Geophysical_Data_soil_temp_layer1\n"
    # two 3-hourly steps on Jan 1 (should average), nothing on Jan 2, a fill value on Jan 3
    "field,field,42.065,-93.73,2023-01-01T01:30:00,0.30,0.40,0.5,0.6,273.15\n"
    "field,field,42.065,-93.73,2023-01-01T04:30:00,0.32,0.42,0.52,0.62,275.15\n"
    "field,field,42.065,-93.73,2023-01-03T01:30:00,-9999,0.44,0.5,0.6,274.15\n"
)


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("EARTHDATA_USERNAME", "u")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "p")
    monkeypatch.setattr(smap.time, "sleep", lambda s: None)


def test_daily_table_shape_units_and_gaps(credentials, monkeypatch):
    fake, calls = make_fake_service(CSV)
    monkeypatch.setattr(smap, "requests", fake)

    df = smap.fetch_smap_daily(42.065, -93.73, "20230101", "20230103", poll_seconds=0)

    assert list(df.index) == list(pd.date_range("2023-01-01", "2023-01-03"))  # one row per day
    assert set(smap.PRODUCT_LAYERS["SPL4SMGP"]) == set(df.columns)
    assert df.loc["2023-01-01", "SM_SURFACE"] == pytest.approx(0.31)         # 3-hourly -> daily mean
    assert df.loc["2023-01-01", "SOIL_TEMP_LAYER1"] == pytest.approx(1.0)    # 274.15 K -> 1.0 degC
    assert np.isnan(df.loc["2023-01-02"]).all()                              # no overpass data
    assert np.isnan(df.loc["2023-01-03", "SM_SURFACE"])                      # -9999 fill -> NaN
    assert df.attrs["product"] == "SPL4SMGP.008"                             # picked newest version


def test_request_uses_latest_version_and_appeears_date_format(credentials, monkeypatch):
    fake, calls = make_fake_service(CSV)
    monkeypatch.setattr(smap, "requests", fake)
    smap.fetch_smap_daily(42.065, -93.73, "20230101", "20230103", poll_seconds=0)

    params = calls.submitted["params"]
    assert calls.submitted["task_type"] == "point"
    assert params["dates"] == [{"startDate": "01-01-2023", "endDate": "01-03-2023"}]
    assert {l["product"] for l in params["layers"]} == {"SPL4SMGP.008"}
    assert params["coordinates"][0]["latitude"] == 42.065
    assert calls.status_polls == 2  # waited through "pending" before "done"


def test_missing_layer_warns_but_continues(credentials, monkeypatch):
    layers = {f"Geophysical_Data_{n}": {} for n in ["sm_surface", "sm_rootzone"]}
    fake, _ = make_fake_service(CSV, layers=layers)
    monkeypatch.setattr(smap, "requests", fake)
    with pytest.warns(UserWarning, match="skipping"):
        df = smap.fetch_smap_daily(42.065, -93.73, "20230101", "20230103", poll_seconds=0)
    assert set(df.columns) == {"SM_SURFACE", "SM_ROOTZONE"}


def test_failed_task_raises(credentials, monkeypatch):
    fake, _ = make_fake_service(CSV, statuses=("error",))
    monkeypatch.setattr(smap, "requests", fake)
    with pytest.raises(smap.SmapError, match="error"):
        smap.fetch_smap_daily(42.065, -93.73, "20230101", "20230103", poll_seconds=0)


def test_missing_credentials_gives_clear_error(monkeypatch):
    monkeypatch.delenv("EARTHDATA_USERNAME", raising=False)
    monkeypatch.delenv("EARTHDATA_PASSWORD", raising=False)
    with pytest.raises(smap.SmapError, match="Earthdata Login"):
        smap.fetch_smap_daily(42.065, -93.73, "20230101", "20230103")


def test_merge_with_power_keeps_every_power_day():
    days = pd.date_range("2023-01-01", periods=3, name="date")
    power = pd.DataFrame({"T2M": [1.0, 2.0, 3.0]}, index=days)
    power.attrs["elevation_m"] = 300
    sm = pd.DataFrame({"SM_ROOTZONE": [0.4, np.nan]}, index=days[:2])
    sm.attrs["product"] = "SPL4SMGP.008"

    merged = smap.merge_with_power(power, sm)

    assert len(merged) == 3
    assert list(merged.columns) == ["T2M", "SM_ROOTZONE"]
    assert np.isnan(merged["SM_ROOTZONE"].iloc[2])
    assert merged.attrs["elevation_m"] == 300 and merged.attrs["smap_product"] == "SPL4SMGP.008"


@pytest.mark.skipif(not (os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD")),
                    reason="needs Earthdata Login credentials")
def test_live_smap_returns_plausible_soil_moisture():
    """Hits the real AppEEARS service; can take several minutes."""
    df = smap.fetch_smap_daily(TEST_FIELD.lat, TEST_FIELD.lon, "20230601", "20230630")
    assert len(df) == 30
    assert df["SM_ROOTZONE"].notna().sum() > 20
    assert 0.05 < df["SM_ROOTZONE"].mean() < 0.6  # Iowa cropland in June, m^3/m^3
