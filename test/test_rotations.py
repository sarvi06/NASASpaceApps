"""Tests for decision/rotations.py: search rules, report card, priorities, top-3 and baseline."""

import pytest

from decision import rotations as R
from decision.suitability import Climate, build_slots

CORN, SOY = "Zea mays ssp. mays", "Glycine max"


@pytest.fixture(scope="module")
def iowa_search(crops):
    from conftest import IOWA_PRECIP, IOWA_TMEAN, IOWA_TMIN_EXT
    clim = Climate(IOWA_TMEAN, IOWA_TMIN_EXT, IOWA_PRECIP)
    site = {"ph": 6.2, "text": "medium", "dra": "well (dry spells)", "dep": "deep (>>150 cm)",
            "sal": "low (<4 dS/m)", "fer": "high", "slope_pct": 2, "erodibility_k": 0.28}
    weights = R.resolve_priorities("balanced", site)
    familiar = {CORN, SOY}
    found = R.search_rotations(build_slots(crops, clim, site), clim, weights, 3, familiar=familiar)
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


def test_baseline_corn_soy_is_scored_and_beaten(iowa_search, crops):
    clim, site, weights, familiar, found = iowa_search
    base = R.baseline_rotation([crops[CORN], crops[SOY]], clim, weights, site, familiar=familiar)
    assert base.is_baseline and base.years == 2
    assert [s.crop.sci for s in base.harvests] == [CORN, SOY]
    assert base.card["fit"] >= 0.8 and base.card["cover"] < 0.5    # fits well, soil often bare
    assert found[0].overall > base.overall
    assert found[0].card["cover"] > base.card["cover"]


def test_report_card_scores_crop_order(iowa_search, crops):
    clim, site, weights, familiar, found = iowa_search
    assert set(found[0].card) == set(R.CARD) and "sequence" in R.CARD

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


def test_calendar_grid(iowa_search):
    *_, found = iowa_search
    grid = R.calendar_grid(found[0])
    assert grid.count("\n  Y") == found[0].years and "Jan" in grid
