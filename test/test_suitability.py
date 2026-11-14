"""Tests for decision/suitability.py on an Iowa-like field."""

import pytest

from decision.suitability import (MONTHS, Climate, best_single_crops, build_slots, score_cover,
                                  score_harvest, soil_factor, trapezoid)

CORN, SOY, RICE = "Zea mays ssp. mays", "Glycine max", "Oryza sativa"


def best(crop, clim, site=None, irrigated=False):
    slots = [s for m in range(12) if (s := score_harvest(crop, m, clim, site, irrigated))]
    return max(slots, key=lambda s: s.score) if slots else None


def test_trapezoid_shape():
    assert trapezoid(5, 0, 10, 20, 30) == 0.5
    assert trapezoid(15, 0, 10, 20, 30) == 1.0
    assert trapezoid(25, 0, 10, 20, 30) == 0.5
    assert trapezoid(-1, 0, 10, 20, 30) == 0.0 and trapezoid(31, 0, 10, 20, 30) == 0.0
    assert trapezoid(7, None, None, None, None) == 1.0


def test_corn_and_soybean_suit_iowa_in_summer(crops, iowa_climate, iowa_site):
    for sci in (CORN, SOY):
        slot = best(crops[sci], iowa_climate, iowa_site)
        assert slot.score >= 0.6, (sci, slot.score, slot.limiter)
        assert MONTHS[slot.start] in ("Apr", "May", "Jun")
        assert slot.months >= 3


def test_corn_cannot_grow_through_winter(crops, iowa_climate):
    assert (s := score_harvest(crops[CORN], 10, iowa_climate)) is None or s.score == 0


def test_rice_does_not_suit_iowa(crops, iowa_climate, iowa_site):
    assert best(crops[RICE], iowa_climate, iowa_site).score < 0.4


def test_winter_wheat_overwinters(crops, iowa_climate, iowa_site):
    slot = score_harvest(crops["Triticum aestivum"], 9, iowa_climate, iowa_site)   # Oct planting
    assert slot is not None and slot.score >= 0.5
    assert slot.months > 6 and "winter" in slot.factors


def test_rye_cover_survives_winter_and_crimson_clover_is_flagged(crops, iowa_climate, iowa_site):
    rye = score_cover(crops["Secale cereale"], 8, 8, iowa_climate, iowa_site)       # Sep-Apr
    assert rye is not None and rye.score >= 0.6 and rye.factors.get("winter", 1) == 1
    clover = score_cover(crops["Trifolium incarnatum"], 8, 8, iowa_climate, iowa_site)
    assert clover is not None and clover.flags and "winter-kill" in clover.flags[0]


def test_frost_tender_cover_is_killed_but_still_counts(crops, iowa_climate):
    radish = score_cover(crops["Raphanus sativus"], 8, 8, iowa_climate)
    assert radish is not None and any("residue" in e for e in radish.evidence)


def test_irrigation_never_lowers_a_score(crops, iowa_climate):
    for crop in crops.values():
        for m in range(12):
            dry, wet = (score_harvest(crop, m, iowa_climate, None, irr) for irr in (False, True))
            if dry and wet:
                assert wet.score >= dry.score - 1e-9


def test_soil_mismatch_lowers_score(crops, iowa_site):
    good, *_ = soil_factor(crops[SOY], iowa_site)
    salty, part, *_ = soil_factor(crops[SOY], {**iowa_site, "sal": "high (>10 dS/m))"})
    assert good == 1.0 and salty < good and part == "salinity"
    no_soil, _, _, gaps = soil_factor(crops[SOY], None)
    assert no_soil == 1.0 and gaps


def test_every_score_is_between_0_and_1(crops, iowa_climate, iowa_site):
    for slots in build_slots(crops, iowa_climate, iowa_site, min_score=0).values():
        for s in slots:
            assert 0 <= s.score <= 1 and s.limiter and s.evidence


def test_tropical_climate_changes_the_winners(crops):
    tropics = Climate([27] * 12, [21] * 12, [150] * 12)
    names = {s.crop.sci for s in best_single_crops(build_slots(crops, tropics), n=40)}
    assert RICE in names and "Secale cereale" not in names
