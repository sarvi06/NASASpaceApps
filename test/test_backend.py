"""Offline end-to-end test of backend.recommend(): the pullers are replaced by Iowa-like data."""

import json

import pandas as pd
import pytest

import backend
from conftest import corn_soy_history, fake_power_daily, nicollet_soil


@pytest.fixture
def offline(monkeypatch):
    """Swap the web pullers for fixed data (EcoCrop still comes from the saved table)."""
    monkeypatch.setattr(backend, "get_climate",
                        lambda lat, lon, s, e: fake_power_daily(s.year, e.year))
    monkeypatch.setattr(backend, "get_soil", lambda lat, lon: nicollet_soil())
    monkeypatch.setattr(backend, "get_crop_history",
                        lambda lat, lon, a, b: corn_soy_history(a, b))
    monkeypatch.setattr(backend, "get_soil_moisture",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no login")))


def test_recommend_returns_three_options_and_current_rotation(offline):
    progress = []
    rec = backend.recommend(42.065, -93.73, "2015-01-01", "2024-12-31", on_progress=progress.append)
    assert len(rec.rotations) == 3
    assert rec.baseline is not None and rec.baseline.name == "corn -> soybean"
    assert rec.field.current_rotation["source"] == "USDA CropScape"
    for rot in rec.rotations + [rec.baseline]:
        e = rot.explanation
        assert e["why"] and e["evidence"] and e["benefits"] and e["information_gaps"] and e["risks"]
    assert progress[0].startswith("Downloading NASA POWER") and progress[-1] == "Done."
    text = rec.to_text()
    assert "OPTION 3" in text and "YOUR CURRENT ROTATION" in text and "agronomist" in text
    json.dumps(rec.to_dict())                                    # front-end friendly


def test_priorities_and_user_rotation(offline):
    rec = backend.recommend(42.065, -93.73, "2015-01-01", "2024-12-31",
                            priorities="save_water", current_rotation=["corn", "corn", "soybean"])
    assert rec.priority_name == "save_water"
    assert rec.field.current_rotation["source"] == "entered by you"
    assert rec.baseline.years == 3


def test_smap_failure_is_a_warning_not_a_crash(offline):
    rec = backend.recommend(42.065, -93.73, "2018-01-01", "2024-12-31", use_smap=True)
    assert any("SMAP" in w for w in rec.warnings)


def test_short_period_warns(offline):
    rec = backend.recommend(42.065, -93.73, "2022-01-01", "2023-12-31")
    assert any("years of data" in w for w in rec.warnings)


@pytest.mark.parametrize("kwargs, message", [
    (dict(lat=420), "Latitude"),
    (dict(start_date="2024-01-01", end_date="2023-01-01"), "after"),
    (dict(start_date="2024-01-01", end_date="2024-06-30"), "12 months"),
    (dict(priorities="money"), "priorities"),
    (dict(rotation_years=7), "rotation_years"),
    (dict(current_rotation=["bananas"]), "Unknown crop"),
])
def test_bad_inputs_give_clear_errors(offline, kwargs, message):
    args = dict(lat=42.065, lon=-93.73, start_date="2015-01-01", end_date="2024-12-31") | kwargs
    with pytest.raises(ValueError, match=message):
        backend.recommend(**args)
