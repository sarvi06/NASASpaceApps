"""Tests for decision/water.py: FAO-56 reference evapotranspiration and the rain share."""

import pytest

from conftest import IOWA_ET0, IOWA_PRECIP, fake_power_daily
from decision.water import rain_share, reference_et_daily, reference_et_monthly


def test_daily_et0_is_in_the_usual_range_for_an_iowa_summer_and_winter_day():
    july = float(reference_et_daily(tmean=24, tmax=30, tmin=18, rh=70, wind=3, radiation=22,
                                    lat=42, day_of_year=196, elevation_m=310))
    january = float(reference_et_daily(tmean=-6, tmax=-1, tmin=-11, rh=70, wind=3, radiation=7,
                                       lat=42, day_of_year=15, elevation_m=310))
    assert 4 <= july <= 7
    assert 0 <= january <= 1.5


def test_daily_et0_never_goes_below_zero():
    assert float(reference_et_daily(-20, -15, -25, 100, 0, 0, 42, 355)) >= 0


def test_monthly_et0_from_power_data():
    et0 = reference_et_monthly(fake_power_daily(), 42.065, 310)
    assert len(et0) == 12 and all(v >= 0 for v in et0)
    assert min(et0[5:8]) > max(et0[0], et0[1], et0[11])        # Jun-Aug above Dec-Feb


def test_monthly_et0_needs_humidity_sunlight_and_wind():
    for column in ("RH2M", "WS2M", "ALLSKY_SFC_SW_DWN"):
        assert reference_et_monthly(fake_power_daily().drop(columns=column), 42.065, 310) is None
    blank = fake_power_daily()
    blank["RH2M"] = float("nan")
    assert reference_et_monthly(blank, 42.065, 310) is None


def test_rain_share_falls_with_less_rain_and_caps_at_one():
    full = rain_share(4, 5, IOWA_ET0, IOWA_PRECIP)
    assert 0 < rain_share(4, 5, IOWA_ET0, IOWA_PRECIP, rain_scale=0.7) < full < 1
    assert rain_share(4, 5, IOWA_ET0, [500] * 12) == 1.0
    assert rain_share(0, 3, [0] * 12, IOWA_PRECIP) == 1.0           # no demand at all


def test_a_crop_growing_through_the_cool_months_scores_above_a_summer_crop():
    summer = rain_share(4, 5, IOWA_ET0, IOWA_PRECIP)                 # May-Sep, e.g. corn
    winter = rain_share(8, 9, IOWA_ET0, IOWA_PRECIP)                 # Sep-May, e.g. winter wheat
    assert winter > summer
