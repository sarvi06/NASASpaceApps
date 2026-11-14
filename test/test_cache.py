"""Offline tests for data_pullers/_common.py: input checks and saving/re-using downloads."""

from datetime import date, timedelta

import pandas as pd
import pytest

from data_pullers import _common
from data_pullers._common import cached_csv, check_date_range, check_location, location_dir, to_date


def test_check_location():
    assert check_location("42.065", -93.73) == (42.065, -93.73)
    for lat, lon in [(91, 0), (-91, 0), (0, 181), (0, -181)]:
        with pytest.raises(ValueError, match="between"):
            check_location(lat, lon)
    with pytest.raises(ValueError, match="numbers"):
        check_location("north", 0)


def test_to_date_accepts_common_formats():
    for value in ("2020-03-01", "20200301", date(2020, 3, 1), pd.Timestamp("2020-03-01")):
        assert to_date(value) == date(2020, 3, 1)
    with pytest.raises(ValueError, match="2015-01-31"):
        to_date("01/03/2020")


def test_check_date_range():
    assert check_date_range("2020-01-01", "2020-12-31", date(1981, 1, 1), "X") == (
        date(2020, 1, 1), date(2020, 12, 31))
    with pytest.raises(ValueError, match="after"):
        check_date_range("2021-01-01", "2020-01-01", date(1981, 1, 1), "X")
    with pytest.raises(ValueError, match="starts on 1981"):
        check_date_range("1970-01-01", "1971-01-01", date(1981, 1, 1), "X")
    with pytest.raises(ValueError, match="future"):
        check_date_range("2020-01-01", date.today() + timedelta(days=2), date(1981, 1, 1), "X")


def test_location_dir_uses_three_decimals(tmp_data_dir):
    assert location_dir(42.0651, -93.73) == tmp_data_dir / "42.065_-93.730"


def test_cached_csv_downloads_once_then_reads_disk(tmp_path):
    calls = []

    def download():
        calls.append(1)
        df = pd.DataFrame({"x": [1.5, 2.5]},
                          index=pd.date_range("2020-01-01", periods=2, name="date"))
        df.attrs["elevation_m"] = 310.2
        return df

    path = tmp_path / "data.csv"
    first = cached_csv(path, download, index=True)
    second = cached_csv(path, download, index=True)
    assert len(calls) == 1
    pd.testing.assert_frame_equal(first, second, check_freq=False)
    assert second.attrs["elevation_m"] == 310.2            # attrs survive via the .json file
    assert isinstance(second.index, pd.DatetimeIndex)

    cached_csv(path, download, refresh=True, index=True)
    assert len(calls) == 2                                  # refresh downloads again


def test_cached_csv_save_if_and_empty_tables(tmp_path):
    path = tmp_path / "bad.csv"
    cached_csv(path, lambda: pd.DataFrame({"a": [1]}), save_if=lambda df: False)
    assert not path.exists()                                # rejected results aren't saved

    empty = tmp_path / "empty.csv"
    cached_csv(empty, pd.DataFrame)
    assert cached_csv(empty, lambda: pytest.fail("should read from disk")).empty
