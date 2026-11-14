"""Offline end-to-end test of backend.recommend(): the pullers are replaced by Iowa-like data."""

import json

import pandas as pd
import pytest

import backend
from conftest import corn_soy_history, fake_faostat, fake_power_daily, nicollet_soil

ARGS = (42.065, -93.73, "2015-01-01", "2024-12-31")
CORN, SOY, OATS = "Zea mays ssp. mays", "Glycine max", "Avena sativa"


@pytest.fixture
def offline(monkeypatch):
    """Swap the web pullers for fixed data (EcoCrop still comes from the saved table)."""
    monkeypatch.setattr(backend, "get_country",
                        lambda lat, lon: {"name": "United States", "iso2": "US", "m49": 840})
    monkeypatch.setattr(backend, "get_crop_economics", lambda m49: fake_faostat())
    monkeypatch.setattr(backend, "get_climate",
                        lambda lat, lon, s, e: fake_power_daily(s.year, e.year))
    monkeypatch.setattr(backend, "get_soil", lambda lat, lon: nicollet_soil())
    monkeypatch.setattr(backend, "get_crop_history",
                        lambda lat, lon, a, b: corn_soy_history(a, b))
    monkeypatch.setattr(backend, "get_soil_moisture",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no login")))


def test_recommend_returns_three_options_and_current_rotation(offline):
    progress = []
    rec = backend.recommend(42.065, -93.73, "2015-01-01", "2024-12-31", on_progress=progress.append)
    assert len(rec.rotations) == 3
    assert rec.baseline is not None and rec.baseline.name == "corn -> soybean"
    assert rec.field.current_rotation["source"] == "USDA CropScape"
    for rot in rec.rotations + [rec.baseline]:
        e = rot.explanation
        assert e["why"] and e["evidence"] and e["benefits"] and e["information_gaps"] and e["risks"]
    assert progress[0].startswith("Downloading NASA POWER") and progress[-1] == "Done."
    text = rec.to_text()
    assert "OPTION 3" in text and "YOUR CURRENT ROTATION" in text and "agronomist" in text
    json.dumps(rec.to_dict())                                    # front-end friendly


def test_priorities_and_user_rotation(offline):
    rec = backend.recommend(42.065, -93.73, "2015-01-01", "2024-12-31",
                            priorities="save_water", current_rotation=["corn", "corn", "soybean"])
    assert rec.priority_name == "save_water"
    assert rec.field.current_rotation["source"] == "entered by you"
    assert rec.baseline.years == 3


def test_previous_crop_decides_where_each_rotation_starts(offline):
    args = (42.065, -93.73, "2015-01-01", "2024-12-31")
    default = backend.recommend(*args)                      # CropScape: soybean in 2024
    assert default.previous_crop == {"crop": "soybean", "scientific_name": "Glycine max",
                                     "source": "USDA CropScape 2024"}
    for previous, family in (("corn", "Poaceae"), ("soybean", "Fabaceae")):
        rec = backend.recommend(*args, previous_crop=previous)
        assert rec.previous_crop["crop"] == previous and rec.previous_crop["source"] == "entered by you"
        assert [r.canonical() for r in rec.rotations] == [r.canonical() for r in default.rotations]
        for rot in rec.rotations:
            assert rot.harvests[0].crop.family != family
            assert previous in rot.start_note and rot.start_note in rot.explanation["why"]
        assert f": {previous}" in rec.to_text()
        assert rec.to_dict()["previous_crop"]["crop"] == previous


def test_previous_crop_falls_back_to_the_entered_rotation(offline, monkeypatch):
    monkeypatch.setattr(backend, "in_contiguous_us", lambda lat, lon: False)
    args = (42.065, -93.73, "2015-01-01", "2024-12-31")
    rec = backend.recommend(*args, current_rotation=["soybean", "corn"])
    assert rec.previous_crop["crop"] == "corn"
    unknown = backend.recommend(*args)
    assert unknown.previous_crop is None
    assert any("grown last is unknown" in w for w in unknown.warnings)
    assert all(not r.start_note for r in unknown.rotations)


def test_recommend_after_crop_needs_and_uses_the_last_crop(offline):
    rec = backend.recommend_after_crop(*ARGS, "corn", priorities="build_soil")
    assert rec.previous_crop["crop"] == "corn" and rec.priority_name == "build_soil"
    assert all(r.harvests[0].crop.family != "Poaceae" and "corn" in r.start_note for r in rec.rotations)
    for missing in (None, "", "  "):
        with pytest.raises(ValueError, match="last_crop is required"):
            backend.recommend_after_crop(*ARGS, missing)


def test_recommend_around_crops_puts_them_in_every_rotation(offline):
    rec = backend.recommend_around_crops(*ARGS, ["oats", "dry bean"])
    assert rec.must_grow == ["oats", "dry bean"] and len(rec.rotations) == 3
    for rot in rec.rotations:
        assert {"oats", "dry bean"} <= {s.crop.name for s in rot.harvests}
    assert len({r.name for r in rec.rotations}) == 3
    assert "Must grow (in every option): oats, dry bean" in rec.to_text()
    assert rec.to_dict()["must_grow"] == ["oats", "dry bean"]
    one = backend.recommend_around_crops(*ARGS, "oats", last_crop="soybean")     # a single name
    assert one.must_grow == ["oats"] and one.previous_crop["crop"] == "soybean"


@pytest.mark.parametrize("must_grow, kwargs, message", [
    ([], {}, "one or two"),
    (["corn", "oats", "wheat"], {}, "one or two"),
    (["bananas"], {}, "Unknown crop"),
    (["sugarcane"], {}, "cannot be grown"),                            # tropical, Iowa is not
    (["corn", "wheat"], dict(rotation_years=2), "No 2-year rotation"),  # same family, no break
])
def test_must_grow_problems_give_clear_errors(offline, must_grow, kwargs, message):
    with pytest.raises(ValueError, match=message):
        backend.recommend_around_crops(*ARGS, must_grow, **kwargs)


def test_poorly_suited_must_grow_crop_is_kept_with_a_warning(offline):
    rec = backend.recommend_around_crops(*ARGS, ["rice"])
    assert any("rice is a poor fit" in w for w in rec.warnings)
    assert all("rice" in {s.crop.name for s in r.harvests} for r in rec.rotations)


def test_income_comes_from_faostat_and_farmer_numbers_replace_it(offline):
    rec = backend.recommend(*ARGS)
    assert rec.country["name"] == "United States"
    corn = rec.economy.get(rec.crops[CORN])
    assert corn.income_usd_ha == pytest.approx(2200) and "FAOSTAT United States" in corn.price_source
    data = rec.to_dict()
    assert data["economics"][0]["crop"] == "tomato" and data["economics"][0]["income_is"] == "gross income"
    assert data["economy"]["typical_income_usd_ha"] == pytest.approx(rec.economy.typical_income)
    assert {"income", "market"} <= set(data["recommended_rotations"][0]["card"])
    assert any(src.startswith("FAOSTAT") for src in rec.data_sources)
    text = rec.to_text()
    assert "Money: about $" in text and "costs not included" in text and "typical hectare" in text
    for rot in rec.rotations:                                          # report and ranking agree
        assert f"${rot.income_usd_ha:,.0f} per hectare per year" in " ".join(rot.explanation["benefits"])

    value = lambda r, sci: r.economy.value(r.crops[sci])               # 0-1 used in the ranking
    own = backend.recommend(*ARGS, farm_numbers={"oats": {"price": 9000}})
    oats = own.economy.get(own.crops[OATS])
    assert oats.price_source == "your price" and oats.income_usd_ha == pytest.approx(2.4 * 9000)
    assert value(own, OATS) == 1 > value(rec, OATS)
    assert value(own, CORN) == value(rec, CORN)                        # one price moves one crop
    crops_before = {s.crop.name for r in rec.rotations for s in r.harvests}
    crops_after = {s.crop.name for r in own.rotations for s in r.harvests}
    assert "oats" not in crops_before and "oats" in crops_after


def test_entered_costs_compare_every_crop_on_profit(offline):
    plain = backend.recommend(*ARGS)
    costed = backend.recommend(*ARGS, farm_numbers={"corn": {"cost": 1100}})     # half of corn's income
    assert costed.economy.cost_share == pytest.approx(0.5)
    corn, soy = costed.economy.get(costed.crops[CORN]), costed.economy.get(costed.crops[SOY])
    assert corn.kind == soy.kind == "profit" and soy.cost_source.startswith("estimated")
    assert costed.economy.value(costed.crops[CORN]) == pytest.approx(plain.economy.value(plain.crops[CORN]))
    text = costed.to_text()
    assert "other crops assumed at 50% of income" in text and "entered by you" in text
    assert costed.to_dict()["economy"]["assumed_cost_share"] == pytest.approx(0.5)


def test_farmer_price_and_yield_make_an_unlisted_crop_usable(offline):
    rec = backend.recommend_around_crops(*ARGS, ["alfalfa"],
                                         farm_numbers={"alfalfa": {"price": 220, "yield": 9}})
    alfalfa = rec.economy.get(rec.crops["Medicago sativa"])
    assert alfalfa.income_usd_ha == pytest.approx(1980) and alfalfa.yield_source == "your yield"
    assert all("alfalfa" in {s.crop.name for s in r.harvests} for r in rec.rotations)
    with pytest.raises(ValueError, match="give both a price and a yield"):
        backend.recommend(*ARGS, farm_numbers={"alfalfa": {"price": 220}})


def test_faostat_failure_is_a_warning_not_a_crash(offline, monkeypatch):
    def down(m49):
        raise RuntimeError("no internet")
    monkeypatch.setattr(backend, "get_crop_economics", down)
    rec = backend.recommend(*ARGS)
    assert any("FAOSTAT prices and yields unavailable" in w for w in rec.warnings)
    assert rec.economy.crops == {} and len(rec.rotations) == 3
    assert all(r.card["income"] == r.card["market"] == 0.5 for r in rec.rotations)
    assert "none available" in rec.to_text()


def test_country_can_be_given_instead_of_looked_up(offline, monkeypatch):
    monkeypatch.setattr(backend, "get_country", lambda lat, lon: 1 / 0)       # must not be called
    asked = []
    monkeypatch.setattr(backend, "get_crop_economics", lambda m49: asked.append(m49) or fake_faostat())
    rec = backend.recommend(*ARGS, country="Japan")
    assert asked == [392] and rec.country["iso2"] == "JP"


def test_smap_failure_is_a_warning_not_a_crash(offline):
    rec = backend.recommend(42.065, -93.73, "2018-01-01", "2024-12-31", use_smap=True)
    assert any("SMAP" in w for w in rec.warnings)


def test_short_period_warns(offline):
    rec = backend.recommend(42.065, -93.73, "2022-01-01", "2023-12-31")
    assert any("years of data" in w for w in rec.warnings)


@pytest.mark.parametrize("kwargs, message", [
    (dict(lat=420), "Latitude"),
    (dict(start_date="2024-01-01", end_date="2023-01-01"), "after"),
    (dict(start_date="2024-01-01", end_date="2024-06-30"), "12 months"),
    (dict(priorities="money"), "priorities"),
    (dict(rotation_years=7), "rotation_years"),
    (dict(current_rotation=["bananas"]), "Unknown crop"),
    (dict(previous_crop="bananas"), "Unknown crop"),
    (dict(must_grow=["corn", "oats", "wheat"]), "one or two"),
    (dict(farm_numbers={"bananas": {"price": 3}}), "Unknown crop"),
    (dict(farm_numbers={"corn": {"cost": -5}}), "0 or more"),
    (dict(country="Atlantis"), "Unknown country"),
])
def test_bad_inputs_give_clear_errors(offline, kwargs, message):
    args = dict(lat=42.065, lon=-93.73, start_date="2015-01-01", end_date="2024-12-31") | kwargs
    with pytest.raises(ValueError, match=message):
        backend.recommend(**args)
