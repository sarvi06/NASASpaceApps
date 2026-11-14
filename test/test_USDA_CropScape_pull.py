"""Tests for data_pullers/USDA_CropScape_pull.py."""

import pandas as pd
import pytest

from data_pullers import TEST_FIELD
from data_pullers import USDA_CropScape_pull as cdl


def test_outside_contiguous_us_is_empty_without_network(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(cdl, "fetch_crop_history", lambda *a, **k: pytest.fail("no request expected"))
    df = cdl.get_crop_history(51.45, -2.58, 2015, 2020)       # Bristol, UK
    assert df.empty and list(df.columns) == cdl.COLUMNS


def test_year_checks(tmp_data_dir):
    with pytest.raises(ValueError, match="2008"):
        cdl.get_crop_history(42, -93, 2000, 2005)
    with pytest.raises(ValueError, match="after"):
        cdl.get_crop_history(42, -93, 2020, 2015)


def test_results_with_failed_years_are_not_saved(tmp_data_dir, monkeypatch):
    bad = pd.DataFrame([{"year": 2020, "cdl_code": None, "crop": None, "error": "timeout"}])
    monkeypatch.setattr(cdl, "fetch_crop_history", lambda *a, **k: bad)
    cdl.get_crop_history(42.065, -93.73, 2020, 2020)
    assert not (tmp_data_dir / "42.065_-93.730" / "USDA_CropScape_2020_2020.csv").exists()


@pytest.mark.live
def test_live_cropscape_shows_corn_soy_rotation(tmp_data_dir):
    df = cdl.get_crop_history(TEST_FIELD.lat, TEST_FIELD.lon, 2021, 2023)
    assert df["error"].isna().all(), df["error"].tolist()
    assert set(df["crop"]) == {"Corn", "Soybeans"}
