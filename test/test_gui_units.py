"""Tests for gui/units.py: US farm units to the metric units the back end takes."""

import pytest

from gui.tabs.base import farm_numbers
from gui.units import acres_to_ha, ha_to_acres, to_metric, unit_for


def test_corn_is_converted_by_the_bushel():
    assert unit_for(" Corn ") == ("bushel", 56)
    metric = to_metric("corn", {"price": 4.5, "yield": 200, "cost": 700})
    assert metric["yield"] == pytest.approx(12.55, abs=0.01)         # tonnes per hectare
    assert metric["price"] == pytest.approx(177, abs=0.5)            # USD per tonne
    assert metric["cost"] == pytest.approx(700 * 2.471)              # USD per hectare


def test_a_crop_that_is_not_in_the_table_uses_hundredweight():
    assert unit_for("potato") == ("cwt", 100.0)
    metric = to_metric("potato", {"price": 10, "yield": 400})
    assert metric["price"] == pytest.approx(10 * 22.0462)
    assert metric["yield"] == pytest.approx(400 * 100 / 2204.62 * 2.471)


def test_only_the_known_keys_are_converted():
    assert to_metric("corn", {"other": 3}) == {"other": 3}
    assert to_metric("corn", {}) == {}


def test_acres_and_hectares_round_trip():
    for x in (0.5, 12, 160.25):
        assert acres_to_ha(ha_to_acres(x)) == pytest.approx(x)
        assert ha_to_acres(acres_to_ha(x)) == pytest.approx(x)


def test_farm_numbers_returns_metric_values():
    numbers = farm_numbers([("corn", "4.50", "200", "")])
    assert numbers["corn"]["yield"] == pytest.approx(12.55, abs=0.01)
    assert numbers["corn"]["price"] == pytest.approx(177, abs=0.5)
