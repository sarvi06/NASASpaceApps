"""USDA NRCS SSURGO soil properties via Soil Data Access (SDA).

API docs: https://sdmdataaccess.nrcs.usda.gov/
No login required. SDA accepts SQL queries over the SSURGO database.

SSURGO structure, in short:
  map unit (mukey)  = the soil polygon our point falls in
    component       = a soil type making up some % of that map unit
      horizon       = a depth layer of that component (we use the topsoil, depth 0)
"""

import pandas as pd
import requests

from .config import TIMEOUT

URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"

# Column -> plain-English meaning, for anyone reading the CSV.
COLUMNS = {
    "mukey": "map unit key (soil polygon id)",
    "muname": "map unit name",
    "compname": "soil component (series) name",
    "comppct_r": "% of the map unit made up by this component",
    "majcompflag": "Yes if a major component",
    "slope_r": "representative slope (%)",
    "drainagecl": "drainage class",
    "hydgrp": "hydrologic soil group (A = high infiltration ... D = low)",
    "hzdepb_r": "topsoil horizon bottom depth (cm)",
    "om_r": "organic matter in topsoil (%)",
    "sandtotal_r": "sand (%)",
    "silttotal_r": "silt (%)",
    "claytotal_r": "clay (%)",
    "awc_r": "available water capacity (cm water / cm soil)",
    "kwfact": "erodibility factor K (higher = more erodible)",
    "ph1to1h2o_r": "pH",
    "ec_r": "electrical conductivity, i.e. salinity (dS/m)",
    "soil_depth_cm": "depth to the bottom of the deepest described horizon (cm)",
    "restriction_depth_cm": "depth to the shallowest root-restricting layer, if any (cm)",
}


def _query(sql: str) -> pd.DataFrame:
    resp = requests.post(URL, json={"query": sql, "format": "JSON+COLUMNNAME"}, timeout=TIMEOUT)
    resp.raise_for_status()
    table = resp.json().get("Table", [])
    if not table:
        return pd.DataFrame()
    header, *rows = table
    return pd.DataFrame(rows, columns=header)


def fetch_soil_at_point(lat: float, lon: float) -> pd.DataFrame:
    """Return one row per soil component at the point, with its topsoil properties."""
    sql = f"""
    SELECT mu.mukey, mu.muname,
           c.compname, c.comppct_r, c.majcompflag, c.slope_r, c.drainagecl, c.hydgrp,
           h.hzdepb_r, h.om_r, h.sandtotal_r, h.silttotal_r, h.claytotal_r,
           h.awc_r, h.kwfact, h.ph1to1h2o_r, h.ec_r,
           (SELECT MAX(h2.hzdepb_r) FROM chorizon h2 WHERE h2.cokey = c.cokey) AS soil_depth_cm,
           (SELECT MIN(r.resdept_r) FROM corestrictions r WHERE r.cokey = c.cokey)
               AS restriction_depth_cm
    FROM mapunit mu
    JOIN component c ON c.mukey = mu.mukey
    LEFT JOIN chorizon h ON h.cokey = c.cokey AND h.hzdept_r = 0
    WHERE mu.mukey IN (
        SELECT * FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('POINT({lon} {lat})')
    )
    ORDER BY c.comppct_r DESC
    """
    df = _query(sql)
    # SDA returns everything as strings; convert the numeric columns.
    numeric = ["comppct_r", "slope_r", "hzdepb_r", "om_r", "sandtotal_r", "silttotal_r",
               "claytotal_r", "awc_r", "kwfact", "ph1to1h2o_r", "ec_r",
               "soil_depth_cm", "restriction_depth_cm"]
    for col in numeric:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df
