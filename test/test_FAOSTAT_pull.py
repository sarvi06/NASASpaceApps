"""Tests for data_pullers/FAOSTAT_pull.py. Offline ones use small made-up tables."""

import pandas as pd
import pytest

from data_pullers import FAOSTAT_pull as fao

JAPAN, USA, KENYA = 392, 840, 404


def raw(area, item, element, year, value, unit, months="Annual value"):
    return {"area_code": area, "item": item, "Element": element, "year": year, "Value": value,
            "Unit": unit, "Months": months}


def test_find_country_accepts_names_and_codes():
    assert fao.find_country("Japan") == {"name": "Japan", "iso2": "JP", "m49": JAPAN}
    assert fao.find_country("jp")["m49"] == JAPAN and fao.find_country(JAPAN)["iso2"] == "JP"
    assert fao.find_country(4)["name"] == "Afghanistan"              # M49 004
    with pytest.raises(ValueError, match="Unknown country"):
        fao.find_country("Atlantis")


def test_get_country_looks_up_once_then_uses_the_saved_copy(tmp_data_dir, monkeypatch):
    calls = []

    class Reply:
        def raise_for_status(self): pass
        def json(self): return {"address": {"country_code": "jp", "country": "Japan"}}

    def fake_get(url, **kwargs):
        calls.append(kwargs)
        return Reply()

    monkeypatch.setattr(fao.requests, "get", fake_get)
    assert fao.get_country(32.617, 130.629) == {"name": "Japan", "iso2": "JP", "m49": JAPAN}
    assert fao.get_country(32.617, 130.629)["m49"] == JAPAN
    assert len(calls) == 1 and calls[0]["headers"]["User-Agent"]


def test_point_at_sea_is_a_clear_error(tmp_data_dir, monkeypatch):
    class Reply:
        def raise_for_status(self): pass
        def json(self): return {"error": "Unable to geocode"}

    monkeypatch.setattr(fao.requests, "get", lambda url, **kwargs: Reply())
    with pytest.raises(ValueError, match="No country"):
        fao.get_country(0.0, -30.0)


def test_download_table_converts_units_and_keeps_recent_annual_values(monkeypatch):
    production = pd.DataFrame([
        raw(JAPAN, "Rice", "Yield", 2024, 7000, "kg/ha"),
        raw(JAPAN, "Rice", "Yield", 2023, 68000, "hg/ha"),            # older unit, same scale
        raw(JAPAN, "Rice", "Yield", 2000, 5000, "kg/ha"),             # too old
        raw(JAPAN, "Rice", "Area harvested", 2024, 1_500_000, "ha"),
        raw(JAPAN, "Rice", "Production", 2024, 10_000_000, "t"),      # not used
        raw(JAPAN, "Hen eggs", "Yield", 2024, 300, "No/An"),          # not a crop yield
    ])
    prices = pd.DataFrame([
        raw(JAPAN, "Rice", "Producer Price (USD/tonne)", 2024, 1800, "USD"),
        raw(JAPAN, "Rice", "Producer Price (USD/tonne)", 2024, 1900, "USD", months="January"),
        raw(JAPAN, "Rice", "Producer Price (LCU/tonne)", 2024, 250000, "LCU"),
    ])
    monkeypatch.setattr(fao, "_read_bulk", lambda name, columns: production if name == fao.PRODUCTION else prices)
    table = fao._download_table()
    assert list(table["year"]) == [2023, 2024] and set(table["item"]) == {"Rice"}
    latest = table.iloc[-1]
    assert latest["yield_t_ha"] == 7.0 and latest["area_ha"] == 1_500_000 and latest["price_usd_t"] == 1800
    assert table.iloc[0]["yield_t_ha"] == pytest.approx(6.8)


def test_download_with_no_yields_is_an_error(monkeypatch):
    empty = pd.DataFrame([raw(JAPAN, "Rice", "Production", 2024, 1, "t")])
    monkeypatch.setattr(fao, "_read_bulk", lambda name, columns: empty)
    with pytest.raises(RuntimeError, match="no crop yields"):
        fao._download_table()


def table_of(rows):
    return pd.DataFrame(rows, columns=["area_code", "item", "year", "yield_t_ha", "area_ha", "price_usd_t"])


def test_summarise_averages_the_latest_five_years_with_data():
    rows = [(JAPAN, "Rice", y, float(y - 2010), 100.0, 1000.0 if y < 2023 else None)
            for y in range(2015, 2025)]
    rows += [(USA, "Rice", 2024, 8.0, 50.0, 300.0), (KENYA, "Rice", 2024, 2.0, 10.0, 500.0),
             (USA, "Okra", 2024, 9.0, 5.0, 700.0)]
    out = fao.summarise(table_of(rows), JAPAN).set_index("item")
    rice = out.loc["Rice"]
    assert rice["yield_t_ha"] == pytest.approx(12.0) and rice["yield_years"] == "2020-2024"
    assert rice["price_usd_t"] == 1000.0 and rice["price_years"] == "2018-2022"   # skips the gaps
    assert rice["world_yield_t_ha"] == 8.0 and rice["world_price_usd_t"] == 500.0  # medians
    okra = out.loc["Okra"]                                           # not grown in Japan
    assert pd.isna(okra["yield_t_ha"]) and okra["world_yield_t_ha"] == 9.0
    assert list(out.reset_index().columns) == fao.COLUMNS


def test_get_crop_economics_reads_the_saved_table(tmp_path, monkeypatch):
    monkeypatch.setattr(fao, "CACHE_PATH", tmp_path / "faostat" / "table.parquet")
    downloads = []

    def fake_download():
        downloads.append(1)
        return table_of([(JAPAN, "Rice", 2024, 7.0, 100.0, 1800.0)])

    monkeypatch.setattr(fao, "_download_table", fake_download)
    first = fao.get_crop_economics("Japan")
    again = fao.get_crop_economics(JAPAN)
    assert len(downloads) == 1 and first.attrs["country"] == "Japan"
    assert again.set_index("item").loc["Rice", "price_usd_t"] == 1800.0
    fao.get_crop_economics("JP", refresh=True)
    assert len(downloads) == 2


@pytest.mark.live
def test_live_faostat_has_us_maize():
    df = fao.get_crop_economics("United States").set_index("item")
    maize = df.loc["Maize (corn)"]
    assert 7 < maize["yield_t_ha"] < 15 and 80 < maize["price_usd_t"] < 500


@pytest.mark.live
def test_live_country_lookup(tmp_data_dir):
    assert fao.get_country(42.065, -93.73)["iso2"] == "US"
