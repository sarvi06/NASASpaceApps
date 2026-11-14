"""Quick offline test demo for ecocrop_loader.py and crop_rotation.py.

No network, no real EcoCrop download: everything uses small synthetic data.

Run either way (same folder as the two modules):
    python test_demo.py
    pytest -q test_demo.py
"""
from __future__ import annotations

import traceback

import numpy as np
import pandas as pd

import crop_rotation as cr
import ecocroploader as el


# ==========================================================================
# Synthetic data
# ==========================================================================
def make_raw() -> pd.DataFrame:
    """A small, deliberately messy EcoCrop-like table (uppercase column names,
    list cells, numpy arrays, a duplicate species, a sentinel, a bad row)."""
    #        sci name            common      family          cat       tmin tmax topmn topmx ktmp rmin rmax ropmn ropmx gmin gmax
    rows = [
        ("Triticum aestivum",  ["wheat"],   "Poaceae",      "cereals", 3, 32, 12, 22, -10, 250, 1750, 450, 900, 90, 180),
        ("Hordeum vulgare",    ["barley"],  "Poaceae",      "cereals", 3, 30, 12, 22,  -8, 250, 2000, 400, 800, 90, 150),
        ("Pisum sativum",      ["pea"],     "Leguminosae",  "legumes", 4, 28, 13, 18,  -5, 300, 2000, 500, 1000, 60, 100),
        ("Vicia faba",         ["faba"],    "Fabaceae",     "legumes", 4, 28, 10, 18,  -8, 400, 2000, 600, 1200, 100, 160),
        ("Brassica napus",     ["rape"],    "Brassicaceae", "oil",     5, 30, 10, 20, -12, 300, 2000, 500, 1000, 120, 200),
        ("Solanum tuberosum",  ["potato"],  "Solanaceae",   "roots",   7, 25, 10, 15,   0, 400, 2000, 600, 1200, 90, 150),
        ("Zea mays",           ["maize"],   "Poaceae",      "cereals", 10, 35, 18, 25,  2, 400, 2500, 600, 1200, 90, 140),
        ("Oryza sativa",       ["rice", "paddy rice"], "Poaceae", "cereals", 15, 35, 20, 25, 5, 1000, 3000, 1500, 2000, 100, 150),
        ("Oryza sativa ",      ["rice"],    "Poaceae",      "cereals", 15, 35, None, None, 5, 1000, 3000, 1500, 2000, 100, 150),  # duplicate, less complete
        ("Bad crop",           [],          "Foo",          "x",       30, 5, 20, 25, -9999, 100, 200, 150, 180, 0, 5),           # inverted + sentinel
    ]
    cols = ["SCIENTIFIC_NAME", "COMNAME", "FAMILY", "CATEGORY", "TMIN", "TMAX", "TOPMN",
            "TOPMX", "KTMP", "RMIN", "RMAX", "ROPMN", "ROPMX", "GMIN", "GMAX"]
    df = pd.DataFrame(rows, columns=cols)
    df["COMNAME"] = df["COMNAME"].map(np.array)          # parquet gives arrays, not lists
    df["TEXT"] = [np.array(["light", "medium"])] + [np.array(["medium"])] * 9
    return df


BRISTOL = cr.Climate(
    tmean=[5, 5.5, 7.5, 9.5, 12.5, 15.5, 17.5, 17, 14.5, 11.5, 8, 5.5],
    tmin_ext=[-4, -4, -3, -1, 2, 5, 8, 7, 4, 0, -2, -4],
    precip=[85, 65, 60, 55, 60, 60, 55, 65, 65, 90, 95, 95])

TROPICS = cr.Climate(
    tmean=[27, 27.5, 28, 28.5, 28, 27, 26.5, 26.5, 27, 27.5, 27, 26.5],
    tmin_ext=[21, 21, 22, 23, 23, 22, 22, 22, 22, 22, 22, 21],
    precip=[30, 40, 60, 120, 250, 330, 360, 350, 300, 160, 60, 30])


def crops_for(clim_irrigated=True):
    clean = el.prepare(make_raw(), verbose=False)
    return cr.build_crops(make_raw(), max_cycle_days=300)


def rotations(clim, irrigated=True, years=3, min_suit=0.4, **kw):
    crops = crops_for()
    slots = cr.build_slots(crops, clim, irrigated, None, "annualised",
                           min_suit, per_start=8, per_family=2)
    return cr.search_rotations(slots, years, kw.get("turnaround", 1),
                               kw.get("max_idle", 11), 200), slots


# ==========================================================================
# Loader tests
# ==========================================================================
def test_numpy_array_cells_do_not_crash():
    clean = el.prepare(make_raw(), verbose=False)
    row = clean[clean["scientific_name"] == "Oryza sativa"].iloc[0]
    assert row["common_name"] == "rice"
    assert row["common_names"] == "rice|paddy rice"
    wheat = clean[clean["scientific_name"] == "Triticum aestivum"].iloc[0]
    assert wheat["texture"] == "light|medium"        # all values kept


def test_columns_match_case_and_separator_insensitively():
    resolved = el.resolve_columns(pd.DataFrame(columns=["PH_MIN", "ph max", "Tmin"]))
    assert resolved == {"ph_min": "PH_MIN", "ph_max": "ph max", "tmin": "Tmin"}


def test_sentinels_become_missing_and_missing_is_not_invented():
    clean = el.prepare(make_raw(), verbose=False)
    bad = clean[clean["scientific_name"] == "Bad crop"].iloc[0]
    assert pd.isna(bad["ktmp"])                      # -9999 -> NaN
    assert pd.isna(clean["drainage"]).all() if "drainage" in clean else True


def test_duplicates_collapse_keeping_most_complete():
    clean = el.prepare(make_raw(), verbose=False)
    rice = clean[clean["scientific_name"].str.strip() == "Oryza sativa"]
    assert len(rice) == 1
    assert rice.iloc[0]["topmn"] == 20               # the complete record won


def test_quality_flags():
    clean = el.prepare(make_raw(), verbose=False).set_index("scientific_name")
    assert not clean.loc["Bad crop", "core_complete"]
    assert "order:tmin" in clean.loc["Bad crop", "qc_issues"]
    assert clean.loc["Triticum aestivum", "core_complete"]
    assert pd.isna(clean.loc["Triticum aestivum", "qc_issues"])


def test_filtering():
    clean = el.prepare(make_raw(), verbose=False)
    assert list(el.filter_crops(clean, names=["paddy"])["scientific_name"]) == ["Oryza sativa"]
    assert "Bad crop" not in set(el.filter_crops(clean, only_complete=True)["scientific_name"])


def test_missing_family_does_not_collapse_into_one_family():
    raw = make_raw()
    raw["FAMILY"] = None                              # every family missing
    fams = [c.family for c in cr.build_crops(raw, 300)]
    assert "nan" not in fams and "None" not in fams
    assert len(set(fams)) == len(fams)                # each crop is its own family


# ==========================================================================
# Suitability tests
# ==========================================================================
def test_trapezoid_shape():
    t = cr.trapezoid
    assert t(5, 0, 10, 20, 30) == 0.5                # ramp up
    assert t(15, 0, 10, 20, 30) == 1.0               # optimum
    assert t(25, 0, 10, 20, 30) == 0.5               # ramp down
    assert t(-1, 0, 10, 20, 30) == 0.0 and t(31, 0, 10, 20, 30) == 0.0
    assert t(7, None, None, None, None) == 1.0       # no constraint


def test_scores_are_between_0_and_1():
    for clim in (BRISTOL, TROPICS):
        for c in crops_for():
            for m in range(12):
                s = cr.score_slot(c, m, clim, False, 6.5, "annualised").score
                assert 0.0 <= s <= 1.0


def test_irrigation_never_lowers_score():
    for c in crops_for():
        for m in range(12):
            wet = cr.score_slot(c, m, BRISTOL, False, None, "annualised").score
            irr = cr.score_slot(c, m, BRISTOL, True, None, "annualised").score
            assert irr >= wet


def test_climate_decides_what_is_viable():
    temperate = {s.crop.sci for v in cr.build_slots(crops_for(), BRISTOL, True, None,
                 "annualised", 0.4, 8, 2).values() for s in v}
    tropical = {s.crop.sci for v in cr.build_slots(crops_for(), TROPICS, True, None,
                "annualised", 0.4, 8, 2).values() for s in v}
    assert "Oryza sativa" not in temperate           # too cold for rice in Bristol
    assert "Oryza sativa" in tropical
    assert "Triticum aestivum" in temperate


def test_raising_min_suit_never_adds_options():
    crops = crops_for()
    n = lambda ms: sum(len(v) for v in cr.build_slots(
        crops, BRISTOL, True, None, "annualised", ms, 99, 99).values())
    assert n(0.2) >= n(0.5) >= n(0.9)


# ==========================================================================
# Rotation invariants
# ==========================================================================
def _check_rotation(r, turnaround):
    H = r.horizon
    placed = r.placed
    assert len(placed) >= 2
    for (a1, s1), (a2, s2) in zip(placed, placed[1:]):
        assert a2 >= a1 + s1.months + turnaround, "overlap / no turnaround"
        assert s1.crop.family != s2.crop.family, "same family back to back"
    (a0, f), (aN, l) = placed[0], placed[-1]
    assert a0 + H >= aN + l.months + turnaround, "last crop runs into the next cycle"
    assert f.crop.family != l.crop.family, "same family across the wrap"
    assert 0 < r.utilisation <= 1.0
    assert all(0.0 <= s.score <= 1.0 for _, s in placed)


def test_rotation_invariants_hold():
    for clim in (BRISTOL, TROPICS):
        for years in (1, 2, 3):
            rots, _ = rotations(clim, years=years)
            for r in rots[:50]:
                _check_rotation(r, turnaround=1)


def test_search_finds_a_rotation_with_a_legume():
    rots, _ = rotations(BRISTOL, years=3)
    assert rots, "expected at least one rotation"
    assert any(s.crop.is_legume for _, s in rots[0].placed)


def test_results_sorted_and_deduplicated():
    rots, _ = rotations(BRISTOL, years=3)
    assert [r.score for r in rots] == sorted((r.score for r in rots), reverse=True)
    assert len({r.canonical() for r in rots}) == len(rots)


def test_impossible_climate_gives_no_rotation():
    arctic = cr.Climate([-20] * 12, [-30] * 12, [20] * 12)
    rots, slots = rotations(arctic)
    assert not rots and sum(len(v) for v in slots.values()) == 0


# ==========================================================================
# Tiny runner (so it works without pytest)
# ==========================================================================
def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception:
            failed += 1
            print(f"  FAIL  {name}")
            print("        " + traceback.format_exc().strip().replace("\n", "\n        "))
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())