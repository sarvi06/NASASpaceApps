"""How much of a crop's water need does rain cover over its own growing months?

The air draws water out of a crop every day; how much depends on heat, sunshine, humidity and
wind. FAO's standard measure of that pull is the reference evapotranspiration, ET0 (mm of water
a day from a well-watered grass field). NASA POWER gives every number it needs, so:

  reference_et_monthly()   NASA POWER daily data -> typical ET0 for each calendar month (mm)
  rain_share()             rain over a crop's season vs its water need there, 0-1

    et0 = reference_et_monthly(power_daily, lat=42.065, elevation_m=310)   # 12 values, Jan first
    rain_share(start=4, months=5, et0=et0, precip=monthly_rain)           # e.g. 0.67 for May-Sep

Method: FAO Irrigation and Drainage Paper 56 (Allen et al. 1998), Penman-Monteith, daily.
Equation numbers in the comments are the paper's.

Simplifications:
  - One generic crop-coefficient shape for every crop (KC_START / KC_MID / KC_END) instead of
    each crop's own FAO-56 table values, which EcoCrop does not hold.
  - A fixed share of rain is counted as reaching the roots (EFFECTIVE_RAIN); run-off and deep
    drainage are not modelled day by day.
  - Water stored in the soil before planting is left out on purpose (see rain_share()).
  - Wind is NASA POWER's 2 m wind, so no height correction is needed; soil heat flux is 0 for
    daily steps, as FAO-56 recommends.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

NEEDED = ["T2M", "T2M_MAX", "T2M_MIN", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN"]

KC_START = 0.5    # crop uses about half the reference rate while it emerges (little leaf cover)
KC_MID = 1.0      # full leaf cover: about the same as the reference grass
KC_END = 0.75     # ripening and drying down: leaves age and use less
EFFECTIVE_RAIN = 0.8   # share of rain that reaches the roots (the rest runs off or drains away)

ALBEDO = 0.23           # share of sunlight a green crop reflects (FAO-56 reference grass)
SOLAR_CONSTANT = 0.0820  # MJ/m^2/min
STEFAN_BOLTZMANN = 4.903e-9  # MJ/K^4/m^2/day


# --------------------------------------------------------------------------------------
# FAO-56 building blocks (work on numbers or numpy arrays)
# --------------------------------------------------------------------------------------
def _sat_vapour_pressure(t):
    """Saturation vapour pressure at temperature t degC, kPa.  (FAO-56 eq. 11)"""
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def _vapour_slope(t):
    """Slope of the saturation vapour pressure curve at t degC, kPa/degC.  (eq. 13)"""
    return 4098 * _sat_vapour_pressure(t) / (t + 237.3) ** 2


def _psychrometric_constant(elevation_m: float) -> float:
    """kPa/degC, from the air pressure at this elevation.  (eq. 7 and 8)"""
    pressure = 101.3 * ((293 - 0.0065 * elevation_m) / 293) ** 5.26
    return 0.000665 * pressure


def _extraterrestrial_radiation(lat: float, day_of_year):
    """Sunlight at the top of the atmosphere, MJ/m^2/day.  (eq. 21, 23, 24, 25)"""
    phi = math.radians(lat)
    angle = 2 * np.pi * np.asarray(day_of_year, dtype=float) / 365
    inverse_distance = 1 + 0.033 * np.cos(angle)                       # eq. 23
    declination = 0.409 * np.sin(angle - 1.39)                          # eq. 24
    # clipped so polar day / night does not give an invalid arccos
    sunset = np.arccos(np.clip(-math.tan(phi) * np.tan(declination), -1, 1))   # eq. 25
    return (24 * 60 / np.pi * SOLAR_CONSTANT * inverse_distance
            * (sunset * math.sin(phi) * np.sin(declination)
               + math.cos(phi) * np.cos(declination) * np.sin(sunset)))  # eq. 21


def _net_radiation(radiation, ra, tmax, tmin, ea, elevation_m: float):
    """Net radiation at the crop surface, MJ/m^2/day.  (eq. 37, 38, 39, 40)"""
    clear_sky = (0.75 + 2e-5 * elevation_m) * ra                        # eq. 37
    shortwave = (1 - ALBEDO) * radiation                                # eq. 38
    cloudiness = np.clip(np.divide(radiation, clear_sky, out=np.ones_like(ra), where=clear_sky > 0),
                         0, 1.0)
    longwave = (STEFAN_BOLTZMANN * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2
                * (0.34 - 0.14 * np.sqrt(ea)) * (1.35 * cloudiness - 0.35))  # eq. 39
    return shortwave - longwave                                         # eq. 40


def reference_et_daily(tmean, tmax, tmin, rh, wind, radiation, lat: float, day_of_year,
                       elevation_m: float | None = None):
    """FAO-56 Penman-Monteith reference evapotranspiration, mm/day (never below 0).

    Temperatures degC, rh = mean relative humidity %, wind at 2 m in m/s, radiation =
    sunlight reaching the ground in MJ/m^2/day, lat in degrees, elevation in m (0 if unknown).
    Works on single numbers or equal-length arrays."""
    z = 0.0 if elevation_m is None or pd.isna(elevation_m) else float(elevation_m)
    tmean, tmax, tmin = (np.asarray(v, dtype=float) for v in (tmean, tmax, tmin))
    rh, wind, radiation = (np.asarray(v, dtype=float) for v in (rh, wind, radiation))
    es = (_sat_vapour_pressure(tmax) + _sat_vapour_pressure(tmin)) / 2  # eq. 12
    ea = rh / 100 * es                                                  # eq. 19
    delta, gamma = _vapour_slope(tmean), _psychrometric_constant(z)
    ra = np.broadcast_to(_extraterrestrial_radiation(lat, day_of_year), tmean.shape).astype(float)
    rn = _net_radiation(radiation, ra, tmax, tmin, ea, z)
    et0 = ((0.408 * delta * rn + gamma * 900 / (tmean + 273) * wind * (es - ea))
           / (delta + gamma * (1 + 0.34 * wind)))                       # eq. 6, soil heat flux 0
    return np.maximum(et0, 0.0)


# --------------------------------------------------------------------------------------
# NASA POWER daily table -> 12 monthly values
# --------------------------------------------------------------------------------------
def reference_et_monthly(power_daily: pd.DataFrame, lat: float,
                         elevation_m: float | None = None) -> list[float] | None:
    """Typical ET0 total for each calendar month, mm, January first: each year's monthly sum,
    averaged over the years, using complete months only (as the rain in
    field_profile.monthly_climatology()). None if a needed NASA POWER column is missing or
    some calendar month never has a complete record."""
    if power_daily is None or any(c not in power_daily for c in NEEDED):
        return None
    df = power_daily[NEEDED].copy()
    df.index = pd.to_datetime(df.index)
    df = df.dropna()
    if df.empty:
        return None
    daily = pd.Series(reference_et_daily(df["T2M"], df["T2M_MAX"], df["T2M_MIN"], df["RH2M"],
                                         df["WS2M"], df["ALLSKY_SFC_SW_DWN"], lat,
                                         df.index.day_of_year, elevation_m),
                      index=df.index)
    year, month = daily.index.year, daily.index.month
    per_month = daily.groupby([year, month]).agg(["sum", "size"])
    full = [n == pd.Timestamp(y, m, 1).days_in_month for (y, m), n in per_month["size"].items()]
    typical = per_month.loc[full, "sum"].groupby(level=1).mean()
    if sorted(typical.index) != list(range(1, 13)):
        return None
    return [float(typical[m]) for m in range(1, 13)]


# --------------------------------------------------------------------------------------
# One crop's season
# --------------------------------------------------------------------------------------
def rain_share(start: int, months: int, et0: list[float], precip: list[float],
               rain_scale: float = 1.0) -> float:
    """Share of a crop's water need over its season that rain supplies, 0-1.

    start = planting month (0 = Jan), months = months in the ground, et0 and precip = 12
    monthly values in mm. Need = crop coefficient x ET0, summed over the season (KC_START in
    the planting month, KC_END in the last, KC_MID between); supply = the season's rain x
    rain_scale x EFFECTIVE_RAIN. Water already stored in the soil is deliberately not counted:
    in a wet place it would cover almost every crop and the score could no longer tell a
    thirsty summer crop from one that grows through the cool, damp months."""
    season = [(start + i) % 12 for i in range(months)]
    kc = [KC_START if i == 0 else KC_END if i == months - 1 else KC_MID for i in range(months)]
    demand = sum(k * et0[m] for k, m in zip(kc, season))
    if demand <= 0:
        return 1.0
    supply = sum(precip[m] for m in season) * rain_scale * EFFECTIVE_RAIN
    return max(0.0, min(1.0, supply / demand))
