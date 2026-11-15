"""Tests for gui/plots.py: the farmer's plots and saving them (no window needed)."""

import json

import pytest

from gui.plots import DEFAULT_PLOTS, MAX_PLOTS, Plot, PlotStore, parse_crops, parse_size


@pytest.fixture
def store(tmp_path):
    return PlotStore(path=tmp_path / "gui" / "plots.json")


def test_starts_with_five_default_plots(store):
    assert [p.name for p in store.plots] == [f"Plot {n}" for n in range(1, DEFAULT_PLOTS + 1)]
    assert all(p.size_ha == 1.0 and not p.located and p.last_crop is None for p in store.plots)
    assert not store.full and store.next_name() == "Plot 6"


def test_add_plots_up_to_ten_and_no_further(store):
    for n in range(DEFAULT_PLOTS, MAX_PLOTS):
        added = store.add(store.next_name(), "2.5")
        assert added.size_ha == 2.5 and len(store.plots) == n + 1
    assert store.full and len(store.plots) == MAX_PLOTS
    with pytest.raises(ValueError, match="at most 10 plots"):
        store.add("One too many", 1)
    assert len(store.plots) == MAX_PLOTS


@pytest.mark.parametrize("name, size, message", [
    ("North", "big", "number of hectares"),
    ("North", 0, "more than 0"),
    ("North", -3, "more than 0"),
    ("  ", 2, "needs a name"),
    ("plot 2", 2, "already a plot called"),
])
def test_bad_new_plots_are_refused_with_a_plain_message(store, name, size, message):
    with pytest.raises(ValueError, match=message):
        store.add(name, size)
    assert len(store.plots) == DEFAULT_PLOTS


def test_update_takes_what_the_farmer_typed(store):
    plot = store.update(0, name=" Home field ", size_ha="12", lat="42.065", lon="-93.73",
                        last_rotation="corn,  soybean ,")
    assert plot == Plot("Home field", 12.0, 42.065, -93.73, ("corn", "soybean"))
    assert plot.located and plot.last_crop == "soybean"
    cleared = store.update(0, lat="", lon="", last_rotation="")
    assert not cleared.located and cleared.last_rotation == ()


def test_zip_code_and_its_place_name_are_kept_with_the_plot(store):
    plot = store.update(0, zip_code=" 50010-1234 ", place="Ames, Iowa (zip 50010)", lat=42.0379, lon=-93.6003)
    assert plot.zip_code == "50010" and plot.place == "Ames, Iowa (zip 50010)" and plot.located
    assert PlotStore(path=store.path).plots[0] == plot
    no_zip = store.update(0, zip_code="")                       # a place name needs its zip code
    assert no_zip.zip_code == "" and no_zip.place == "" and no_zip.located


@pytest.mark.parametrize("changes, message", [
    (dict(lat="95", lon="10"), "Latitude must be between"),
    (dict(lat="42"), "both latitude and longitude"),
    (dict(lat="north", lon="10"), "must be numbers"),
    (dict(size_ha="lots"), "number of hectares"),
    (dict(zip_code="BA2 7AY"), "five digits"),
    (dict(name="Plot 3"), "already a plot called"),
])
def test_bad_details_change_nothing(store, changes, message):
    before = store.plots[0]
    with pytest.raises(ValueError, match=message):
        store.update(0, **changes)
    assert store.plots[0] == before


def test_plots_are_saved_and_come_back(store):
    store.update(1, size_ha=7, lat=34.75, lon=-91.5, last_rotation=["rice"])
    store.add("Hill field", 3)
    again = PlotStore(path=store.path)
    assert again.plots == store.plots and len(again.plots) == DEFAULT_PLOTS + 1
    assert json.loads(store.path.read_text())[1]["last_rotation"] == ["rice"]


def test_plots_saved_before_zip_codes_still_load(tmp_path):
    path = tmp_path / "plots.json"
    path.write_text(json.dumps([{"name": "Old", "size_ha": 2.0, "lat": 42.0, "lon": -93.0,
                                 "last_rotation": ["corn"]}]))
    assert PlotStore(path=path).plots == [Plot("Old", 2.0, 42.0, -93.0, ("corn",))]


def test_unreadable_save_file_starts_fresh(tmp_path):
    path = tmp_path / "plots.json"
    path.write_text("not json")
    assert len(PlotStore(path=path).plots) == DEFAULT_PLOTS


def test_parsers():
    assert parse_size(" 2.5 ") == 2.5
    assert parse_crops("corn, soybean") == ("corn", "soybean") == parse_crops(["corn", " soybean"])
    assert parse_crops("") == () == parse_crops(None)
