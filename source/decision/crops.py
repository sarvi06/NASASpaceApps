"""Candidate crops: every plant in EcoCrop that can sit in a field rotation, with its needs.

EcoCrop has ~2,500 plants, most of them trees, ornamentals and medicinal plants. There is no
hand-picked shortlist: is_rotation_crop() removes those using EcoCrop's own columns (life form,
category, life span) and everything else is a candidate. What each plant can be used for
(harvest, cover crop, forage), its family and its winter hardiness also come from EcoCrop.

    raw = get_crop_requirements()                  # data_pullers/FAO_EcoCrop_pull.py
    crops = build_crops(raw, sold=SOLD_CROPS)      # {scientific name: Crop}

A Crop holds agronomy only. What it earns is a separate question: decision/economics.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from .field_profile import CDL_TO_ECOCROP

LEGUME_FAMILY = "Fabaceae"

# EcoCrop categories (column `cat`).
NOT_FIELD_CROPS = {"forest/wood", "ornamentals/turf", "medicinals & aromatic", "weed"}
CASH_CATEGORIES = {"cereals & pseudocereals", "pulses (grain legumes)", "roots/tubers",
                   "vegetables", "fruits & nuts", "materials"}
FORAGE_CATEGORY, COVER_CATEGORY = "forage/pasture", "cover crop"
# Perennials only fit a 1-4 year rotation if they are cut, ended or dug up within it.
PERENNIALS_ALLOWED = {FORAGE_CATEGORY, COVER_CATEGORY, "roots/tubers"}

HARDY_BELOW_C = -4      # EcoCrop "killing temperature at rest" at or below this = overwinters

# Extra names people use that EcoCrop does not list.
_ALIASES = {"maize": "Zea mays ssp. mays", "soy": "Glycine max", "soybeans": "Glycine max",
            "winter wheat": "Triticum aestivum", "spring wheat": "Triticum aestivum",
            "hairy vetch": "Vicia villosa ssp. villosa", "cereal rye": "Secale cereale",
            "rapeseed": "Brassica napus", "sugarbeets": "Beta vulgaris var. saccharifera"}


@dataclass(frozen=True)
class Crop:
    sci: str
    name: str
    family: str
    roles: frozenset            # {"cash", "cover", "forage"}
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
    other_names: frozenset = frozenset()    # every EcoCrop common name, lower case

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
# Which EcoCrop plants are rotation crops, and what for
# --------------------------------------------------------------------------------------
def is_rotation_crop(row: Mapping, sold: bool = False) -> bool:
    """Can this EcoCrop plant sit in a field rotation?

    Removed: trees; plants that are only timber, ornamental, medicinal or weeds; perennials
    that are not forage, cover or root crops (orchards, plantations); and perennial shrubs
    that are not root crops. EcoCrop gives some plants no category at all (e.g. sweet potato,
    sugarcane): those are kept only if `sold`, i.e. FAOSTAT lists them as a crop farmers sell.
    """
    forms, categories, spans = _labels(row.get("lifo")), _labels(row.get("cat")), _labels(row.get("lispa"))
    if not categories:
        return sold
    if "tree" in forms or categories <= NOT_FIELD_CROPS:
        return False
    if spans != {"perennial"}:
        return True
    allowed = {"roots/tubers"} if "shrub" in forms else PERENNIALS_ALLOWED
    return bool(categories & allowed)


def crop_roles(row: Mapping, sold: bool = False) -> frozenset:
    """What the plant can be grown for, from its EcoCrop categories."""
    categories = _labels(row.get("cat"))
    roles = set()
    if sold or categories & CASH_CATEGORIES:
        roles.add("cash")
    if FORAGE_CATEGORY in categories:
        roles.add("forage")
    if COVER_CATEGORY in categories:
        roles.add("cover")
    return frozenset(roles)


# --------------------------------------------------------------------------------------
# Building the candidate list
# --------------------------------------------------------------------------------------
def build_crops(raw: pd.DataFrame, sold: Mapping[str, str] | None = None,
                extra: Iterable[str] = ()) -> dict[str, Crop]:
    """Raw EcoCrop table -> {scientific name: Crop} for every rotation crop.

    sold    {scientific name: everyday name} of crops FAOSTAT has prices for
            (economics.SOLD_CROPS); they are listed first and use that name
    extra   scientific names to include whatever the filter says (e.g. the field's history)

    One Crop per name: where EcoCrop has several rows called the same (e.g. two "cotton"
    species), the sold one, else the most complete row, is kept.
    """
    sold, extra = dict(sold or {}), set(extra)
    records = raw.assign(_filled=raw.notna().sum(axis=1)).to_dict("records")
    records.sort(key=lambda r: (r["scientificname"] not in sold, r["scientificname"] not in extra,
                                -r["_filled"]))
    crops: dict[str, Crop] = {}
    names: set[str] = set()
    for r in records:
        sci = r["scientificname"]
        if sci in crops or not (sci in extra or is_rotation_crop(r, sci in sold)):
            continue
        crop = _make_crop(r, sold.get(sci), forced=sci in extra)
        if crop is not None and crop.name.lower() not in names:
            crops[sci] = crop
            names.add(crop.name.lower())
    return crops


def _make_crop(r: Mapping, name: str | None = None, forced: bool = False) -> Crop | None:
    sci = r["scientificname"]
    tmin, tmax, topmn, topmx = (_num(r.get(c)) for c in ("tmin", "tmax", "topmn", "topmx"))
    gmin, gmax = _num(r.get("gmin")), _num(r.get("gmax"))
    if None in (tmin, tmax, topmn, topmx, gmin) or not tmin <= topmn <= topmx <= tmax or gmin <= 0:
        return None
    if gmax is None or gmax < gmin:
        gmax = gmin
    roles = crop_roles(r, sold=name is not None) or (frozenset({"cash"}) if forced else frozenset())
    if not roles:
        return None
    rest_kill = _num(r.get("ktmpr"))
    common = _items(r.get("comname"))
    return Crop(
        sci=sci, name=name or (str(common[0]).strip() if common else sci),
        family=_family(r.get("famname")), roles=roles,
        hardy_to=rest_kill if rest_kill is not None and rest_kill <= HARDY_BELOW_C else None,
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
        other_names=frozenset(str(n).strip().lower() for n in common),
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
    """Look a crop up by scientific name, our name, a CropScape name, an alias or any EcoCrop
    common name (the first crop listing that name wins; sold crops are listed first)."""
    key = str(name).strip().lower()
    for crop in crops.values():
        if key in (crop.sci.lower(), crop.name.lower()):
            return crop
    sci = {k.lower(): v for k, v in CDL_TO_ECOCROP.items()}.get(key) or _ALIASES.get(key)
    if sci in crops:
        return crops[sci]
    return next((crop for crop in crops.values() if key in crop.other_names), None)
