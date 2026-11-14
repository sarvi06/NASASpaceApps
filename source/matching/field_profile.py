"""Translate our three data outputs into EcoCrop's variables, units and labels.

  NASA POWER daily climate -> climate_profile()          monthly temps, annual rain, frost-free days
  SSURGO soil + location   -> site_profile()             pH, texture/drainage/depth/salinity/fertility
  CropScape crop history   -> crop_history_to_ecocrop()  crop names -> EcoCrop scientific names

Nothing here judges whether a crop suits the field. That comparison is a later step.
Every label below is copied exactly from the EcoCrop table, so a field value can be
checked directly against a crop's columns (e.g. site["dra"] in crop["drar"]).
"""

import math

import pandas as pd

# --------------------------------------------------------------------------------------
# EcoCrop's category labels (exact strings, typos included)
# --------------------------------------------------------------------------------------
TEXT_LIGHT, TEXT_MEDIUM, TEXT_HEAVY, TEXT_ORGANIC = "light", "medium", "heavy", "organic"

DRA_POOR = "poorly (saturated >50% of year)"
DRA_WELL = "well (dry spells)"
DRA_EXCESSIVE = "excessive (dry/moderately dry)"

DEP_VERY_SHALLOW = "very shallow (<20 cm)"
DEP_SHALLOW = "shallow (20-50 cm)"
DEP_MEDIUM = "medium (50-150 cm)"
DEP_DEEP = "deep (>>150 cm)"

SAL_LOW = "low (<4 dS/m)"
SAL_MEDIUM = "medium (4-10 dS/m)"
SAL_HIGH = "high (>10 dS/m))"  # sic: EcoCrop's label has a double closing bracket

FER_LOW, FER_MODERATE, FER_HIGH = "low", "moderate", "high"

# --------------------------------------------------------------------------------------
# Lookup tables: our sources' wording -> EcoCrop's wording
# --------------------------------------------------------------------------------------

# USDA texture class -> EcoCrop texture. Light = sandy, medium = loamy/silty,
# heavy = clayey (>= ~35-40% clay). Organic soils are caught separately by organic matter.
USDA_TEXTURE_TO_ECOCROP = {
    "sand": TEXT_LIGHT,
    "loamy sand": TEXT_LIGHT,
    "sandy loam": TEXT_LIGHT,
    "loam": TEXT_MEDIUM,
    "silt loam": TEXT_MEDIUM,
    "silt": TEXT_MEDIUM,
    "sandy clay loam": TEXT_MEDIUM,
    "clay loam": TEXT_MEDIUM,
    "silty clay loam": TEXT_MEDIUM,
    "sandy clay": TEXT_HEAVY,
    "silty clay": TEXT_HEAVY,
    "clay": TEXT_HEAVY,
}
ORGANIC_SOIL_OM_PCT = 20  # topsoil organic matter at/above this % counts as an organic soil

# SSURGO drainage class -> EcoCrop drainage.
# EcoCrop's "poorly" means saturated for over half the year. A "somewhat poorly drained"
# soil is only wet for short periods (and Midwest fields like this are usually
# tile-drained), so it maps to "well". Raw class is kept alongside for local review.
SSURGO_DRAINAGE_TO_ECOCROP = {
    "Excessively drained": DRA_EXCESSIVE,
    "Somewhat excessively drained": DRA_EXCESSIVE,
    "Well drained": DRA_WELL,
    "Moderately well drained": DRA_WELL,
    "Somewhat poorly drained": DRA_WELL,
    "Poorly drained": DRA_POOR,
    "Very poorly drained": DRA_POOR,
}

# CropScape (CDL) crop name -> EcoCrop scientific name. Non-crop classes
# (e.g. "Grass/Pasture", "Fallow/Idle Cropland", "Developed/Open Space") have no match.
CDL_TO_ECOCROP = {
    "Corn": "Zea mays ssp. mays",  # plain "Zea mays" row is missing several columns
    "Sweet Corn": "Zea mays ssp. saccharata",
    "Soybeans": "Glycine max",
    "Winter Wheat": "Triticum aestivum",
    "Spring Wheat": "Triticum aestivum",
    "Alfalfa": "Medicago sativa",
    "Oats": "Avena sativa",
    "Barley": "Hordeum vulgare",
    "Rye": "Secale cereale",
    "Sorghum": "Sorghum bicolor",
    "Sunflower": "Helianthus annuus",
    "Canola": "Brassica napus",
    "Dry Beans": "Phaseolus vulgaris",
    "Peas": "Pisum sativum",
    "Potatoes": "Solanum tuberosum",
    "Sugarbeets": "Beta vulgaris",
    "Cotton": "Gossypium hirsutum",
    "Rice": "Oryza sativa",
    "Peanuts": "Arachis hypogaea",
    "Buckwheat": "Fagopyrum esculentum",
    "Flaxseed": "Linum usitatissimum",
}


# --------------------------------------------------------------------------------------
# Single-value converters
# --------------------------------------------------------------------------------------
def usda_texture_class(sand: float, silt: float, clay: float) -> str:
    """Name the USDA soil texture class from sand/silt/clay percentages (texture triangle)."""
    if silt + 1.5 * clay < 15:
        return "sand"
    if silt + 2 * clay < 30:
        return "loamy sand"
    if clay >= 40:
        if sand > 45:
            return "sandy clay"
        return "silty clay" if silt >= 40 else "clay"
    if clay >= 35 and sand > 45:
        return "sandy clay"
    if clay >= 27:
        if sand <= 20:
            return "silty clay loam"
        return "clay loam" if sand <= 45 else "sandy clay loam"
    if clay >= 20 and silt < 28 and sand > 45:
        return "sandy clay loam"
    if silt >= 80 and clay < 12:
        return "silt"
    if silt >= 50:
        return "silt loam"
    if clay >= 7 and silt >= 28 and sand <= 52:
        return "loam"
    return "sandy loam"


def texture_to_ecocrop(sand: float, silt: float, clay: float, om: float | None = None) -> str:
    if om is not None and not _missing(om) and om >= ORGANIC_SOIL_OM_PCT:
        return TEXT_ORGANIC
    return USDA_TEXTURE_TO_ECOCROP[usda_texture_class(sand, silt, clay)]


def drainage_to_ecocrop(drainagecl: str | None) -> str | None:
    return SSURGO_DRAINAGE_TO_ECOCROP.get(drainagecl) if drainagecl else None


def depth_to_ecocrop(depth_cm: float | None) -> str | None:
    if _missing(depth_cm):
        return None
    if depth_cm < 20:
        return DEP_VERY_SHALLOW
    if depth_cm < 50:
        return DEP_SHALLOW
    if depth_cm <= 150:
        return DEP_MEDIUM
    return DEP_DEEP


def salinity_to_ecocrop(ec_dsm: float | None) -> str | None:
    if _missing(ec_dsm):
        return None
    if ec_dsm < 4:
        return SAL_LOW
    return SAL_MEDIUM if ec_dsm <= 10 else SAL_HIGH


def fertility_to_ecocrop(om_pct: float | None) -> str | None:
    """APPROXIMATE: EcoCrop fertility has no numeric definition, so topsoil organic
    matter is used as a stand-in (<2% low, 2-4% moderate, >4% high)."""
    if _missing(om_pct):
        return None
    if om_pct < 2:
        return FER_LOW
    return FER_MODERATE if om_pct <= 4 else FER_HIGH


def frost_free_days(daily_tmin: pd.Series, frost_c: float = 0.0) -> int:
    """Days between the last spring frost (Jan-Jun) and the first autumn frost (Jul-Dec)
    in one year of daily minimum temperatures. Compare with EcoCrop gmin/gmax."""
    frost = daily_tmin[daily_tmin <= frost_c]
    year = daily_tmin.index[0].year
    spring = frost[frost.index.month <= 6]
    autumn = frost[frost.index.month >= 7]
    last_spring = spring.index.max() if len(spring) else pd.Timestamp(year, 1, 1) - pd.Timedelta(days=1)
    first_autumn = autumn.index.min() if len(autumn) else pd.Timestamp(year, 12, 31) + pd.Timedelta(days=1)
    return (first_autumn - last_spring).days - 1


# --------------------------------------------------------------------------------------
# Whole-output converters
# --------------------------------------------------------------------------------------
def climate_profile(power_df: pd.DataFrame) -> pd.DataFrame:
    """NASA POWER daily data -> one row per full year, plus a final multi-year mean row.

    Columns (compare with EcoCrop):
      t_mean_m01..m12  monthly mean air temp, degC   -> topmn/topmx, tmin/tmax
      t_min_m01..m12   monthly mean of daily minimum temp, degC -> ktmp
      t_min_abs        coldest daily minimum of the year, degC  -> ktmp / ktmpr
      rain_annual_mm   total precipitation, mm       -> ropmn/ropmx, rmin/rmax
      frost_free_days  days between frosts, days     -> gmin/gmax
    """
    df = power_df.copy()
    df.index = pd.to_datetime(df.index)
    full_years = [y for y, n in df.groupby(df.index.year).size().items() if n >= 365]
    df = df[df.index.year.isin(full_years)]
    year, month = df.index.year, df.index.month

    t_mean = df["T2M"].groupby([year, month]).mean().unstack()
    t_mean.columns = [f"t_mean_m{m:02d}" for m in t_mean.columns]
    t_min = df["T2M_MIN"].groupby([year, month]).mean().unstack()
    t_min.columns = [f"t_min_m{m:02d}" for m in t_min.columns]

    yearly = pd.concat([t_mean, t_min], axis=1)
    yearly["t_min_abs"] = df["T2M_MIN"].groupby(year).min()
    yearly["rain_annual_mm"] = df["PRECTOTCORR"].groupby(year).sum()
    yearly["frost_free_days"] = df["T2M_MIN"].groupby(year).apply(frost_free_days)

    yearly.index = yearly.index.astype(str)
    yearly.loc[f"mean_{full_years[0]}_{full_years[-1]}"] = yearly.mean()
    yearly.index.name = "period"
    return yearly.round(2)


def site_profile(soil_df: pd.DataFrame, lat: float, lon: float, elevation_m: float) -> dict:
    """SSURGO soil + location -> one record in EcoCrop terms.

    Uses the dominant soil component (largest % of the map unit). Raw SSURGO values
    are kept next to each EcoCrop class so the translation can be checked.
    """
    soil = soil_df.sort_values("comppct_r", ascending=False).iloc[0]
    depth = soil["restriction_depth_cm"]
    if _missing(depth):
        depth = soil["soil_depth_cm"]
    return {
        # location -> latmn/latmx, altmx
        "lat": lat,
        "lon": lon,
        "alt_m": elevation_m,
        # which soil this describes
        "soil_component": soil["compname"],
        "soil_component_pct": soil["comppct_r"],
        # pH -> phopmn/phopmx, phmin/phmax (already the same units)
        "ph": soil["ph1to1h2o_r"],
        # texture -> text/textr
        "text": texture_to_ecocrop(soil["sandtotal_r"], soil["silttotal_r"],
                                   soil["claytotal_r"], soil["om_r"]),
        "text_raw": usda_texture_class(soil["sandtotal_r"], soil["silttotal_r"],
                                       soil["claytotal_r"]),
        # drainage -> dra/drar
        "dra": drainage_to_ecocrop(soil["drainagecl"]),
        "dra_raw": soil["drainagecl"],
        # depth -> dep/depr
        "dep": depth_to_ecocrop(depth),
        "dep_raw_cm": depth,
        # salinity -> sal/salr
        "sal": salinity_to_ecocrop(soil["ec_r"]),
        "sal_raw_dsm": soil["ec_r"],
        # fertility -> fer/ferr (approximate, from organic matter)
        "fer": fertility_to_ecocrop(soil["om_r"]),
        "fer_raw_om_pct": soil["om_r"],
    }


def crop_history_to_ecocrop(cdl_df: pd.DataFrame, ecocrop_df: pd.DataFrame) -> pd.DataFrame:
    """Add each year's EcoCrop scientific name (and whether that row exists) to the CDL history."""
    out = cdl_df.copy()
    out["scientificname"] = out["crop"].map(CDL_TO_ECOCROP)
    known = set(ecocrop_df["scientificname"])
    out["in_ecocrop"] = out["scientificname"].isin(known)
    return out


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NA
