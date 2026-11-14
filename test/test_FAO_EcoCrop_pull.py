"""Tests for data_pullers/FAO_EcoCrop_pull.py (downloads once, then uses the saved copy)."""

from data_pullers.FAO_EcoCrop_pull import get_crop_requirements
from decision.field_profile import CDL_TO_ECOCROP


def test_table_has_the_columns_we_use():
    df = get_crop_requirements()
    assert len(df) > 2000
    needed = {"scientificname", "famname", "tmin", "tmax", "topmn", "topmx", "ktmp", "rmin",
              "rmax", "ropmn", "ropmx", "phmin", "phmax", "gmin", "gmax", "text", "textr",
              "dra", "drar", "dep", "depr", "sal", "salr", "fer", "ferr"}
    assert needed <= set(df.columns)


def test_every_cropscape_crop_exists_in_ecocrop():
    names = set(get_crop_requirements()["scientificname"])
    missing = {cdl: sci for cdl, sci in CDL_TO_ECOCROP.items() if sci not in names}
    assert not missing, f"Not found in EcoCrop: {missing}"
