"""Tests for gui/results.py: reading a recommendation's data for the results page (no window
needed), and one check that the page builds from a real recommendation."""

import tkinter as tk

import pytest

import backend
from gui import results
from gui.theme import Theme
from test_backend import ARGS, offline  # noqa: F401  (the fixture that replaces the web pullers)


def step(year, crop, use, plant, months):
    return {"year": year, "crop": crop, "use": use, "plant": plant, "months": months}


CORN_SOY = {"name": "corn -> soybean", "years": 2, "overall": 0.62,
            "steps": [step(1, "corn", "harvest", "Jun", 4), step(2, "soybean", "harvest", "Jun", 4)]}
WITH_COVER = {"name": "corn -> rye (cover) -> soybean", "years": 2, "overall": 0.755, "strategy": "best match",
              "steps": [step(1, "corn", "harvest", "May", 5), step(1, "rye", "cover", "Oct", 7),
                        step(2, "soybean", "harvest", "May", 5), step(2, "rye", "cover", "Oct", 7)]}
DATA = {"recommended_rotations": [WITH_COVER], "current_rotation": CORN_SOY,
        "field": {"insights": {"annual_rain_mm": 821.0, "frost_free_days": 183.0, "heat_days_per_year": 21.2},
                  "site": {"text_raw": "loam", "ph": 6.2, "dra_raw": "Somewhat poorly drained"},
                  "current_rotation": {"crops": ["Corn", "Soybeans"]}}}


def test_calendar_has_a_row_a_year_and_wraps_past_the_last_december():
    rows = results.calendar(CORN_SOY)
    assert len(rows) == 2 and all(len(row) == 12 for row in rows)
    assert rows[0][5:9] == [("corn", "harvest")] * 4 and rows[0][:5] == [None] * 5
    covered = results.calendar(WITH_COVER)
    assert covered[1][9] == ("rye", "cover") and covered[0][0] == ("rye", "cover")   # year 2's rye runs into year 1
    assert covered[0][4] == ("corn", "harvest")
    assert results.covered_months_per_year(CORN_SOY) == 4 and results.covered_months_per_year(WITH_COVER) == 12


def test_options_are_numbered_and_the_current_rotation_comes_last():
    assert [label for label, _ in results.options(DATA)] == ["Option 1", "What you grow now"]
    assert results.options({"recommended_rotations": [WITH_COVER]})[-1][0] == "Option 1"
    assert results.harvest_names(WITH_COVER) == "corn, then soybean"
    assert results.crop_colours(DATA, ("red", "blue")) == {"corn": "red", "soybean": "blue"}   # covers get none


def test_field_facts_use_everyday_units_and_skip_what_is_missing():
    facts = dict(results.field_facts(DATA))
    assert facts["Rain in a year"] == "821 mm (32 in)" and facts["Frost-free days"] == "183"
    assert facts["Soil"] == "loam, pH 6.2, somewhat poorly drained"
    assert facts["You grow now"] == "corn, then soybeans"
    assert results.field_facts({}) == []


def test_numbers_are_shown_the_way_a_farmer_reads_them():
    assert results.out_of_100(0.755) == 76 and results.out_of_100(None) == 0
    assert results.money(1861.4) == "$1,861" and results.per_acre(2471) == "$1,000"


def test_page_builds_from_a_real_recommendation(offline):  # noqa: F811
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    try:
        view = results.ResultsView(root, Theme())
        view.pack()
        data = backend.recommend(*ARGS, place="Ames, Iowa (zip 50010)").to_dict()
        view.show(data)
        root.update()
        cards = view.body.winfo_children()
        assert len(cards) == 2 + 4 + 1                 # field, side by side, 3 options + current, footer
        view.show({**data, "warnings": ["Check this"], "current_rotation": None})
        root.update()
        assert len(view.body.winfo_children()) == 3 + 3 + 1   # a notes card more, the current rotation gone
        view.show({})                                  # nothing to show must not crash
    finally:
        root.destroy()
