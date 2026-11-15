"""Tests for decision/rotations.py: search rules, report card, priorities, top-3 and baseline."""

import pytest

from decision import rotations as R
from decision.economics import MIN_MARKET_TO_SUGGEST
from decision.sequence import follow_score
from decision.suitability import Climate, build_slots, score_cover

CORN, SOY, OATS, BEAN = "Zea mays ssp. mays", "Glycine max", "Avena sativa", "Phaseolus vulgaris"


@pytest.fixture(scope="module")
def iowa_search(crops, economy):
    from conftest import IOWA_PRECIP, IOWA_TMEAN, IOWA_TMIN_EXT
    clim = Climate(IOWA_TMEAN, IOWA_TMIN_EXT, IOWA_PRECIP)
    site = {"lat": 42.065, "ph": 6.2, "text": "medium", "dra": "well (dry spells)", "dep": "deep (>>150 cm)",
            "sal": "low (<4 dS/m)", "fer": "high", "slope_pct": 2, "erodibility_k": 0.28}
    weights = R.resolve_priorities("balanced", site)
    familiar = {CORN, SOY}
    slots = build_slots(crops, clim, site, rank=economy.rank, always=familiar)
    found = R.search_rotations(slots, clim, weights, 3, economy=economy)
    return clim, site, weights, familiar, found


def test_priorities():
    for name in R.PRIORITY_PRESETS:
        assert sum(R.resolve_priorities(name).values()) == pytest.approx(1)
    assert R.resolve_priorities("build_soil")["cover"] > R.resolve_priorities("balanced")["cover"]
    steep = R.resolve_priorities("balanced", {"slope_pct": 9})
    assert steep["cover"] > R.resolve_priorities("balanced")["cover"]
    custom = R.resolve_priorities({"water": 5})
    assert max(custom, key=custom.get) == "water"
    with pytest.raises(ValueError):
        R.resolve_priorities("money")
    with pytest.raises(ValueError):
        R.resolve_priorities({"profit": 1})


def test_search_finds_rotations_sorted_best_first(iowa_search):
    *_, found = iowa_search
    assert len(found) >= 3
    assert [r.overall for r in found] == sorted((r.overall for r in found), reverse=True)
    assert len({r.canonical() for r in found}) == len(found)


def test_every_rotation_obeys_the_rules(iowa_search):
    *_, found = iowa_search
    for r in found[:200]:
        placed = list(r.placed)
        for (a1, s1), (a2, s2) in zip(placed, placed[1:]):
            assert a2 >= a1 + s1.months, "crops overlap"
            assert not (s1.use == s2.use == "cover"), "cover after cover"
            if s1.use == "cover" and s2.use == "harvest":
                assert s1.crop.family != s2.crop.family
        harvests = r.harvests
        assert len(harvests) >= r.years
        for h1, h2 in zip(harvests, harvests[1:] + harvests[:1]):
            assert h1.crop.family != h2.crop.family, "same family back to back"
        assert placed[-1][0] + placed[-1][1].months <= placed[0][0] + r.horizon, "runs into next cycle"
        assert all(0 <= v <= 1 for v in r.card.values())


def test_short_summer_climate_allows_one_harvest_a_year(iowa_search):
    clim, *_, found = iowa_search
    assert R.harvests_per_year(clim) == 1
    assert all(len(r.harvests) == r.years for r in found[:100])
    assert R.harvests_per_year(Climate([25] * 12, [18] * 12, [100] * 12)) == 2


def test_top_three_are_distinct_and_include_legumes(iowa_search):
    *_, familiar, found = iowa_search
    top = R.pick_top(found, 3, familiar)
    assert len(top) == 3
    assert top[0].strategy == "best match for your priorities"
    assert any(r.strategy == "builds on the crops you already grow" for r in top)
    for i, a in enumerate(top):
        assert any(s.crop.legume for s in a.slots)
        for b in top[i + 1:]:
            assert R._overlap(a, b) < 1


def test_top_three_hold_only_believable_crops(iowa_search, economy):
    clim, site, weights, familiar, found = iowa_search
    for r in R.pick_top(found, 3, familiar):
        for s in r.covers:                                          # short-lived, grown this far north
            assert s.crop.can_cover and (s.crop.lat_limit is None or s.crop.lat_limit >= site["lat"])
        for s in r.harvests:                                        # widely grown, or already grown here
            assert economy.market(s.crop) >= MIN_MARKET_TO_SUGGEST or s.crop.sci in familiar, s.crop.name
        names = {s.crop.name for s in r.slots}
        assert not names & {"tomato", "leafcup"}, r.name


def test_income_score_uses_the_rotations_real_dollars_per_year(iowa_search, economy):
    *_, found = iowa_search
    for r in found[:100]:
        dollars = sum(economy.income(s.crop) * s.score for s in r.harvests) / r.years
        trusted = sum(economy.trusted_income(s.crop) * s.score for s in r.harvests) / r.years
        assert r.income_usd_ha == pytest.approx(dollars) and dollars > 0
        assert r.trusted_income_usd_ha == pytest.approx(trusted) and trusted <= dollars + 1e-9
        assert r.card["income"] == pytest.approx(economy.score(trusted))
        markets = [economy.market(s.crop) for s in r.harvests]
        assert r.card["market"] == pytest.approx(sum(markets) / len(markets))
        assert r.to_dict()["income_usd_ha_per_year"] == round(dollars)


def test_a_long_low_earner_no_longer_counts_like_a_short_high_earner(iowa_search, crops, economy):
    clim, site, weights, *_ = iowa_search
    corn_soy = R.baseline_rotation([crops[CORN], crops[SOY]], clim, weights, site, economy=economy)
    corn_only = R.baseline_rotation([crops[CORN]], clim, weights, site, economy=economy)
    assert corn_only.income_usd_ha > corn_soy.income_usd_ha            # corn earns more than soybean
    assert corn_only.card["income"] > corn_soy.card["income"]
    assert corn_soy.card["market"] == 1.0
    no_prices = R.baseline_rotation([crops[CORN], crops[SOY]], clim, weights, site)
    assert no_prices.card["income"] == no_prices.card["market"] == 0.5  # neutral without data


def test_baseline_corn_soy_is_scored_and_beaten(iowa_search, crops, economy):
    clim, site, weights, familiar, found = iowa_search
    base = R.baseline_rotation([crops[CORN], crops[SOY]], clim, weights, site, economy=economy)
    assert base.is_baseline and base.years == 2
    assert [s.crop.sci for s in base.harvests] == [CORN, SOY]
    assert base.card["fit"] >= 0.8 and base.card["cover"] < 0.5    # fits well, soil often bare
    assert found[0].overall > base.overall
    assert found[0].card["cover"] > base.card["cover"]


def test_report_card_scores_crop_order(iowa_search, crops):
    clim, site, weights, familiar, found = iowa_search
    assert set(found[0].card) == set(R.CARD) and {"sequence", "income", "market"} <= set(R.CARD)

    def card(names):
        return R.baseline_rotation([crops[n] for n in names], clim, weights, site).card

    assert card([CORN, CORN])["sequence"] == 0                      # corn after corn
    assert card([CORN, SOY])["sequence"] > card([CORN, "Helianthus annuus"])["sequence"] > 0


def test_start_after_enters_the_cycle_where_it_suits_the_last_crop(iowa_search, crops):
    *_, found = iowa_search
    for rot in found[:50]:
        for previous in (crops[CORN], crops[SOY]):
            started = R.start_after(rot, previous)
            assert started.canonical() == rot.canonical()           # same rotation, same months
            assert started.card == rot.card and started.overall == rot.overall
            assert previous.name in started.start_note
            assert [a for a, _ in started.placed] == sorted(a for a, _ in started.placed)
            assert 0 <= started.placed[0][0] < 12
            families = {s.crop.family for s in rot.harvests}
            if families - {previous.family}:                        # another entry point exists
                assert started.harvests[0].crop.family != previous.family


def test_must_grow_crops_are_in_every_rotation(iowa_search, crops, economy):
    clim, site, weights, familiar, plain = iowa_search
    must = {OATS, BEAN}
    assert not any(must <= {s.crop.sci for s in r.harvests} for r in plain[:20])   # not there anyway
    slots = build_slots(crops, clim, site, rank=economy.rank, always=must)
    found = R.search_rotations(slots, clim, weights, 3, economy=economy, must_grow=must)
    assert found and all(must <= {s.crop.sci for s in r.harvests} for r in found)
    assert all(0 <= r.overall <= 1 for r in found)                  # the search bonus is not a score
    top = R.pick_top(found, 3, familiar, shared=must)
    assert len(top) == 3
    for i, a in enumerate(top):                                     # differ beyond the shared crops
        assert all(R._overlap(a, b, must) < 1 for b in top[i + 1:])


def test_must_grow_crops_of_one_family_need_a_break_between_them(iowa_search, crops):
    clim, site, weights, *_ = iowa_search
    must = {CORN, "Triticum aestivum"}
    slots = build_slots(crops, clim, site, always=must)
    assert R.search_rotations(slots, clim, weights, 2, must_grow=must) == []
    four_years = R.search_rotations(slots, clim, weights, 4, must_grow=must)
    assert four_years and all(must <= {s.crop.sci for s in r.harvests} for r in four_years)


def test_previous_crop_sets_the_start_and_counts_in_the_ranking(iowa_search, crops, economy):
    clim, site, weights, familiar, plain = iowa_search
    slots = build_slots(crops, clim, site, rank=economy.rank, always=familiar)
    after_corn = R.search_rotations(slots, clim, weights, 3, economy=economy, previous=crops[CORN])
    assert {r.canonical() for r in after_corn} == {r.canonical() for r in plain}
    before = {r.canonical(): r for r in plain}
    changed = 0
    for r in after_corn[:100]:
        entry = follow_score(crops[CORN], r.harvests[0].crop)[0]
        pairs = [follow_score(a.crop, b.crop)[0] for a, b in r.hand_overs()]
        assert r.card["sequence"] == pytest.approx((sum(pairs) + entry) / (len(pairs) + 1))
        assert "corn" in r.start_note
        changed += r.card["sequence"] != pytest.approx(before[r.canonical()].card["sequence"])
    assert changed


def test_water_is_the_rain_share_of_the_harvest_crops(iowa_search):
    from dataclasses import replace

    from conftest import IOWA_ET0
    from decision.water import rain_share
    clim, *_, found = iowa_search
    rot = found[0]
    # without ET0: the EcoCrop fallback (yearly rain vs each crop's rain need)
    old = [R._ecocrop_water_score(s.crop, clim.annual_rain) for s in rot.harvests]
    assert rot.card["water"] == pytest.approx(sum(old) / len(old))
    # with ET0: rain over each crop's own season vs its water need there
    wet = replace(clim, et0=list(IOWA_ET0))
    shares = [rain_share(s.start, s.months, IOWA_ET0, clim.precip) for s in rot.harvests]
    assert R.score_card(rot, wet)["water"] == pytest.approx(sum(shares) / len(shares))
    falling = {"rain_trend_mm_per_decade": -100}                     # plan for less rain
    scale = R.expected_rain(wet, falling) / wet.annual_rain
    shares = [rain_share(s.start, s.months, IOWA_ET0, clim.precip, scale) for s in rot.harvests]
    assert R.score_card(rot, wet, insights=falling)["water"] == pytest.approx(sum(shares) / len(shares))


def test_calendar_grid(iowa_search):
    *_, found = iowa_search
    grid = R.calendar_grid(found[0])
    assert grid.count("\n  Y") == found[0].years and "Jan" in grid


def test_a_killed_cover_leaves_the_soil_bare_after_its_residue(crops, iowa_search):
    clim, site, weights, familiar, found = iowa_search
    cover = score_cover(crops["Fagopyrum esculentum"], 7, 6, clim)           # Aug-Jan, killed by frost
    assert cover.covered < cover.months
    rot = R.Rotation(placed=((7, cover),), years=1)
    assert rot.bare_months() == [m for m in range(12) if m not in range(7, 7 + cover.covered)]
    assert len(rot.covered_months()) == cover.covered
    assert R.score_card(rot, clim)["cover"] < cover.months / 12
