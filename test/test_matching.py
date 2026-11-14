"""Tests for translating field data into EcoCrop terms.

All tests are offline except the last one, which downloads EcoCrop once (then uses the cache).
"""

import pandas as pd
import pytest

from data_pull.ecocrop import load_ecocrop
from matching.field_profile import (
    CDL_TO_ECOCROP, DEP_DEEP, DEP_MEDIUM, DEP_SHALLOW, DRA_EXCESSIVE, DRA_POOR, DRA_WELL,
    SAL_HIGH, SAL_LOW, SAL_MEDIUM, TEXT_HEAVY, TEXT_LIGHT, TEXT_MEDIUM, TEXT_ORGANIC,
    climate_profile, depth_to_ecocrop, drainage_to_ecocrop, frost_free_days,
    salinity_to_ecocrop, texture_to_ecocrop, usda_texture_class,
)


@pytest.mark.parametrize("sand, silt, clay, expected", [
    (92, 4, 4, "sand"),
    (65, 25, 10, "sandy loam"),
    (31, 43, 26, "loam"),          # Nicollet, our test field's soil
    (20, 65, 15, "silt loam"),
    (5, 88, 7, "silt"),
    (21, 47, 32, "clay loam"),     # Webster
    (10, 55, 35, "silty clay loam"),
    (55, 15, 30, "sandy clay loam"),
    (10, 45, 45, "silty clay"),
    (20, 20, 60, "clay"),
])
def test_usda_texture_class(sand, silt, clay, expected):
    assert usda_texture_class(sand, silt, clay) == expected


def test_texture_to_ecocrop():
    assert texture_to_ecocrop(92, 4, 4) == TEXT_LIGHT
    assert texture_to_ecocrop(31, 43, 26, om=6) == TEXT_MEDIUM
    assert texture_to_ecocrop(20, 20, 60) == TEXT_HEAVY
    assert texture_to_ecocrop(31, 43, 26, om=40) == TEXT_ORGANIC


def test_drainage_depth_salinity():
    assert drainage_to_ecocrop("Excessively drained") == DRA_EXCESSIVE
    assert drainage_to_ecocrop("Somewhat poorly drained") == DRA_WELL
    assert drainage_to_ecocrop("Very poorly drained") == DRA_POOR
    assert drainage_to_ecocrop(None) is None
    assert depth_to_ecocrop(35) == DEP_SHALLOW
    assert depth_to_ecocrop(120) == DEP_MEDIUM
    assert depth_to_ecocrop(203) == DEP_DEEP
    assert salinity_to_ecocrop(0.5) == SAL_LOW
    assert salinity_to_ecocrop(6) == SAL_MEDIUM
    assert salinity_to_ecocrop(15) == SAL_HIGH
    assert salinity_to_ecocrop(float("nan")) is None


def _fake_year(year=2021, last_spring_frost="2021-04-20", first_autumn_frost="2021-10-10"):
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    tmin = pd.Series(5.0, index=days)
    tmin[:last_spring_frost] = -2.0
    tmin[first_autumn_frost:] = -2.0
    return tmin


def test_frost_free_days():
    # Apr 21 .. Oct 9 inclusive, no frost
    assert frost_free_days(_fake_year()) == 172
    # A year with no frost at all counts every day
    assert frost_free_days(pd.Series(5.0, index=pd.date_range("2021-01-01", "2021-12-31"))) == 365


def test_climate_profile_shape():
    tmin = pd.concat([_fake_year(2021), _fake_year(2022, "2022-04-20", "2022-10-10")])
    power = pd.DataFrame({"T2M": tmin + 8, "T2M_MIN": tmin, "PRECTOTCORR": 2.0})
    profile = climate_profile(power)
    assert list(profile.index) == ["2021", "2022", "mean_2021_2022"]
    assert profile.loc["2021", "rain_annual_mm"] == 730
    assert profile.loc["2021", "frost_free_days"] == 172
    assert {f"t_mean_m{m:02d}" for m in range(1, 13)} <= set(profile.columns)


def test_every_cdl_mapping_exists_in_ecocrop():
    names = set(load_ecocrop()["scientificname"])
    missing = {cdl: sci for cdl, sci in CDL_TO_ECOCROP.items() if sci not in names}
    assert not missing, f"Not found in EcoCrop: {missing}"
