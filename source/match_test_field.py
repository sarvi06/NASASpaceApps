"""Translate the test field's data into EcoCrop terms and show it next to its crops' rows.

Run from the repo root (pulls the data first if it isn't cached yet):
    .venv\\Scripts\\python.exe source\\match_test_field.py
"""

import json

import pandas as pd

import pull_test_field
from data_pull.config import DATA_DIR, TEST_FIELD
from data_pull.ecocrop import load_ecocrop
from matching.field_profile import climate_profile, crop_history_to_ecocrop, site_profile

GROWING_MONTHS = ["m05", "m06", "m07", "m08", "m09"]  # May-Sep, the local corn/soy season


def _fmt(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return "-"
    if hasattr(value, "__len__") and not isinstance(value, str):
        return ", ".join(str(v) for v in value) or "-"
    return str(value)


def _range(lo, hi) -> str:
    return f"{_fmt(lo)} to {_fmt(hi)}"


def side_by_side(climate: pd.Series, site: dict, crops: pd.DataFrame) -> pd.DataFrame:
    """One row per EcoCrop variable: our field's value, then each crop's optimal | absolute range."""
    season = [climate[f"t_mean_{m}"] for m in GROWING_MONTHS]
    rows = {
        "Temperature, degC (field: May-Sep monthly means)":
            (f"{min(season):.1f} to {max(season):.1f}",
             lambda c: f"{_range(c.topmn, c.topmx)} | {_range(c.tmin, c.tmax)}"),
        "Killing temp, degC (field: coldest daily min)":
            (f"{climate['t_min_abs']:.1f}", lambda c: _fmt(c.ktmp)),
        "Annual rainfall, mm":
            (f"{climate['rain_annual_mm']:.0f}",
             lambda c: f"{_range(c.ropmn, c.ropmx)} | {_range(c.rmin, c.rmax)}"),
        "Season length, days (field: frost-free days)":
            (f"{climate['frost_free_days']:.0f}", lambda c: _range(c.gmin, c.gmax)),
        "Soil pH":
            (_fmt(site["ph"]), lambda c: f"{_range(c.phopmn, c.phopmx)} | {_range(c.phmin, c.phmax)}"),
        "Latitude":
            (_fmt(site["lat"]), lambda c: f"{_range(c.latopmn, c.latopmx)} | {_range(c.latmn, c.latmx)}"),
        "Max altitude, m":
            (f"{site['alt_m']:.0f}", lambda c: _fmt(c.altmx)),
        "Texture":
            (f"{site['text']} ({site['text_raw']})", lambda c: f"{_fmt(c.text)} | {_fmt(c.textr)}"),
        "Drainage":
            (f"{site['dra']} ({site['dra_raw']})", lambda c: f"{_fmt(c.dra)} | {_fmt(c.drar)}"),
        "Soil depth":
            (f"{site['dep']} ({_fmt(site['dep_raw_cm'])} cm)", lambda c: f"{_fmt(c.dep)} | {_fmt(c.depr)}"),
        "Salinity":
            (f"{site['sal']} ({_fmt(site['sal_raw_dsm'])} dS/m)", lambda c: f"{_fmt(c.sal)} | {_fmt(c.salr)}"),
        "Fertility (field: approx. from organic matter)":
            (f"{site['fer']} ({_fmt(site['fer_raw_om_pct'])}% OM)", lambda c: f"{_fmt(c.fer)} | {_fmt(c.ferr)}"),
    }
    table = {"field": {k: v[0] for k, v in rows.items()}}
    for crop in crops.itertuples():
        table[f"{crop.scientificname}  (optimal | absolute)"] = {k: v[1](crop) for k, v in rows.items()}
    return pd.DataFrame(table)


def main() -> None:
    field = TEST_FIELD
    field_dir = DATA_DIR / field.name
    soil_path = field_dir / "ssurgo_soil.csv"
    needs_pull = not (field_dir / "field_info.json").exists() or (
        soil_path.exists() and "ec_r" not in pd.read_csv(soil_path, nrows=0).columns)
    if needs_pull:
        print("Cached data missing or out of date - pulling it first.\n")
        pull_test_field.main()
        print()

    info = json.loads((field_dir / "field_info.json").read_text())
    power = pd.read_csv(field_dir / "power_daily.csv", index_col="date", parse_dates=True)
    soil = pd.read_csv(soil_path)
    cdl = pd.read_csv(field_dir / "cdl_history.csv")
    ecocrop = load_ecocrop()

    climate = climate_profile(power)
    site = site_profile(soil, info["lat"], info["lon"], info["elevation_m"])
    history = crop_history_to_ecocrop(cdl, ecocrop)

    climate.to_csv(field_dir / "field_profile_climate.csv")
    pd.DataFrame([site]).to_csv(field_dir / "field_profile_site.csv", index=False)
    history.to_csv(field_dir / "cdl_history_ecocrop.csv", index=False)

    pd.set_option("display.width", 200, "display.max_columns", 30, "display.max_colwidth", 60)
    print(f"Field: {field.name} ({field.lat}, {field.lon}), elevation {info['elevation_m']} m\n")

    print("CLIMATE PROFILE (per year, last row = multi-year mean)")
    print(climate[["t_min_abs", "rain_annual_mm", "frost_free_days"]
                  + [f"t_mean_{m}" for m in GROWING_MONTHS]].to_string(), "\n")

    print("CROP HISTORY -> ECOCROP")
    print(history[["year", "crop", "scientificname", "in_ecocrop"]].to_string(index=False), "\n")

    grown = history.loc[history["in_ecocrop"], "scientificname"].unique()
    crops = ecocrop[ecocrop["scientificname"].isin(grown)]
    print("FIELD (multi-year mean) vs ECOCROP ROWS FOR THE CROPS GROWN HERE")
    print(side_by_side(climate.iloc[-1], site, crops).to_string(), "\n")

    print(f"Saved field_profile_climate.csv, field_profile_site.csv, cdl_history_ecocrop.csv to {field_dir}")


if __name__ == "__main__":
    main()
