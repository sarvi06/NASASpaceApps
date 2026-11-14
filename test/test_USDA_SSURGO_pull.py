"""Tests for data_pullers/USDA_SSURGO_pull.py."""

import pytest

from conftest import nicollet_soil
from data_pullers import TEST_FIELD
from data_pullers import USDA_SSURGO_pull as ssurgo


def test_get_soil_saves_and_reuses(tmp_data_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(ssurgo, "fetch_soil_at_point",
                        lambda lat, lon: calls.append(1) or nicollet_soil())
    a = ssurgo.get_soil(42.065, -93.73)
    b = ssurgo.get_soil(42.065, -93.73)
    assert len(calls) == 1
    assert list(b["compname"]) == ["Nicollet", "Clarion"]
    assert b["ph1to1h2o_r"].iloc[0] == 6.2


@pytest.mark.live
def test_live_ssurgo_returns_topsoil_properties(tmp_data_dir):
    df = ssurgo.get_soil(TEST_FIELD.lat, TEST_FIELD.lon)
    assert not df.empty
    assert df["comppct_r"].max() > 0
    assert df["om_r"].notna().any()


@pytest.mark.live
def test_live_ssurgo_outside_us_is_empty(tmp_data_dir):
    assert ssurgo.get_soil(51.45, -2.58).empty
