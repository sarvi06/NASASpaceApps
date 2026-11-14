"""Tests for decision/crops.py against the real EcoCrop table (downloaded once, then saved)."""

import pandas as pd

from decision.crops import (LEGUME_FAMILY, _family, build_crops, crop_roles, find_crop,
                            is_rotation_crop)
from decision.field_profile import CDL_TO_ECOCROP


def row(cat, lifo=("herb",), lispa=("annual",)):
    return {"cat": list(cat), "lifo": list(lifo), "lispa": list(lispa)}


def test_filter_removes_trees_ornamentals_and_medicinals():
    assert is_rotation_crop(row(["cereals & pseudocereals"], ["grass"]))
    assert is_rotation_crop(row(["vegetables", "medicinals & aromatic"]))       # also a food crop
    assert not is_rotation_crop(row(["fruits & nuts"], ["tree"], ["perennial"]))
    assert not is_rotation_crop(row(["forest/wood", "environmental"], ["shrub", "tree"]))
    assert not is_rotation_crop(row(["ornamentals/turf"]))
    assert not is_rotation_crop(row(["medicinals & aromatic", "weed"]))


def test_filter_keeps_only_perennials_that_fit_a_rotation():
    assert is_rotation_crop(row(["forage/pasture"], lispa=["perennial"]))        # e.g. alfalfa
    assert is_rotation_crop(row(["roots/tubers"], ["shrub"], ["perennial"]))     # e.g. cassava
    assert not is_rotation_crop(row(["fruits & nuts"], lispa=["perennial"]))     # e.g. strawberry
    assert not is_rotation_crop(row(["materials"], ["shrub"], ["perennial"]))    # e.g. tea
    assert is_rotation_crop(row(["materials"], ["shrub"], ["annual", "perennial"]))   # e.g. cotton


def test_plants_without_a_category_need_a_market():
    assert not is_rotation_crop(row([], [], []))
    assert is_rotation_crop(row([], [], []), sold=True)                           # e.g. sugarcane


def test_roles_come_from_ecocrop_categories():
    assert crop_roles(row(["cereals & pseudocereals", "forage/pasture", "cover crop"])) == {"cash", "forage", "cover"}
    assert crop_roles(row(["environmental"])) == frozenset()
    assert crop_roles(row([]), sold=True) == {"cash"}


def test_real_list_is_wide_and_has_no_trees(crops):
    assert len(crops) > 300
    for name in ("larch", "tea", "apple", "rose", "opium poppy"):
        assert find_crop(name, crops) is None, name
    for name in ("corn", "rice", "soybean", "potato", "rye", "hairy vetch", "alfalfa", "tomato",
                 "sweet potato", "sugarcane", "okra"):
        assert find_crop(name, crops) is not None, name
    assert len({c.name.lower() for c in crops.values()}) == len(crops)           # one crop per name
    assert all(sci in crops for sci in CDL_TO_ECOCROP.values())


def test_legumes_and_families(crops):
    for sci in ("Glycine max", "Medicago sativa", "Vicia villosa ssp. villosa"):
        assert crops[sci].legume and crops[sci].family == LEGUME_FAMILY
    for sci in ("Zea mays ssp. mays", "Secale cereale"):
        assert crops[sci].family == "Poaceae" and not crops[sci].legume
    assert sum(c.legume for c in crops.values()) >= 10


def test_roles_and_hardiness_of_known_crops(crops):
    assert crops["Secale cereale"].can_cover and crops["Secale cereale"].can_harvest
    assert crops["Secale cereale"].hardy_to <= -15                 # overwinters
    assert crops["Zea mays ssp. mays"].hardy_to is None            # does not
    assert not crops["Zea mays ssp. mays"].can_cover
    assert sum(c.can_cover for c in crops.values()) >= 20


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
    assert find_crop("soya bean", crops).sci == "Glycine max"             # EcoCrop common name
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
    assert build_crops(raw) == {}                                         # no category: filtered out
    crops = build_crops(raw, extra=["Test plant"])
    assert crops["Test plant"].family == "Brassicaceae" and crops["Test plant"].name == "test"
