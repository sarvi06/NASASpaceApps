"""Tests for the GUI's tabs: turning what was typed into the right back-end call (no window
needed), the background runner, and one smoke test that builds the real window."""

import threading
import time
import tkinter as tk
from datetime import date

import pytest

import backend
from gui.plots import DEFAULT_PLOTS, MAX_PLOTS, Plot, PlotStore
from gui.runner import Runner
from gui.tabs import TABS, BaseTab, BudgetTab, CropPlantingTab, RotationTab
from gui.tabs.base import NO_LOCATION, common_inputs, default_dates, farm_numbers
from gui.tabs.budget import budget_request
from gui.tabs.crops import crops_request
from gui.tabs.rotation import rotation_request
from gui.theme import Theme

IOWA = Plot("Home field", 12.0, 42.065, -93.73, ("corn", "soybean"))
BARE = Plot("New field", 3.0, 42.065, -93.73)
COMMON = {"lat": 42.065, "lon": -93.73, "start_date": "2015-01-01", "end_date": "2024-12-31"}


# ---- shared inputs ------------------------------------------------------------------------
def test_default_dates_are_the_last_ten_full_years():
    assert default_dates(date(2026, 11, 15)) == ("2016-01-01", "2025-12-31")


def test_common_inputs_come_from_the_plot_and_the_settings_row():
    inputs = common_inputs(IOWA, " 2015-01-01", "2024-12-31 ", "build_soil", "4", True)
    assert inputs == {**COMMON, "priorities": "build_soil", "rotation_years": 4, "irrigated": True,
                      "current_rotation": ["corn", "soybean"]}
    assert "current_rotation" not in common_inputs(BARE, "2015-01-01", "2024-12-31", "balanced", 3)
    with pytest.raises(ValueError, match="whole number of years"):
        common_inputs(IOWA, "2015-01-01", "2024-12-31", "balanced", "three")
    with pytest.raises(ValueError) as error:
        common_inputs(Plot("Plot 2"), "2015-01-01", "2024-12-31", "balanced", 3)
    assert str(error.value) == NO_LOCATION


def test_farm_numbers_reads_the_table_and_skips_blanks():
    rows = [("corn", "180", "", "900"), (" soybean ", "", "3.5", ""), ("", "", "", ""), ("oats", "", "", "")]
    assert farm_numbers(rows) == {"corn": {"price": 180.0, "cost": 900.0}, "soybean": {"yield": 3.5}}
    assert farm_numbers([("corn", "1,250", "", "")]) == {"corn": {"price": 1250.0}}
    assert farm_numbers([("", "", "", "")] * 3) is None
    with pytest.raises(ValueError, match="no crop name"):
        farm_numbers([("", "180", "", "")])
    with pytest.raises(ValueError, match="cost for corn must be a number"):
        farm_numbers([("corn", "", "", "lots")])


# ---- each tab's back-end call ---------------------------------------------------------------
def test_rotation_tab_follows_the_last_crop_when_it_is_known():
    after = rotation_request(IOWA, COMMON, None)
    assert after.call is backend.recommend_after_crop and after.kwargs["last_crop"] == "soybean"
    general = rotation_request(BARE, COMMON, {"corn": {"price": 180}})
    assert general.call is backend.recommend and "last_crop" not in general.kwargs
    assert general.kwargs["farm_numbers"] == {"corn": {"price": 180}}


def test_crop_planting_tab_builds_around_one_or_two_crops():
    request = crops_request(IOWA, " oats, dry bean ", COMMON, None)
    assert request.call is backend.recommend_around_crops
    assert request.kwargs["must_grow"] == ["oats", "dry bean"] and request.kwargs["last_crop"] == "soybean"
    for text in ("", "corn, oats, wheat"):
        with pytest.raises(ValueError, match="one or two crops"):
            crops_request(IOWA, text, COMMON, None)


def test_budget_tab_uses_the_plot_size_and_needs_a_cost():
    costs = {"corn": {"cost": 900.0}}
    request = budget_request(IOWA, "$9,000", COMMON, costs)
    assert request.call is backend.recommend_within_budget
    assert request.kwargs == {**COMMON, "budget_usd": 9000.0, "plot_size_ha": 12.0,
                              "farm_numbers": costs, "previous_crop": "soybean"}
    for text, numbers, message in (("", costs, "number of US dollars"), ("0", costs, "more than 0"),
                                   ("9000", None, "at least one crop costs"),
                                   ("9000", {"corn": {"price": 180}}, "at least one crop costs")):
        with pytest.raises(ValueError, match=message):
            budget_request(IOWA, text, COMMON, numbers)


def test_request_passes_progress_to_the_back_end():
    said = []
    request = rotation_request(BARE, COMMON, None)
    request.call = lambda on_progress, **kwargs: on_progress("working") or kwargs["lat"]
    assert request.run(said.append) == 42.065 and said == ["working"]


def test_tab_list_is_what_a_plot_shows():
    assert TABS == [BudgetTab, CropPlantingTab, RotationTab]
    assert all(issubclass(tab, BaseTab) and tab.title and tab.intro for tab in TABS)


# ---- the background runner ------------------------------------------------------------------
class FakeWidget:
    """Stands in for a tkinter widget: collects after() callbacks to run by hand."""
    def __init__(self):
        self.waiting = []

    def after(self, ms, callback):
        self.waiting.append(callback)

    def turn(self):
        callbacks, self.waiting = self.waiting, []
        for callback in callbacks:
            callback()


def wait_for(runner, widget, seconds=5):
    end = time.time() + seconds
    while runner.busy and time.time() < end:
        widget.turn()
        time.sleep(0.01)


def test_runner_reports_progress_then_the_result_in_the_window_thread():
    widget, events, main = FakeWidget(), [], threading.get_ident()

    def job(report):
        assert threading.get_ident() != main            # the slow work is off the window thread
        report("half way")
        return 42

    runner = Runner(widget)
    note = lambda kind: lambda payload: events.append((kind, payload, threading.get_ident() == main))
    assert runner.start(job, note("progress"), note("done"), note("error"))
    assert not runner.start(job, note("progress"), note("done"), note("error"))    # one at a time
    wait_for(runner, widget)
    assert events == [("progress", "half way", True), ("done", 42, True)] and not runner.busy


def test_runner_hands_errors_back_instead_of_losing_them():
    widget, errors = FakeWidget(), []

    def job(report):
        raise ValueError("bad dates")

    runner = Runner(widget)
    runner.start(job, lambda m: None, lambda r: errors.append("done"), errors.append)
    wait_for(runner, widget)
    assert len(errors) == 1 and str(errors[0]) == "bad dates" and not runner.busy


# ---- the real window --------------------------------------------------------------------------
@pytest.fixture
def window(tmp_path):
    import user_interface
    store = PlotStore(path=tmp_path / "plots.json")
    store.update(0, name="Home field", size_ha=12, lat=42.065, lon=-93.73, last_rotation="corn, soybean")
    try:
        root = user_interface.build(Theme(), store)
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    yield root, store
    root.destroy()


def test_window_opens_plots_shows_every_tab_and_checks_inputs(window, monkeypatch):
    root, store = window
    sidebar = root.sidebar
    assert len(sidebar.buttons.winfo_children()) == DEFAULT_PLOTS
    assert "Home field  (12 ha)" in sidebar.buttons.winfo_children()[0].cget("text")

    for _ in range(MAX_PLOTS - DEFAULT_PLOTS):
        store.add(store.next_name(), 2)
    sidebar.refresh()
    assert len(sidebar.buttons.winfo_children()) == MAX_PLOTS
    assert str(sidebar.add_button.cget("state")) == "disabled"

    root.open_plot(0)
    view = root.content.winfo_children()[0]
    assert [view.notebook.tab(tab, "text") for tab in view.tabs] == ["Budget", "Crop planting", "Rotation"]
    budget, crops, rotation = view.tabs
    assert [row[0].get() for row in budget.number_rows][:2] == ["corn", "soybean"]     # last rotation

    budget.run()                                                    # nothing typed yet
    assert "number of US dollars" in budget.status.cget("text") and not budget.runner.busy
    budget.budget.insert(0, "9000")
    budget.number_rows[0][3].insert(0, "900")
    assert budget.collect().kwargs["budget_usd"] == 9000 and budget.collect().kwargs["plot_size_ha"] == 12
    crops.crops.insert(0, "oats")
    assert crops.collect().kwargs["must_grow"] == ["oats"]
    assert rotation.collect().call is backend.recommend_after_crop

    view.boxes["size_ha"].delete(0, "end")
    view.boxes["size_ha"].insert(0, "20")
    view.save()
    assert store.plots[0].size_ha == 20 and budget.collect().kwargs["plot_size_ha"] == 20
    assert "20 ha" in budget.size_note.cget("text")
    assert "(20 ha)" in sidebar.buttons.winfo_children()[0].cget("text")
    view.boxes["lat"].delete(0, "end")
    view.boxes["lat"].insert(0, "95")
    view.save()
    assert "Latitude must be between" in view.message.cget("text") and store.plots[0].lat == 42.065

    class FakeRecommendation:
        rotations = [1, 2, 3]
        def to_text(self): return "THE REPORT"

    monkeypatch.setattr(backend, "recommend_after_crop", lambda **kwargs: FakeRecommendation())
    rotation.run()
    end = time.time() + 5
    while rotation.runner.busy and time.time() < end:
        root.update()
        time.sleep(0.01)
    assert "3 option(s)" in rotation.status.cget("text")
    assert rotation.results.get("1.0", "end").strip() == "THE REPORT"
    assert str(rotation.run_button.cget("state")) == "normal"

    root.open_plot(1)                                               # a plot with no location yet
    empty = root.content.winfo_children()[0].tabs[2]
    empty.run()
    assert empty.status.cget("text") == NO_LOCATION
