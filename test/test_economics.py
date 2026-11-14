"""Tests for decision/economics.py: FAOSTAT yields and prices -> income per hectare -> 0-1 value."""

import pandas as pd
import pytest

from conftest import fake_faostat
from data_pullers import get_crop_requirements
from decision import economics as E
from decision.crops import build_crops

CORN, SOY, LENTIL, OKRA, TOMATO = ("Zea mays ssp. mays", "Glycine max", "Lens culinaris",
                                   "Abelmoschus esculentus", "Lycopersicon esculentum")


@pytest.fixture(scope="module")
def plain():
    return build_crops(get_crop_requirements(), E.SOLD_CROPS)


def test_translation_table_points_at_real_ecocrop_plants():
    names = set(get_crop_requirements()["scientificname"])
    assert not [sci for sci in E.SOLD_CROPS if sci not in names]
    assert set(E.FAOSTAT_TO_ECOCROP["Wheat"]) == {"Triticum aestivum", "Triticum durum"}


def test_income_is_yield_times_price(plain):
    table = E.income_table(fake_faostat(), plain, "Testland")
    corn = table[CORN]
    assert corn.income_usd_ha == pytest.approx(11.0 * 200) and corn.cost_usd_ha is None
    assert corn.price_source == "FAOSTAT Testland 2020-2024" and corn.kind == "income"
    assert "costs not included" in corn.describe()
    assert corn.to_dict()["income_is"] == "gross income"


def test_world_price_fills_a_local_gap_and_says_so(plain):
    table = E.income_table(fake_faostat(), plain, "Testland")
    assert table[LENTIL].price_usd_t == 900 and "world median" in table[LENTIL].price_source
    assert OKRA not in table                                  # not grown locally, no farmer price


def test_farmer_price_and_cost_override_faostat(plain):
    table = E.income_table(fake_faostat(), plain, "Testland",
                           local_prices={"corn": 300, "okra": 1000}, costs={"maize": 1000})
    corn = table[CORN]
    assert corn.price_source == "your price" and corn.kind == "profit"
    assert corn.income_usd_ha == pytest.approx(11.0 * 300 - 1000)
    assert "entered by you" in corn.describe()
    assert table[OKRA].yield_t_ha == 8.0 and "world median" in table[OKRA].yield_source
    assert table[SOY].income_usd_ha == pytest.approx(3.4 * 450)          # untouched


@pytest.mark.parametrize("kwargs, message", [
    (dict(local_prices={"bananas": 5}), "Unknown crop"),
    (dict(local_prices={"corn": "cheap"}), "must be a number"),
    (dict(costs={"corn": -1}), "0 or more"),
    (dict(local_prices={"alfalfa": 200}), "no yield"),                    # FAOSTAT has no hay yields
])
def test_bad_farmer_numbers_give_clear_errors(plain, kwargs, message):
    with pytest.raises(ValueError, match=message):
        E.income_table(fake_faostat(), plain, "Testland", **kwargs)


def test_no_faostat_data_gives_an_empty_table(plain):
    assert E.income_table(pd.DataFrame(), plain) == {}
    assert all(c.value == E.NO_PRICE_VALUE for c in E.with_economics(plain, {}).values())


def test_values_are_log_scaled_between_lowest_and_highest_earner(plain):
    table = E.income_table(fake_faostat(), plain, "Testland")
    values = E.value_scores(table)
    assert all(0 <= v <= 1 for v in values.values())
    assert values[TOMATO] == 1.0 and min(values.values()) == pytest.approx(E.LOWEST_VALUE)
    assert values[TOMATO] > values[CORN] > values[SOY]
    assert table[TOMATO].income_usd_ha / table[CORN].income_usd_ha > values[TOMATO] / values[CORN]


def test_a_loss_making_crop_scores_zero(plain):
    table = E.income_table(fake_faostat(), plain, "Testland", costs={"corn": 5000})
    assert table[CORN].income_usd_ha < 0 and E.value_scores(table)[CORN] == 0


def test_with_economics_fills_value_and_keeps_the_rest(plain):
    table = E.income_table(fake_faostat(), plain, "Testland")
    priced = E.with_economics(plain, table)
    assert priced[CORN].economics is table[CORN] and priced[CORN].tmin == plain[CORN].tmin
    unpriced = priced["Vicia villosa ssp. villosa"]
    assert unpriced.economics is None and unpriced.value == E.NO_PRICE_VALUE
