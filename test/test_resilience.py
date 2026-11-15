"""Tests for decision/resilience.py: how a rotation holds up in each year's weather and in a
hotter, drier climate (offline, Iowa fixtures)."""

import json

import pandas as pd
import pytest

from conftest import fake_power_daily
from decision import resilience as RS
from decision import rotations as R
from decision.report import explain
from decision.suitability import Climate, score_cover

CORN, SOY = "Zea mays ssp. mays", "Glycine max"


@pytest.fixture
def corn_soy(crops, iowa_climate, iowa_site, economy):
    weights = R.resolve_priorities("balanced", iowa_site)
    return R.baseline_rotation([crops[CORN], crops[SOY]], iowa_climate, weights, iowa_site,
                               economy=economy)


def test_hotter_drier_shifts_all_three_series_and_leaves_the_input_alone(iowa_climate):
    before = Climate(list(iowa_climate.tmean), list(iowa_climate.tmin_ext), list(iowa_climate.precip))
    hot = RS.hotter_drier(iowa_climate)
    assert hot.tmean == pytest.approx([t + RS.WARMER_C for t in before.tmean])
    assert hot.tmin_ext == pytest.approx([t + RS.WARMER_C for t in before.tmin_ext])
    assert hot.precip == pytest.approx([p * RS.DRIER_FACTOR for p in before.precip])
    assert iowa_climate == before


def test_yearly_climates_gives_one_climate_per_full_year():
    yearly = RS.yearly_climates(fake_power_daily(2015, 2024))
    assert sorted(yearly) == list(range(2015, 2025))
    assert all(len(c.tmean) == len(c.tmin_ext) == len(c.precip) == 12 for c in yearly.values())
    part = fake_power_daily(2015, 2016).loc["2015-03-01":]        # 2015 lacks Jan and Feb
    assert sorted(RS.yearly_climates(part)) == [2016]


def test_corn_soybean_suits_every_normal_year(corn_soy, iowa_climate, iowa_site):
    res = RS.check(corn_soy, iowa_climate, RS.yearly_climates(fake_power_daily(2015, 2024)), iowa_site)
    assert res["years_checked"] == res["years_ok"] == 10 and res["bad_years"] == []
    sc = res["scenario"]
    assert sc["name"] == "2 degC warmer and 20% less rain"
    assert sc["fit_now"] == pytest.approx(corn_soy.card["fit"], abs=1e-3)   # same scoring as the card
    assert 0 <= sc["fit"] <= 1
    json.dumps(res)


def test_a_very_dry_year_is_named_and_blamed_on_rain(corn_soy, iowa_climate, iowa_site):
    daily = pd.concat([fake_power_daily(2015, 2019), fake_power_daily(2020, 2020, rain_scale=0.2),
                       fake_power_daily(2021, 2024)])
    res = RS.check(corn_soy, iowa_climate, RS.yearly_climates(daily), iowa_site)
    assert res["years_checked"] == 10 and res["years_ok"] == 9
    [bad] = res["bad_years"]
    assert bad["year"] == 2020 and bad["limited_by"] == "rain" and bad["score"] < RS.WORKS_AT
    assert bad["crop"] in {"corn", "soybean"}


def test_a_crop_that_cannot_grow_counts_as_zero(corn_soy, iowa_climate, iowa_site, monkeypatch):
    frozen = Climate([-20] * 12, [-40] * 12, [10] * 12)
    res = RS.check(corn_soy, frozen, {2020: frozen}, iowa_site)
    assert res["years_ok"] == 0 and res["bad_years"][0]["score"] == 0     # too cold: scores 0
    monkeypatch.setattr(RS, "score_harvest", lambda *a, **k: None)       # no season fits at all
    res = RS.check(corn_soy, iowa_climate, {2020: iowa_climate}, iowa_site)
    assert res["years_ok"] == 0 and res["bad_years"][0]["limited_by"] == "cannot grow"
    assert res["bad_years"][0]["score"] == 0 and res["scenario"]["fit_now"] == 0
    assert res["scenario"]["weakest"] is None                             # nothing left to lose


def test_fit_score_is_the_report_card_fit(corn_soy, crops, iowa_climate):
    cover = score_cover(crops["Secale cereale"], 9, 6, iowa_climate)      # rye cover, Oct-Mar
    rot = R.Rotation(corn_soy.placed + ((21, cover),), 2)
    slots = rot.slots
    weights = [s.months * (1.0 if s.use == "harvest" else 0.5) for s in slots]   # the old formula
    by_hand = sum(s.score * w for s, w in zip(slots, weights)) / sum(weights)
    assert R.fit_score(slots) == by_hand == R.score_card(rot, iowa_climate)["fit"]
    assert R.fit_score(corn_soy.slots) == corn_soy.card["fit"]
    assert R.fit_score(slots, [0.0] * len(slots)) == 0 and R.fit_score([]) == 0.0


def test_rotation_dict_and_report_carry_the_checks(corn_soy, iowa_climate, iowa_site, economy):
    assert corn_soy.to_dict()["resilience"] == {}
    yearly = RS.yearly_climates(fake_power_daily(2015, 2024))
    corn_soy.resilience = RS.check(corn_soy, iowa_climate, yearly, iowa_site)
    assert corn_soy.to_dict()["resilience"]["years_checked"] == 10

    class Field:                                         # explain() only reads the insights
        insights = {}
    e = explain(corn_soy, Field(), None, {k: 1.0 for k in R.CARD}, "balanced", economy=economy)
    said = " ".join(e["benefits"] + e["risks"])
    assert "every one of the last 10 years on record" in " ".join(e["benefits"])
    assert "2 degC warmer and 20% less rain" in said


def test_report_sentences_for_weak_years_and_a_falling_fit():
    from decision.report import _hotter_drier, _reliability
    bad = [{"year": y, "crop": "corn", "limited_by": "rain", "score": 0.1} for y in (2012, 2013, 2017, 2018)]
    text, benefit = _reliability({"years_checked": 10, "years_ok": 6, "bad_years": bad})
    assert not benefit and "only 6 of the last 10" in text and "2012, corn limited by rain" in text
    assert "and 1 more" in text and "2018" not in text
    text, benefit = _reliability({"years_checked": 10, "years_ok": 8, "bad_years": bad[:2]})
    assert benefit and text.startswith("Would have suited the weather in 8 of the last 10 years")
    scenario = {"name": RS.SCENARIO, "fit_now": 0.83, "fit": 0.71,
                "weakest": {"crop": "corn", "score": 0.5, "limited_by": "rain"}}
    text, benefit = _hotter_drier({"scenario": scenario})
    assert not benefit and "drops from 83% to 71%; corn is hit hardest (limited by rain)" in text
    text, benefit = _hotter_drier({"scenario": {**scenario, "fit": 0.82, "weakest": None}})
    assert benefit and text.startswith("Holds up") and "82% against 83% now" in text
    text, benefit = _hotter_drier({"scenario": {**scenario, "fit": 0.70, "weakest": None}})
    assert not benefit and "the cover crops suffer" in text
