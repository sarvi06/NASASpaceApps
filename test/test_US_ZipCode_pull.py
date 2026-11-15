"""Tests for data_pullers/US_ZipCode_pull.py. Offline ones replace the web request."""

import pytest

from data_pullers import US_ZipCode_pull as zips

AMES = {"zip": "50010", "place": "Ames", "state": "Iowa", "state_code": "IA",
        "lat": 42.0379, "lon": -93.6003}


class Reply:
    def __init__(self, status_code=200, body=None):
        self.status_code, self.body = status_code, body

    def raise_for_status(self): pass

    def json(self): return self.body


def ames_reply():
    return Reply(body={"post code": "50010", "country": "United States", "places": [
        {"place name": "Ames", "longitude": "-93.6003", "latitude": "42.0379",
         "state": "Iowa", "state abbreviation": "IA"}]})


def test_zip_is_looked_up_once_then_read_from_the_saved_copy(tmp_data_dir, monkeypatch):
    asked = []
    monkeypatch.setattr(zips.requests, "get", lambda url, **kwargs: asked.append(url) or ames_reply())
    assert zips.get_zip_location("50010") == AMES
    assert zips.get_zip_location(" 50010-1234 ") == AMES            # zip+4: first five digits
    assert asked == ["https://api.zippopotam.us/us/50010"]
    assert (tmp_data_dir / "zip" / "50010.csv").exists()
    zips.get_zip_location(50010, refresh=True)
    assert len(asked) == 2
    assert zips.describe(AMES) == "Ames, Iowa (zip 50010)"


def test_leading_zero_survives_the_saved_copy(tmp_data_dir, monkeypatch):
    reply = Reply(body={"places": [{"place name": "Agawam", "longitude": "-72.6", "latitude": "42.07",
                                    "state": "Massachusetts", "state abbreviation": "MA"}]})
    monkeypatch.setattr(zips.requests, "get", lambda url, **kwargs: reply)
    assert zips.get_zip_location("01001")["zip"] == "01001"
    assert zips.get_zip_location("01001")["zip"] == "01001"         # second time: from disk


@pytest.mark.parametrize("bad", ["", "5001", "500100", "ABCDE", "BA2 7AY", "50010-12", None])
def test_things_that_are_not_zip_codes_are_refused_before_any_request(bad, monkeypatch):
    monkeypatch.setattr(zips.requests, "get", lambda url, **kwargs: 1 / 0)
    with pytest.raises(ValueError, match="five digits"):
        zips.get_zip_location(bad)


@pytest.mark.parametrize("reply", [Reply(status_code=404), Reply(body={})])
def test_unknown_zip_is_a_clear_error_and_is_not_saved(tmp_data_dir, monkeypatch, reply):
    monkeypatch.setattr(zips.requests, "get", lambda url, **kwargs: reply)
    with pytest.raises(ValueError, match="no US zip code 00000"):
        zips.get_zip_location("00000")
    assert not (tmp_data_dir / "zip" / "00000.csv").exists()


@pytest.mark.live
def test_live_zip_lookup(tmp_data_dir):
    found = zips.get_zip_location("50010")
    assert found["place"] == "Ames" and found["state_code"] == "IA"
    assert 41.5 < found["lat"] < 42.5 and -94.5 < found["lon"] < -93
