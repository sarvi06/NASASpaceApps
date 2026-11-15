"""Turn the pulled data into one FieldProfile, in EcoCrop's variables, units and labels.

  NASA POWER daily climate -> monthly_climatology()       12-month climate the crop scoring uses
                           -> climate_profile()           per-year summary (frost, heat, heavy rain)
                           -> climate_insights()          trends and plain numbers for the report
  SSURGO soil + location   -> site_profile()              pH, texture/drainage/depth/salinity/fertility
  CropScape crop history   -> crop_history_to_ecocrop()   crop names -> EcoCrop scientific names
                           -> detect_current_rotation()   e.g. corn <-> soybeans
  all of the above         -> build_field_profile()       one FieldProfile object

Nothing here judges whether a crop suits the field; that is decision/suitability.py.
Every label below is copied exactly from the EcoCrop table, so a field value can be
checked directly against a crop's columns (e.g. site["dra"] in crop["drar"]).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

HEAT_STRESS_C = 32     # daily max above this = heat-stress day
TREND_P_MAX = 0.1      # a yearly trend is reported only if its chance-probability is below this
HEAVY_RAIN_MM = 25    # daily rain above this = heavy-rain day (erosion / waterlogging risk)

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
    "Sugarbeets": "Beta vulgaris var. saccharifera",
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
def _complete_months(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only days in calendar months that are fully covered (e.g. not half of June)."""
    idx = pd.to_datetime(df.index)
    df = df.set_axis(idx)
    counts = df.groupby([idx.year, idx.month]).size()
    full = {k for k, n in counts.items() if n == pd.Timestamp(k[0], k[1], 1).days_in_month}
    return df[[(y, m) in full for y, m in zip(idx.year, idx.month)]]


def climate_profile(power_df: pd.DataFrame) -> pd.DataFrame:
    """NASA POWER daily data -> one row per full calendar year, plus a final mean row.

    Columns (compare with EcoCrop):
      t_mean_m01..m12  monthly mean air temp, degC   -> topmn/topmx, tmin/tmax
      t_min_m01..m12   monthly mean of daily minimum temp, degC -> ktmp
      t_min_abs        coldest daily minimum of the year, degC  -> ktmp / ktmpr
      rain_annual_mm   total precipitation, mm       -> ropmn/ropmx, rmin/rmax
      frost_free_days  days between frosts, days     -> gmin/gmax
      heat_days        days with max temp > 32 degC (heat stress)
      heavy_rain_days  days with > 25 mm rain (erosion / waterlogging risk)
      root_wetness     mean root-zone wetness (0 dry .. 1 saturated)
    Empty table if the data contains no full calendar year.
    """
    df = power_df.copy()
    df.index = pd.to_datetime(df.index)
    full_years = [y for y, n in df.groupby(df.index.year).size().items() if n >= 365]
    if not full_years:
        return pd.DataFrame()
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
    if "T2M_MAX" in df:
        yearly["heat_days"] = (df["T2M_MAX"] > HEAT_STRESS_C).groupby(year).sum()
    yearly["heavy_rain_days"] = (df["PRECTOTCORR"] > HEAVY_RAIN_MM).groupby(year).sum()
    if "GWETROOT" in df:
        yearly["root_wetness"] = df["GWETROOT"].groupby(year).mean()

    yearly = yearly.astype(float)
    yearly.index = yearly.index.astype(str)
    yearly.loc[f"mean_{full_years[0]}_{full_years[-1]}"] = yearly.mean()
    yearly.index.name = "period"
    return yearly.round(2)


def monthly_climatology(power_df: pd.DataFrame) -> pd.DataFrame:
    """NASA POWER daily data -> 12 rows (one per calendar month), using complete months only.

      month     1..12
      tmean     mean daily air temperature, degC
      tmax      mean daily maximum temperature, degC
      tmin_ext  typical coldest night of the month: each year's lowest daily min, averaged, degC
      precip    typical monthly rainfall total: each year's monthly sum, averaged, mm
      wetness   mean root-zone soil wetness (0 dry .. 1 saturated), if available
    Raises ValueError if some calendar month never appears complete (needs >= 12 months).
    """
    df = _complete_months(power_df)
    if df.empty:
        raise ValueError("Need at least 12 complete months of daily climate data.")
    year, month = df.index.year, df.index.month

    out = pd.DataFrame({
        "tmean": df["T2M"].groupby(month).mean(),
        "tmax": df["T2M_MAX"].groupby(month).mean() if "T2M_MAX" in df else float("nan"),
        "tmin_ext": df["T2M_MIN"].groupby([year, month]).min().groupby(level=1).mean(),
        "precip": df["PRECTOTCORR"].groupby([year, month]).sum().groupby(level=1).mean(),
    })
    if "GWETROOT" in df:
        out["wetness"] = df["GWETROOT"].groupby(month).mean()
    missing = sorted(set(range(1, 13)) - set(out.index))
    if missing:
        raise ValueError(f"Need at least 12 complete months of daily climate data; "
                         f"no complete month for month number(s) {missing}.")
    out.index.name = "month"
    return out.reset_index()


def site_profile(soil_df: pd.DataFrame, lat: float, lon: float,
                 elevation_m: float | None) -> dict | None:
    """SSURGO soil + location -> one record in EcoCrop terms (None if there is no soil data).

    Uses the dominant soil component (largest % of the map unit). Raw SSURGO values
    are kept next to each EcoCrop class so the translation can be checked.
    """
    if soil_df is None or soil_df.empty:
        return None
    soil = soil_df.sort_values("comppct_r", ascending=False).iloc[0]
    depth = soil["restriction_depth_cm"]
    if _missing(depth):
        depth = soil["soil_depth_cm"]
    have_texture = not any(_missing(soil[c]) for c in ("sandtotal_r", "silttotal_r", "claytotal_r"))
    return {
        # location -> latmn/latmx, altmx
        "lat": lat,
        "lon": lon,
        "alt_m": elevation_m,
        # which soil this describes
        "soil_component": soil["compname"],
        "soil_component_pct": soil["comppct_r"],
        # pH -> phopmn/phopmx, phmin/phmax (already the same units)
        "ph": None if _missing(soil["ph1to1h2o_r"]) else float(soil["ph1to1h2o_r"]),
        # texture -> text/textr
        "text": texture_to_ecocrop(soil["sandtotal_r"], soil["silttotal_r"],
                                   soil["claytotal_r"], soil["om_r"]) if have_texture else None,
        "text_raw": usda_texture_class(soil["sandtotal_r"], soil["silttotal_r"],
                                       soil["claytotal_r"]) if have_texture else None,
        # drainage -> dra/drar
        "dra": drainage_to_ecocrop(soil["drainagecl"]) if isinstance(soil["drainagecl"], str) else None,
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
        # extra context for erosion / water (not EcoCrop variables)
        "slope_pct": soil.get("slope_r"),
        "erodibility_k": soil.get("kwfact"),
        "hydrologic_group": soil.get("hydgrp"),
        "water_capacity": soil.get("awc_r"),
    }


def crop_history_to_ecocrop(cdl_df: pd.DataFrame, ecocrop_df: pd.DataFrame | None = None
                            ) -> pd.DataFrame:
    """Add each year's EcoCrop scientific name (and whether that row exists) to the CDL history."""
    out = cdl_df.copy()
    out["scientificname"] = out["crop"].map(CDL_TO_ECOCROP)
    if ecocrop_df is not None:
        out["in_ecocrop"] = out["scientificname"].isin(set(ecocrop_df["scientificname"]))
    return out


def detect_current_rotation(history: pd.DataFrame, max_years: int = 8) -> dict | None:
    """Find the field's current rotation from its CropScape history.

    Looks at the most recent years (up to max_years) and finds the shortest repeating
    pattern, e.g. Corn, Soybeans, Corn, Soybeans -> ["Corn", "Soybeans"].
    Returns {"crops": [CDL names], "scientific": [...], "years": [...], "repeating": bool}
    or None if fewer than 2 recent years are known crops.
    """
    if history is None or history.empty or "crop" not in history:
        return None
    known = history.dropna(subset=["crop"]).sort_values("year").tail(max_years)
    known = known[known["crop"].isin(CDL_TO_ECOCROP)]
    if len(known) < 2:
        return None
    seq = list(known["crop"])
    for period in range(1, min(4, len(seq) // 2) + 1):
        if all(seq[i] == seq[i + period] for i in range(len(seq) - period)):
            pattern = seq[-period:]
            break
    else:
        period, pattern = None, seq[-3:]
    return {
        "crops": pattern,
        "scientific": [CDL_TO_ECOCROP[c] for c in pattern],
        "years": [int(y) for y in known["year"]],
        "history": seq,
        "repeating": period is not None,
    }


# --------------------------------------------------------------------------------------
# Insights (patterns the brief asks about: heat, frost, rain extremes, water trends)
# --------------------------------------------------------------------------------------
def _trend_p_value(values) -> float:
    """How likely a pattern this strong is to be luck (small = a real trend).

    It asks whether later years are higher (or lower) than earlier years more often than
    chance would give (the Mann-Kendall test), and needs no extra library.
    """
    v = list(values)
    n = len(v)
    s = sum(int(v[j] > v[i]) - int(v[j] < v[i]) for i in range(n) for j in range(i + 1, n))
    var = n * (n - 1) * (2 * n + 5) / 18
    if s == 0 or var == 0:
        return 1.0
    z = (s - 1 if s > 0 else s + 1) / math.sqrt(var)
    return 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))


def _trend_per_decade(series: pd.Series) -> float | None:
    """Least-squares slope of a yearly series, per 10 years.

    None if there are under 5 years or the trend could easily be chance (p >= TREND_P_MAX),
    so noisy years are not reported as a climate trend.
    """
    s = series.dropna()
    if len(s) < 5 or _trend_p_value(s.to_numpy(dtype=float)) >= TREND_P_MAX:
        return None
    years = s.index.astype(int)
    slope = np.polyfit(years, s.to_numpy(dtype=float), 1)[0]
    return round(float(slope) * 10, 3)


def climate_insights(power_df: pd.DataFrame, monthly: pd.DataFrame,
                     smap_df: pd.DataFrame | None = None) -> dict:
    """Plain numbers describing the field's conditions over the requested period."""
    yearly = climate_profile(power_df)
    per_year = yearly.iloc[:-1] if not yearly.empty else yearly
    warm = monthly.nlargest(5, "tmean")["month"].tolist()   # works in both hemispheres
    insights = {
        "years_of_data": round(len(power_df) / 365.25, 1),
        "full_years": len(per_year),
        "warm_season_months": sorted(warm),
        "annual_rain_mm": round(float(monthly["precip"].sum()), 0),
        "warm_season_rain_mm": round(float(monthly.set_index("month").loc[warm, "precip"].sum()), 0),
        "coldest_month_c": round(float(monthly["tmean"].min()), 1),
        "warmest_month_c": round(float(monthly["tmean"].max()), 1),
        "frost_months": int((monthly["tmin_ext"] < 0).sum()),
    }
    if not per_year.empty:
        insights.update({
            "frost_free_days": round(float(per_year["frost_free_days"].mean()), 0),
            "coldest_night_c": round(float(per_year["t_min_abs"].mean()), 1),
            "heat_days_per_year": round(float(per_year.get("heat_days", pd.Series([0])).mean()), 1),
            "heavy_rain_days_per_year": round(float(per_year["heavy_rain_days"].mean()), 1),
            "rain_trend_mm_per_decade": _trend_per_decade(per_year["rain_annual_mm"]),
            "driest_year_rain_mm": round(float(per_year["rain_annual_mm"].min()), 0),
            "wettest_year_rain_mm": round(float(per_year["rain_annual_mm"].max()), 0),
            "temp_trend_c_per_decade": _trend_per_decade(
                per_year[[f"t_mean_m{m:02d}" for m in range(1, 13)]].mean(axis=1)),
            "heat_days_trend_per_decade": _trend_per_decade(per_year["heat_days"])
            if "heat_days" in per_year else None,
            "root_wetness_trend_per_decade": _trend_per_decade(per_year["root_wetness"])
            if "root_wetness" in per_year else None,
        })
    if "wetness" in monthly:
        insights["warm_season_root_wetness"] = round(
            float(monthly.set_index("month").loc[warm, "wetness"].mean()), 2)
    if smap_df is not None and not smap_df.empty and "SM_ROOTZONE" in smap_df:
        sm = smap_df["SM_ROOTZONE"]
        insights["smap_root_zone_moisture"] = round(float(sm.mean()), 3)
        insights["smap_driest_month"] = int(sm.groupby(pd.to_datetime(sm.index).month).mean().idxmin())
    return insights


# --------------------------------------------------------------------------------------
# Everything about one field, in one object
# --------------------------------------------------------------------------------------
@dataclass
class FieldProfile:
    lat: float
    lon: float
    start_date: str
    end_date: str
    elevation_m: float | None
    climate_daily: pd.DataFrame          # NASA POWER, one row per day
    climate_monthly: pd.DataFrame        # 12 rows: tmean, tmax, tmin_ext, precip, wetness
    climate_yearly: pd.DataFrame         # one row per full year + mean row
    soil: pd.DataFrame                   # SSURGO components (empty outside the US)
    site: dict | None                    # dominant soil in EcoCrop terms (None outside the US)
    crop_history: pd.DataFrame           # CropScape years + EcoCrop names (empty outside the US)
    current_rotation: dict | None        # detected or user-supplied current rotation
    insights: dict = field(default_factory=dict)
    soil_moisture: pd.DataFrame | None = None   # NASA SMAP, if requested

    def to_dict(self) -> dict:
        """JSON-safe summary (no daily tables)."""
        return _json_safe({
            "lat": self.lat, "lon": self.lon, "start_date": self.start_date,
            "end_date": self.end_date, "elevation_m": self.elevation_m,
            "climate_monthly": self.climate_monthly.round(2).to_dict(orient="records"),
            "site": self.site,
            "crop_history": self.crop_history[["year", "crop"]].to_dict(orient="records")
            if not self.crop_history.empty else [],
            "current_rotation": self.current_rotation,
            "insights": self.insights,
        })


def build_field_profile(lat, lon, start_date, end_date, climate_daily, soil=None,
                        crop_history=None, current_rotation=None, smap=None) -> FieldProfile:
    """Turn the raw pulled tables into one FieldProfile."""
    soil = soil if soil is not None else pd.DataFrame()
    history = crop_history_to_ecocrop(crop_history) if crop_history is not None and not crop_history.empty \
        else pd.DataFrame(columns=["year", "cdl_code", "crop", "error", "scientificname"])
    elevation = climate_daily.attrs.get("elevation_m")
    monthly = monthly_climatology(climate_daily)
    if current_rotation is None:
        current_rotation = detect_current_rotation(history)
        if current_rotation is not None:
            current_rotation["source"] = "USDA CropScape"
    return FieldProfile(
        lat=lat, lon=lon, start_date=str(start_date), end_date=str(end_date),
        elevation_m=elevation, climate_daily=climate_daily, climate_monthly=monthly,
        climate_yearly=climate_profile(climate_daily), soil=soil,
        site=site_profile(soil, lat, lon, elevation), crop_history=history,
        current_rotation=current_rotation,
        insights=climate_insights(climate_daily, monthly, smap), soil_moisture=smap,
    )


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if math.isnan(value) else float(value)
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def _missing(value) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False
