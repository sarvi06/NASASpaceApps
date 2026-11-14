"""Candidate crops: a curated list of field, cover and forage crops, with their EcoCrop needs.

EcoCrop has ~2,500 plants (trees, ornamentals, weeds...). Recommending from all of them gives
answers like "European larch", so we only consider the CANDIDATES below. Their growing needs
(temperature, rain, pH, soil, season length) come from EcoCrop; the farm-practice facts
(family, role, rough market value, winter hardiness) are filled in here because EcoCrop
doesn't hold them, or holds them unreliably.

    raw = get_crop_requirements()       # data_pullers/FAO_EcoCrop_pull.py
    crops = build_crops(raw)            # {scientific name: Crop}
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .field_profile import CDL_TO_ECOCROP

LEGUME_FAMILY = "Fabaceae"

# --------------------------------------------------------------------------------------
# Curated candidates.  value = rough relative market/forage value (0-1, INDICATIVE ONLY:
# no price data is used), hardy_to = typical lowest air temperature an overwintering crop
# survives while dormant (with normal snow/soil insulation); None = not winter-hardy.
# --------------------------------------------------------------------------------------
#   scientific name              name              family           roles                       value deep  hardy_to
_CANDIDATES = [
    ("Zea mays ssp. mays",         "corn",           "Poaceae",       ("cash",),                   0.80, False, None),
    ("Glycine max",                "soybean",        "Fabaceae",      ("cash",),                   0.80, False, None),
    ("Triticum aestivum",          "wheat",          "Poaceae",       ("cash", "cover"),           0.60, False, -25),
    ("Avena sativa",               "oats",           "Poaceae",       ("cash", "cover", "forage"), 0.35, False, None),
    ("Secale cereale",             "cereal rye",     "Poaceae",       ("cover", "cash", "forage"), 0.30, False, -30),
    ("Hordeum vulgare",            "barley",         "Poaceae",       ("cash", "cover", "forage"), 0.45, False, -15),
    ("Medicago sativa",            "alfalfa",        "Fabaceae",      ("forage",),                 0.60, True,  -30),
    ("Trifolium pratense",         "red clover",     "Fabaceae",      ("cover", "forage"),         0.30, True,  -25),
    ("Trifolium repens",           "white clover",   "Fabaceae",      ("cover", "forage"),         0.20, False, -25),
    ("Trifolium incarnatum",       "crimson clover", "Fabaceae",      ("cover",),                  0.10, False, -15),
    ("Vicia villosa ssp. villosa", "hairy vetch",    "Fabaceae",      ("cover",),                  0.10, False, -25),
    ("Pisum sativum",              "field pea",      "Fabaceae",      ("cash", "cover"),           0.45, False, -12),
    ("Vicia faba",                 "faba bean",      "Fabaceae",      ("cash", "cover"),           0.45, False, -10),
    ("Raphanus sativus",           "tillage radish", "Brassicaceae",  ("cover",),                  0.05, True,  None),
    ("Lolium multiflorum",         "annual ryegrass","Poaceae",       ("cover", "forage"),         0.30, False, -15),
    ("Sorghum bicolor",            "sorghum",        "Poaceae",       ("cash", "forage", "cover"), 0.55, True,  None),
    ("Helianthus annuus",          "sunflower",      "Asteraceae",    ("cash",),                   0.60, True,  None),
    ("Brassica napus",             "canola",         "Brassicaceae",  ("cash",),                   0.60, False, -15),
    ("Fagopyrum esculentum",       "buckwheat",      "Polygonaceae",  ("cover", "cash"),           0.35, False, None),
    ("Lens culinaris",             "lentil",         "Fabaceae",      ("cash",),                   0.55, False, None),
    ("Cicer arietinum",            "chickpea",       "Fabaceae",      ("cash",),                   0.60, False, None),
    ("Phaseolus vulgaris",         "dry bean",       "Fabaceae",      ("cash",),                   0.65, False, None),
    ("Solanum tuberosum",          "potato",         "Solanaceae",    ("cash",),                   0.90, False, None),
    ("Beta vulgaris",              "sugar beet",     "Amaranthaceae", ("cash",),                   0.80, True,  None),
    ("Panicum miliaceum",          "proso millet",   "Poaceae",       ("cash",),                   0.35, False, None),
    ("Linum usitatissimum",        "flax",           "Linaceae",      ("cash",),                   0.45, False, None),
    ("Sinapis alba",               "white mustard",  "Brassicaceae",  ("cover",),                  0.15, False, None),
    ("Oryza sativa",               "rice",           "Poaceae",       ("cash",),                   0.75, False, None),
    ("Gossypium hirsutum",         "cotton",         "Malvaceae",     ("cash",),                   0.80, True,  None),
    ("Arachis hypogaea",           "peanut",         "Fabaceae",      ("cash",),                   0.75, False, None),
    ("Vigna unguiculata",          "cowpea",         "Fabaceae",      ("cover", "cash", "forage"), 0.40, False, None),
    ("Cajanus cajan",              "pigeon pea",     "Fabaceae",      ("cash", "cover"),           0.45, True,  None),
    ("Pennisetum glaucum",         "pearl millet",   "Poaceae",       ("cash", "forage"),          0.40, False, None),
    ("Crotalaria juncea",          "sunn hemp",      "Fabaceae",      ("cover",),                  0.10, True,  None),
    ("Vigna radiata",              "mung bean",      "Fabaceae",      ("cash",),                   0.50, False, None),
    ("Sesamum indicum",            "sesame",         "Pedaliaceae",   ("cash",),                   0.55, False, None),
]
CANDIDATES = {row[0]: row for row in _CANDIDATES}

# Extra names people (or CropScape) use for the candidates.
_ALIASES = {"maize": "Zea mays ssp. mays", "soy": "Glycine max", "soybeans": "Glycine max",
            "rye": "Secale cereale", "winter wheat": "Triticum aestivum",
            "spring wheat": "Triticum aestivum", "peas": "Pisum sativum",
            "dry beans": "Phaseolus vulgaris", "potatoes": "Solanum tuberosum",
            "sugarbeets": "Beta vulgaris", "flaxseed": "Linum usitatissimum",
            "peanuts": "Arachis hypogaea", "radish": "Raphanus sativus",
            "clover": "Trifolium pratense", "vetch": "Vicia villosa ssp. villosa",
            "ryegrass": "Lolium multiflorum", "millet": "Panicum miliaceum"}


@dataclass(frozen=True)
class Crop:
    sci: str
    name: str
    family: str
    roles: frozenset            # {"cash", "cover", "forage"}
    value: float                # rough relative market/forage value, 0-1 (indicative)
    deep_rooted: bool
    hardy_to: float | None      # survives dormancy down to this air temp; None = not hardy
    # EcoCrop needs (None = unknown)
    tmin: float
    tmax: float
    topmn: float
    topmx: float
    ktmp: float | None          # killed by this temperature while growing
    rmin: float | None
    rmax: float | None
    ropmn: float | None
    ropmx: float | None
    phmin: float | None
    phmax: float | None
    phopmn: float | None
    phopmx: float | None
    gmin: float
    gmax: float
    text_opt: frozenset
    text_abs: frozenset
    dra_opt: frozenset
    dra_abs: frozenset
    dep_opt: str | None
    dep_abs: str | None
    sal_opt: str | None
    sal_abs: str | None
    fer_opt: str | None
    fer_abs: str | None

    @property
    def legume(self) -> bool:
        return self.family == LEGUME_FAMILY

    @property
    def can_harvest(self) -> bool:
        return bool(self.roles & {"cash", "forage"})

    @property
    def can_cover(self) -> bool:
        return "cover" in self.roles

    @property
    def label(self) -> str:
        return f"{self.name} ({self.sci})"


# --------------------------------------------------------------------------------------
# Cleaning EcoCrop cells (lists, numpy arrays, NaN, sentinels)
# --------------------------------------------------------------------------------------
_SENTINELS = {-9999.0, -999.0, -99.0}


def _items(v: Any) -> list:
    """Flatten a cell (scalar, list, numpy array) into non-missing plain values."""
    if isinstance(v, (list, tuple, set, np.ndarray)):
        out = []
        for x in (v.tolist() if isinstance(v, np.ndarray) else v):
            out.extend(_items(x))
        return out
    if v is None or v is pd.NA:
        return []
    try:
        if pd.isna(v):
            return []
    except (TypeError, ValueError):
        pass
    if isinstance(v, str):
        v = v.strip()
        return [v] if v and v.lower() not in {"nan", "none", "na", "-"} else []
    return [v.item() if isinstance(v, np.generic) else v]


def _num(v: Any) -> float | None:
    for x in _items(v):
        try:
            f = float(x)
        except (TypeError, ValueError):
            continue
        if not math.isnan(f) and f not in _SENTINELS:
            return f
    return None


def _labels(v: Any) -> frozenset:
    return frozenset(str(x).strip() for x in _items(v))


def _first(v: Any) -> str | None:
    items = _items(v)
    return str(items[0]).strip() if items else None


# --------------------------------------------------------------------------------------
# Building the candidate list
# --------------------------------------------------------------------------------------
def build_crops(raw: pd.DataFrame, extra: Iterable[str] = ()) -> dict[str, Crop]:
    """Raw EcoCrop table -> {scientific name: Crop} for the curated candidates
    (plus any `extra` scientific names, e.g. a crop in the field's history)."""
    rows = raw.set_index("scientificname")
    crops: dict[str, Crop] = {}
    for sci in list(CANDIDATES) + [s for s in extra if s not in CANDIDATES]:
        if sci not in rows.index:
            continue
        r = rows.loc[sci]
        if isinstance(r, pd.DataFrame):     # duplicate name: keep the most complete row
            r = r.loc[r.notna().sum(axis=1).idxmax()]
        crop = _make_crop(sci, r)
        if crop is not None:
            crops[sci] = crop
    return crops


def _make_crop(sci: str, r: pd.Series) -> Crop | None:
    tmin, tmax, topmn, topmx = (_num(r.get(c)) for c in ("tmin", "tmax", "topmn", "topmx"))
    gmin, gmax = _num(r.get("gmin")), _num(r.get("gmax"))
    if None in (tmin, tmax, topmn, topmx, gmin) or not tmin <= topmn <= topmx <= tmax or gmin <= 0:
        return None
    if gmax is None or gmax < gmin:
        gmax = gmin
    _, name, family, roles, value, deep, hardy = CANDIDATES.get(
        sci, (sci, _first(r.get("comname")) or sci, _family(r.get("famname")),
              ("cash",), 0.5, False, None))
    return Crop(
        sci=sci, name=name, family=family, roles=frozenset(roles), value=value,
        deep_rooted=deep, hardy_to=hardy,
        tmin=tmin, tmax=tmax, topmn=topmn, topmx=topmx, ktmp=_num(r.get("ktmp")),
        rmin=_num(r.get("rmin")), rmax=_num(r.get("rmax")),
        ropmn=_num(r.get("ropmn")), ropmx=_num(r.get("ropmx")),
        phmin=_num(r.get("phmin")), phmax=_num(r.get("phmax")),
        phopmn=_num(r.get("phopmn")), phopmx=_num(r.get("phopmx")),
        gmin=gmin, gmax=gmax,
        text_opt=_labels(r.get("text")), text_abs=_labels(r.get("textr")),
        dra_opt=_labels(r.get("dra")), dra_abs=_labels(r.get("drar")),
        dep_opt=_first(r.get("dep")), dep_abs=_first(r.get("depr")),
        sal_opt=_first(r.get("sal")), sal_abs=_first(r.get("salr")),
        fer_opt=_first(r.get("fer")), fer_abs=_first(r.get("ferr")),
    )


_FAMILY_SYNONYMS = {"gramineae": "Poaceae", "leguminosae": "Fabaceae",
                    "papilionaceae": "Fabaceae", "cruciferae": "Brassicaceae",
                    "compositae": "Asteraceae", "umbelliferae": "Apiaceae",
                    "labiatae": "Lamiaceae", "palmae": "Arecaceae"}


def _family(v: Any) -> str:
    """EcoCrop famname is a path like 'Magnoliopsida:...:Leguminosae' -> 'Fabaceae'."""
    text = _first(v)
    if not text:
        return "unknown"
    name = text.split(":")[-1].strip()
    return _FAMILY_SYNONYMS.get(name.lower(), name)


def find_crop(name: str, crops: dict[str, Crop]) -> Crop | None:
    """Look a crop up by scientific name, our name, a CropScape name or a common alias."""
    key = name.strip().lower()
    for crop in crops.values():
        if key in (crop.sci.lower(), crop.name.lower()):
            return crop
    sci = {k.lower(): v for k, v in CDL_TO_ECOCROP.items()}.get(key) or _ALIASES.get(key)
    return crops.get(sci) if sci else None
