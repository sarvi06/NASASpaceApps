"""Tests for decision/crops.py against the real EcoCrop table (downloaded once, then saved)."""

import pandas as pd

from decision.crops import CANDIDATES, LEGUME_FAMILY, _family, build_crops, find_crop


def test_every_candidate_loads_from_ecocrop(crops):
    missing = [sci for sci in CANDIDATES if sci not in crops]
    assert not missing, f"Candidates missing or unusable in EcoCrop: {missing}"


def test_legumes_and_families(crops):
    for sci in ("Glycine max", "Medicago sativa", "Vicia villosa ssp. villosa"):
        assert crops[sci].legume and crops[sci].family == LEGUME_FAMILY
    for sci in ("Zea mays ssp. mays", "Secale cereale"):
        assert crops[sci].family == "Poaceae" and not crops[sci].legume
    assert sum(c.legume for c in crops.values()) >= 10


def test_crop_values_are_sane(crops):
    for c in crops.values():
        assert c.tmin <= c.topmn <= c.topmx <= c.tmax, c.sci
        assert 0 < c.gmin <= c.gmax, c.sci
        assert c.can_harvest or c.can_cover, c.sci
        assert 0 <= c.value <= 1


def test_soil_labels_are_read(crops):
    soy = crops["Glycine max"]
    assert "medium" in soy.text_opt and "well (dry spells)" in soy.dra_opt
    assert soy.phopmn == 5.5 and soy.phopmx == 6.5


def test_find_crop_accepts_common_names(crops):
    assert find_crop("Corn", crops).sci == "Zea mays ssp. mays"           # CropScape name
    assert find_crop("maize", crops).sci == "Zea mays ssp. mays"          # alias
    assert find_crop("Soybeans", crops).sci == "Glycine max"
    assert find_crop("hairy vetch", crops).sci == "Vicia villosa ssp. villosa"
    assert find_crop("bananas", crops) is None


def test_family_path_is_cleaned():
    assert _family("Magnoliopsida:Rosidae:Fabales:Leguminosae") == "Fabaceae"
    assert _family("Gramineae") == "Poaceae"
    assert _family(None) == "unknown"


def test_extra_crops_from_history_are_added():
    raw = pd.DataFrame([{"scientificname": "Test plant", "famname": "X:Y:Cruciferae",
                         "comname": ["test"], "tmin": 5, "tmax": 30, "topmn": 15, "topmx": 25,
                         "gmin": 90, "gmax": 120}])
    crops = build_crops(raw, extra=["Test plant"])
    assert crops["Test plant"].family == "Brassicaceae" and crops["Test plant"].name == "test"
