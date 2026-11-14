"""Tests for decision/economics.py: FAOSTAT rows + the farmer's numbers -> one Economy."""

import pandas as pd
import pytest

from conftest import fake_faostat
from data_pullers import get_crop_requirements
from decision import economics as E
from decision.suitability import Slot

CORN, SOY, WHEAT, LENTIL, OKRA, TOMATO, ALFALFA, VETCH = (
    "Zea mays ssp. mays", "Glycine max", "Triticum aestivum", "Lens culinaris",
    "Abelmoschus esculentus", "Lycopersicon esculentum", "Medicago sativa", "Vicia villosa ssp. villosa")


def build(crops, **farm_numbers):
    return E.build_economy(fake_faostat(), crops, "Testland", farm_numbers or None)


# ---- the name table -------------------------------------------------------------------
def test_name_table_is_a_data_file_pointing_at_real_ecocrop_plants():
    assert E.NAMES_FILE.suffix == ".csv" and E.NAMES_FILE.exists()
    names = set(get_crop_requirements()["scientificname"])
    assert not [sci for sci in E.SOLD_CROPS if sci not in names]
    assert set(E.FAOSTAT_TO_ECOCROP["Wheat"]) == {"Triticum aestivum", "Triticum durum"}
    assert len(E.SOLD_CROPS) >= 90 and E.SOLD_CROPS[CORN] == "corn"


# ---- income ---------------------------------------------------------------------------
def test_income_is_yield_times_price(crops, economy):
    corn = economy.get(crops[CORN])
    assert corn.income_usd_ha == pytest.approx(11.0 * 200) and corn.cost_usd_ha is None
    assert economy.income(crops[CORN]) == corn.income_usd_ha and corn.kind == "income"
    assert corn.price_source == "FAOSTAT Testland 2020-2024" and corn.price_range == (160, 250)
    text = corn.describe()
    assert "yearly range $160-250" in text and "costs not included" in text
    assert corn.to_dict()["income_is"] == "gross income"
    assert economy.get(crops[VETCH]) is None and economy.income(crops[VETCH]) == 0     # no market item


def test_typical_income_is_the_area_weighted_hectare(economy):
    rows = fake_faostat().dropna(subset=["yield_t_ha", "price_usd_t", "area_ha"])
    income = rows["yield_t_ha"] * rows["price_usd_t"]
    assert economy.typical_income == pytest.approx((income * rows["area_ha"]).sum() / rows["area_ha"].sum())
    assert 1500 < economy.typical_income < 2200                    # set by corn, soybean and wheat
    assert economy.cost_share is None


def test_missing_local_price_uses_the_world_price_at_the_local_price_level(crops, economy):
    rows = fake_faostat().set_index("item")
    level = E.price_level(rows)
    assert 0.5 < level < 1 and level == pytest.approx((rows.price_usd_t / rows.world_price_usd_t).median())
    lentil = economy.get(crops[LENTIL])
    assert lentil.price_usd_t == pytest.approx(900 * level) and lentil.price_source.startswith("estimate")
    assert lentil.price_range is None
    assert E.price_level(rows.head(2)) == 1.0                      # too few crops to compare


def test_a_crop_new_to_the_country_is_priced_from_world_figures_with_no_market(crops, economy):
    okra = economy.get(crops[OKRA])
    assert okra.yield_t_ha == 8.0 and "not grown in Testland" in okra.yield_source
    assert okra.area_share is None and economy.market(crops[OKRA]) == 0
    assert economy.value(crops[OKRA]) > 0


# ---- the farmer's numbers ---------------------------------------------------------------
def test_farmer_price_and_yield_replace_faostat(crops, economy):
    own = build(crops, corn={"price": 300, "yield": 13})
    corn = own.get(crops[CORN])
    assert (corn.price_source, corn.yield_source) == ("your price", "your yield")
    assert corn.income_usd_ha == pytest.approx(13 * 300) and corn.price_range is None
    assert own.market(crops[CORN]) == 1.0
    for other in (SOY, WHEAT, TOMATO):                              # nothing else moves
        assert own.value(crops[other]) == economy.value(crops[other])
        assert own.get(crops[other]) == economy.get(crops[other])
    assert own.typical_income == economy.typical_income


def test_price_and_yield_together_price_a_crop_faostat_does_not_cover(crops, economy):
    assert economy.get(crops[ALFALFA]) is None
    own = build(crops, alfalfa={"price": 200, "yield": 9})
    assert own.income(crops[ALFALFA]) == pytest.approx(1800) and own.market(crops[ALFALFA]) == 1.0
    with pytest.raises(ValueError, match="give both a price and a yield"):
        build(crops, alfalfa={"price": 200})


def test_costs_are_spread_so_profit_is_compared_with_profit(crops, economy):
    own = build(crops, corn={"cost": 880}, wheat={"cost": 495})    # 40% and 60% of income
    assert own.cost_share == pytest.approx(0.5)
    corn, soy = own.get(crops[CORN]), own.get(crops[SOY])
    assert corn.cost_source == "entered by you" and corn.income_usd_ha == pytest.approx(2200 - 880)
    assert corn.kind == "profit" and "entered by you" in corn.describe()
    assert soy.cost_usd_ha == pytest.approx(0.5 * 3.4 * 450) and soy.cost_source.startswith("estimated: 50%")
    assert own.typical_income == pytest.approx(economy.typical_income * 0.5)
    assert own.value(crops[SOY]) == pytest.approx(economy.value(crops[SOY]))    # same standing as before
    assert own.value(crops[CORN]) > economy.value(crops[CORN])                  # cheaper than assumed
    assert own.value(crops[WHEAT]) < economy.value(crops[WHEAT])                # dearer than assumed


def test_a_loss_making_crop_scores_zero(crops):
    own = build(crops, corn={"cost": 5000})
    assert own.income(crops[CORN]) < 0 and own.value(crops[CORN]) == 0
    assert own.cost_share == E.MAX_ASSUMED_COST_SHARE               # capped, others not all losses
    assert own.income(crops[SOY]) > 0


@pytest.mark.parametrize("numbers, message", [
    ({"bananas": {"price": 5}}, "Unknown crop"),
    ({"corn": {"price": "cheap"}}, "must be a number"),
    ({"corn": {"cost": -1}}, "0 or more"),
    ({"corn": {"yield": 0}}, "more than 0"),
    ({"corn": {"profit": 3}}, "price, yield, cost"),
    ({"corn": 180}, "must be a dict"),
])
def test_bad_farmer_numbers_give_clear_errors(crops, numbers, message):
    with pytest.raises(ValueError, match=message):
        E.build_economy(fake_faostat(), crops, "Testland", numbers)


# ---- scores -----------------------------------------------------------------------------
def test_score_is_half_at_the_typical_hectare_on_a_log_scale(economy):
    typical = economy.typical_income
    assert economy.score(typical) == pytest.approx(0.5)
    assert economy.score(typical * 10) == 1.0 and economy.score(typical * 100) == 1.0
    assert economy.score(typical / 10) == 0.0 and economy.score(0) == 0.0 and economy.score(-50) == 0.0
    assert economy.score(typical * 10 ** 0.5) == pytest.approx(0.75)
    assert economy.score(10) == pytest.approx(economy.score(10.5), abs=0.02)     # no jump near zero


def test_market_follows_the_share_of_harvested_area(crops, economy):
    assert economy.market(crops[CORN]) == 1.0 and economy.market(crops[SOY]) == 1.0
    tomato = economy.get(crops[TOMATO])
    assert tomato.area_share == pytest.approx(110_000 / fake_faostat()["area_ha"].sum())
    assert 0.2 < economy.market(crops[TOMATO]) < 0.5 < economy.market(crops["Oryza sativa"]) < 1
    assert economy.market(crops[VETCH]) == 0


def test_income_above_typical_is_trusted_only_as_far_as_the_crop_is_grown(crops, economy):
    typical = economy.typical_income
    tomato, market = economy.income(crops[TOMATO]), economy.market(crops[TOMATO])
    assert tomato > 5 * typical
    assert economy.trusted_income(crops[TOMATO]) == pytest.approx(typical * (tomato / typical) ** market)
    assert typical < economy.trusted_income(crops[TOMATO]) < tomato / 2
    assert economy.trusted_income(crops[CORN]) == economy.income(crops[CORN])      # widely grown
    assert economy.trusted_income(crops[WHEAT]) == economy.income(crops[WHEAT])    # below typical
    assert economy.trusted_income(crops[VETCH]) == 0
    costed = build(crops, tomato={"cost": 4000})                    # a real cost: trusted in full
    assert costed.trusted_income(crops[TOMATO]) == pytest.approx(12000 - 4000)
    sold = build(crops, tomato={"price": 120})                      # the farmer has a buyer
    assert sold.trusted_income(crops[TOMATO]) == pytest.approx(12000)


def test_rank_combines_suitability_value_and_market(crops, economy):
    def slot(sci, score):
        return Slot(crops[sci], 4, 5, "harvest", score, "temperature")
    corn = slot(CORN, 0.8)
    assert economy.rank(corn) == pytest.approx(0.8 * (economy.value(crops[CORN]) + 1.0) / 2)
    assert economy.rank(slot(CORN, 0.4)) == pytest.approx(economy.rank(corn) / 2)
    assert economy.rank(slot(VETCH, 1.0)) == 0                      # nothing known to sell it for


def test_no_data_means_every_score_is_neutral(crops):
    empty = E.build_economy(pd.DataFrame(), crops)
    assert empty.crops == {} and empty.typical_income is None
    for sci in (CORN, VETCH):
        assert empty.value(crops[sci]) == empty.market(crops[sci]) == E.NEUTRAL
    assert empty.score(123) == E.NEUTRAL and empty.income(crops[CORN]) == 0
    assert E.Economy().value(crops[CORN]) == E.NEUTRAL


def test_table_lists_priced_crops_highest_income_first(crops, economy):
    table = economy.table(crops)
    assert table[0]["crop"] == "tomato" and len(table) == len(economy.crops)
    assert {"value", "market", "income_usd_ha", "price_range_usd_t", "area_share"} <= set(table[0])
