"""Tests for data_pullers/NASA_POWER_pull.py."""

import pandas as pd
import pytest

from conftest import fake_power_daily
from data_pullers import NASA_POWER_pull as power
from data_pullers import TEST_FIELD


def test_get_climate_saves_and_reuses(tmp_data_dir, monkeypatch):
    calls = []

    def fake_fetch(lat, lon, start, end):
        calls.append((start, end))
        return fake_power_daily(2020, 2020)

    monkeypatch.setattr(power, "fetch_power_daily", fake_fetch)
    a = power.get_climate(42.065, -93.73, "2020-01-01", "2020-12-31")
    b = power.get_climate(42.065, -93.73, "2020-01-01", "2020-12-31")
    assert calls == [("20200101", "20201231")]               # downloaded once
    assert (tmp_data_dir / "42.065_-93.730" / "NASA_POWER_20200101_20201231.csv").exists()
    assert b.attrs["elevation_m"] == 310.0
    assert len(a) == len(b) == 366


def test_get_climate_rejects_bad_inputs(tmp_data_dir):
    with pytest.raises(ValueError, match="1981"):
        power.get_climate(42, -93, "1970-01-01", "1971-01-01")
    with pytest.raises(ValueError, match="Latitude"):
        power.get_climate(420, -93, "2020-01-01", "2020-12-31")


@pytest.mark.live
def test_live_power_returns_one_row_per_day(tmp_data_dir):
    df = power.get_climate(TEST_FIELD.lat, TEST_FIELD.lon, "2023-01-01", "2023-01-31")
    assert len(df) == 31
    assert set(power.PARAMETERS) <= set(df.columns)
    assert -35 < df["T2M"].mean() < 10                       # Iowa in January
    assert df.attrs["elevation_m"] > 0
