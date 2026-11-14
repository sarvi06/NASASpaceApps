"""FAOSTAT: what farmers are paid for each crop and what a hectare yields, country by country.

Call:    get_country(lat, lon, refresh=False)
Output:  {"name": "Japan", "iso2": "JP", "m49": 392}   (m49 = the country code FAOSTAT uses)
Saved:   databases/<lat>_<lon>/country.csv

Call:    get_crop_economics(country, refresh=False)
Inputs:  country       a name, ISO code or M49 number ("Japan", "JP", 392)
Output:  DataFrame, one row per FAOSTAT crop item:
           item                  FAOSTAT's name, e.g. "Maize (corn)"
           yield_t_ha            average yield in that country, tonnes per hectare
           area_ha               average area harvested in that country
           price_usd_t           average price paid to farmers there, US dollars per tonne
           yield_years, price_years   the years averaged, e.g. "2020-2024"
           world_yield_t_ha, world_price_usd_t   median of all countries (for gaps)
         Averages use the latest 5 years that have data. Empty cells = FAOSTAT has no figure.
Saved:   databases/faostat/crop_yields_and_prices.parquet (all countries, last 10 years)

Source: FAOSTAT bulk downloads, https://www.fao.org/faostat/en/#data (QCL and PP domains).
No login needed. The first call downloads about 45 MB, once.
Limits: figures are national averages per year, not local ones, and FAOSTAT holds no seed or
production costs.
"""

import io
import os
import zipfile

import pandas as pd
import pycountry
import requests

from ._common import DATA_DIR, TIMEOUT, cached_csv, location_dir

BULK_URL = "https://bulks-faostat.fao.org/production/{name}.zip"
PRODUCTION = "Production_Crops_Livestock_E_All_Data_(Normalized)"
PRICES = "Prices_E_All_Data_(Normalized)"
CACHE_PATH = DATA_DIR / "faostat" / "crop_yields_and_prices.parquet"

GEOCODER_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "FieldShift-crop-rotation-tool"      # Nominatim asks every client to name itself

YEARS_KEPT = 10        # years saved to disk
YEARS_AVERAGED = 5     # latest years with data that make up an average
FIRST_REGION_CODE = 5000                          # FAOSTAT area codes from here up are regions
TO_TONNES_PER_HA = {"kg/ha": 1e-3, "hg/ha": 1e-4, "100 g/ha": 1e-4, "t/ha": 1.0}
COLUMNS = ["item", "yield_t_ha", "yield_years", "area_ha", "price_usd_t", "price_years",
           "world_yield_t_ha", "world_price_usd_t"]


# --------------------------------------------------------------------------------------
# Which country is this?
# --------------------------------------------------------------------------------------
def find_country(country) -> dict:
    """A name, ISO code or M49 number -> {"name", "iso2", "m49"}."""
    text = f"{country:03d}" if isinstance(country, int) else str(country).strip()
    try:
        found = pycountry.countries.lookup(text)
    except LookupError:
        raise ValueError(f"Unknown country {country!r}; use a name or code such as 'Japan' or 'JP'.") from None
    return {"name": found.name, "iso2": found.alpha_2, "m49": int(found.numeric)}


def get_country(lat: float, lon: float, refresh: bool = False) -> dict:
    """The country a point is in (OpenStreetMap Nominatim lookup, saved per location)."""
    def download() -> pd.DataFrame:
        resp = requests.get(GEOCODER_URL, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT},
                            params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 3})
        resp.raise_for_status()
        code = resp.json().get("address", {}).get("country_code")
        if not code:
            raise ValueError(f"No country found at {lat}, {lon} (is the point at sea?).")
        return pd.DataFrame([find_country(code)])

    row = cached_csv(location_dir(lat, lon) / "country.csv", download, refresh).iloc[0]
    return {"name": str(row["name"]), "iso2": str(row["iso2"]), "m49": int(row["m49"])}


# --------------------------------------------------------------------------------------
# Yields and prices
# --------------------------------------------------------------------------------------
def _read_bulk(name: str, columns: list[str]) -> pd.DataFrame:
    resp = requests.get(BULK_URL.format(name=name), timeout=TIMEOUT)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        with archive.open(f"{name}.csv") as fh:
            df = pd.read_csv(fh, encoding="latin-1", usecols=columns, low_memory=False)
    df = df[df["Area Code"] < FIRST_REGION_CODE]                 # countries only
    df["area_code"] = df["Area Code (M49)"].str.strip("'").astype(int)
    return df.rename(columns={"Item": "item", "Year": "year"})


def _download_table() -> pd.DataFrame:
    """Every country's crop yield, area and farm price for the last YEARS_KEPT years."""
    keys = ["area_code", "item", "year"]
    shared = ["Area Code", "Area Code (M49)", "Item", "Element", "Year", "Unit", "Value"]

    prod = _read_bulk(PRODUCTION, shared)
    prod = prod[prod["year"] > prod["year"].max() - YEARS_KEPT]
    yields = prod[(prod["Element"] == "Yield") & prod["Unit"].isin(list(TO_TONNES_PER_HA))]
    yields = yields.assign(yield_t_ha=yields["Value"] * yields["Unit"].map(TO_TONNES_PER_HA))
    area = prod[(prod["Element"] == "Area harvested") & (prod["Unit"] == "ha")]
    area = area.rename(columns={"Value": "area_ha"})

    prices = _read_bulk(PRICES, shared + ["Months"])
    prices = prices[(prices["Element"] == "Producer Price (USD/tonne)")
                    & (prices["Months"] == "Annual value")
                    & (prices["year"] > prices["year"].max() - YEARS_KEPT)]
    prices = prices.rename(columns={"Value": "price_usd_t"})

    table = yields[keys + ["yield_t_ha"]].merge(area[keys + ["area_ha"]], on=keys, how="left")
    table = table.merge(prices[keys + ["price_usd_t"]], on=keys, how="outer")
    if table.empty or table["yield_t_ha"].notna().sum() == 0:
        raise RuntimeError("The FAOSTAT download held no crop yields; its format may have changed.")
    return table.sort_values(keys).reset_index(drop=True)


def _load_table(refresh: bool = False) -> pd.DataFrame:
    if refresh or not CACHE_PATH.exists():
        table = _download_table()
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_name(CACHE_PATH.name + ".part")
        table.to_parquet(tmp, index=False)
        os.replace(tmp, CACHE_PATH)                 # only a complete file replaces the saved copy
    return pd.read_parquet(CACHE_PATH)


def _recent_mean(table: pd.DataFrame, column: str, by: list[str]) -> pd.DataFrame:
    """Mean of `column` over each group's latest YEARS_AVERAGED years that have a value."""
    known = table.dropna(subset=[column]).sort_values("year").groupby(by).tail(YEARS_AVERAGED)
    return known.groupby(by).agg(value=(column, "mean"), first=("year", "min"), last=("year", "max"))


def summarise(table: pd.DataFrame, m49: int) -> pd.DataFrame:
    """The saved all-countries table -> one row per crop item for one country (see module docs)."""
    local = table[table["area_code"] == m49]
    out = pd.DataFrame(index=pd.Index(sorted(table["item"].unique()), name="item"))
    for column in ("yield_t_ha", "area_ha", "price_usd_t"):
        mean = _recent_mean(local, column, ["item"])
        out[column] = mean["value"]
        if column != "area_ha":
            years = mean["first"].astype(str) + "-" + mean["last"].astype(str)
            out[column.split("_")[0] + "_years"] = years
            world = _recent_mean(table, column, ["area_code", "item"])["value"]
            out["world_" + column] = world.groupby("item").median()
    return out.reset_index()[COLUMNS]


def get_crop_economics(country, refresh: bool = False) -> pd.DataFrame:
    """Average yield and farm price of every FAOSTAT crop item in one country."""
    found = find_country(country)
    out = summarise(_load_table(refresh), found["m49"])
    out.attrs["country"] = found["name"]
    return out
