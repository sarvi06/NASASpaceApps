"""Pull, clean and validate the FAO EcoCrop database — standalone module + CLI.

What this does
--------------
1. Downloads the EcoCrop Parquet from the CGIAR Climate Data Hub (atomic,
   with retries, cache expiry, and fallback to a stale cache if offline).
2. Maps EcoCrop's column names onto a clean internal schema.
3. Cleans cells properly: numpy arrays/lists, NaN, sentinel values, stray
   whitespace — missing data stays missing (no invented defaults).
4. Runs quality checks (range + ordering) and flags each row.
5. De-duplicates species, keeping the most complete record.
6. Exports CSV / Parquet / JSON, or looks up a crop.

Library use
-----------
    from ecocrop_loader import get_clean_ecocrop
    crops = get_clean_ecocrop(only_complete=True)            # DataFrame
    rice  = get_clean_ecocrop(names=["rice"])

Dependencies
------------
    pip install pandas pyarrow

CLI
---
    python ecocrop_loader.py inspect
    python ecocrop_loader.py validate
    python ecocrop_loader.py export --out ecocrop_clean.csv
    python ecocrop_loader.py export --out crops.parquet --format parquet --only-complete
    python ecocrop_loader.py export --out india.csv --names rice wheat chickpea lentil
    python ecocrop_loader.py lookup "Oryza sativa"
    python ecocrop_loader.py lookup rice
"""
from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


# ==========================================================================
# 1. CONFIGURATION
# ==========================================================================
ECOCROP_URL = (
    "https://digital-atlas.s3.amazonaws.com/cdh/data/ecocrop/ecocrop.parquet"
)
LOCAL_CACHE = Path("ecocrop.parquet")
CACHE_MAX_AGE_DAYS: Optional[float] = None   # None = cache never expires
DOWNLOAD_TIMEOUT = 120
DOWNLOAD_RETRIES = 3

# How list-valued cells are reduced for NAME / NUMERIC fields:
#   "first" -> first element   "join" -> pipe-joined   "keep" -> Python list
# (Categorical fields such as texture/drainage always keep ALL values,
#  normalised, de-duplicated and pipe-joined: "light|medium".)
LIST_HANDLING = "first"

# Strings treated as missing; numeric sentinels treated as missing.
MISSING_TOKENS = {"", "nan", "none", "null", "na", "n/a", "-", "--", "?", "unknown"}
NUMERIC_SENTINELS = {-9999.0, -999.0, -99.0}

# Fields that must be present and sane for a crop to be modelled.
CORE_FIELDS = ("tmin", "tmax", "topmn", "topmx", "gmin")


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# ==========================================================================
# 2. COLUMN ALIASES
# --------------------------------------------------------------------------
# Matching ignores case, spaces, underscores and hyphens, so "PH_MIN",
# "ph min" and "phmin" are all the same column.
# ==========================================================================
COLUMN_ALIASES: Dict[str, List[str]] = {
    # ---- identity ----
    "ecocrop_id":       ["ecocrop_id", "ecoportcode", "ecoport_code", "ECOPORT_CODE"],
    "scientific_name":  ["scientific_name", "scientificname", "sci_name", "species"],
    "common_name":      ["common_name", "comname", "common_names"],
    "family":           ["family"],
    "category":         ["category"],

    # ---- climatic ----
    "tmin":  ["tmin"],
    "tmax":  ["tmax"],
    "topmn": ["topmn"],
    "topmx": ["topmx"],
    "ktmp":  ["ktmp", "ktmin"],
    "rmin":  ["rmin"],
    "rmax":  ["rmax"],
    "ropmn": ["ropmn"],
    "ropmx": ["ropmx"],
    "gmin":  ["gmin"],
    "gmax":  ["gmax"],

    # ---- edaphic ----
    "ph_min":     ["phmin", "ph_min"],
    "ph_max":     ["phmax", "ph_max"],
    "ph_opt_min": ["phopmn", "ph_opt_min"],
    "ph_opt_max": ["phopmx", "ph_opt_max"],

    # ---- categorical ----
    "photoperiod": ["photo", "photoperiod"],
    "texture":     ["text", "txt", "texture"],
    "drainage":    ["dra", "drain", "drainage"],
    "salinity":    ["sal", "salinity"],
    "climate":     ["clim", "climate"],
}

FLOAT_FIELDS = {
    "tmin", "tmax", "topmn", "topmx", "ktmp",
    "rmin", "rmax", "ropmn", "ropmx",
    "ph_min", "ph_max", "ph_opt_min", "ph_opt_max",
}
INT_FIELDS = {"gmin", "gmax", "ecocrop_id"}
TEXT_FIELDS = {"scientific_name", "common_name", "family", "category"}
CATEGORICAL_FIELDS = {"photoperiod", "texture", "drainage", "salinity", "climate"}


# ==========================================================================
# 3. LABEL NORMALISATION
# --------------------------------------------------------------------------
# These only unify spelling variants. EcoCrop's own vocabulary
# (light/medium/heavy, ...) is preserved, and unmapped labels pass through
# lower-cased instead of being replaced by a guess.
# ==========================================================================
CATEGORY_MAPS: Dict[str, Dict[str, str]] = {
    "photoperiod": {
        "short day": "short-day", "short-day": "short-day", "short": "short-day",
        "neutral day": "day-neutral", "day neutral": "day-neutral",
        "day-neutral": "day-neutral", "neutral": "day-neutral",
        "long day": "long-day", "long-day": "long-day", "long": "long-day",
    },
    "drainage": {
        "well": "well-drained", "well drained": "well-drained",
        "poorly": "poorly-drained", "poor": "poorly-drained",
        "excessive": "excessively-drained", "excessively": "excessively-drained",
    },
    "texture": {},
    "salinity": {},
    "climate": {},
}

# Only applied when fill_defaults=True (off by default: missing != "well-drained")
DEFAULTS = {"photoperiod": "day-neutral", "drainage": "well-drained"}


# ==========================================================================
# 4. LOAD  (atomic download, retries, cache expiry, stale-cache fallback)
# ==========================================================================
def _read_parquet(path_or_url) -> pd.DataFrame:
    try:
        return pd.read_parquet(path_or_url)
    except ImportError as e:
        raise ImportError(
            "Reading Parquet needs a engine: pip install pyarrow") from e


def _download(url: str, dest: Path, timeout: float, retries: int) -> pd.DataFrame:
    """Download to a temp file, validate it parses, then atomically move it."""
    tmp = dest.with_name(dest.name + ".part")
    last: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "ecocrop-loader/2.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp, \
                    open(tmp, "wb") as fh:
                shutil.copyfileobj(resp, fh)
            df = _read_parquet(tmp)          # raises if truncated/corrupt
            os.replace(tmp, dest)
            return df
        except ImportError:
            raise
        except Exception as e:               # network, HTTP, corrupt file
            last = e
            tmp.unlink(missing_ok=True)
            if attempt < retries:
                log(f"[download] attempt {attempt} failed ({e}); retrying...")
                time.sleep(2 * attempt)
    raise RuntimeError(f"download failed after {retries} attempts: {last}") from last


def load_ecocrop(url: str = ECOCROP_URL,
                 local_path: Path = LOCAL_CACHE,
                 force_download: bool = False,
                 max_age_days: Optional[float] = CACHE_MAX_AGE_DAYS,
                 offline: bool = False) -> pd.DataFrame:
    """Return the raw EcoCrop table, using/refreshing a local cache."""
    local_path = Path(local_path)
    cached = local_path.exists()
    fresh = False
    if cached and not force_download:
        age_days = (time.time() - local_path.stat().st_mtime) / 86400
        fresh = max_age_days is None or age_days <= max_age_days

    if cached and (offline or fresh):
        try:
            log(f"[load] using cached {local_path}")
            return _read_parquet(local_path)
        except ImportError:
            raise
        except Exception as e:
            if offline:
                raise
            log(f"[load] cache unreadable ({e}); re-downloading")

    if offline:
        raise FileNotFoundError(f"--offline set but no cache at {local_path}")

    log(f"[download] {url}")
    try:
        df = _download(url, local_path, DOWNLOAD_TIMEOUT, DOWNLOAD_RETRIES)
    except RuntimeError as e:
        if cached:
            log(f"[warn] {e}\n[warn] falling back to stale cache {local_path}")
            return _read_parquet(local_path)
        raise
    log(f"[cached] {local_path}  ({len(df)} rows, {len(df.columns)} columns)")
    return df


# ==========================================================================
# 5. COLUMN RESOLUTION
# ==========================================================================
def _norm_col(name: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(name).lower())


def resolve_columns(df: pd.DataFrame,
                    aliases: Dict[str, List[str]] = COLUMN_ALIASES
                    ) -> Dict[str, str]:
    """Return {internal_field: actual_dataframe_column}.

    Matching ignores case/spaces/underscores/hyphens; candidates are tried in
    order. Fields with no matching column are omitted.
    """
    by_norm: Dict[str, str] = {}
    for c in df.columns:
        by_norm.setdefault(_norm_col(c), c)
    resolved: Dict[str, str] = {}
    for field, candidates in aliases.items():
        for cand in candidates:
            hit = by_norm.get(_norm_col(cand))
            if hit is not None:
                resolved[field] = hit
                break
    return resolved


# ==========================================================================
# 6. VALUE CLEANING
# ==========================================================================
_LISTLIKE = (list, tuple, set, np.ndarray)


def _is_missing_scalar(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip().lower() in MISSING_TOKENS
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def as_list(v: Any) -> List[Any]:
    """Flatten any cell (scalar, list, tuple, set, numpy array, nested) into a
    list of cleaned, non-missing native Python scalars."""
    if isinstance(v, _LISTLIKE):
        items = v.tolist() if isinstance(v, np.ndarray) else list(v)
        out: List[Any] = []
        for x in items:
            out.extend(as_list(x))
        return out
    if _is_missing_scalar(v):
        return []
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, str):
        v = v.strip()
    return [v]


def clean_value(v: Any, list_handling: str = LIST_HANDLING):
    """Turn one cell into a plain Python value (None if missing)."""
    items = as_list(v)
    if isinstance(v, _LISTLIKE):
        if list_handling == "keep":
            return items or None
        if not items:
            return None
        if list_handling == "join":
            return "|".join(str(x) for x in items)
        return items[0]
    return items[0] if items else None


def _to_float(v: Any) -> Optional[float]:
    """First usable number in a cell; NaN/sentinels/garbage -> None."""
    for x in as_list(v):
        try:
            f = float(x)
        except (TypeError, ValueError):
            continue
        if math.isnan(f) or f in NUMERIC_SENTINELS:
            continue
        return f
    return None


def _clean_text(v: Any, list_handling: str = LIST_HANDLING) -> Optional[str]:
    items = [" ".join(str(x).split()) for x in as_list(v)]
    items = [x for x in items if x]
    if not items:
        return None
    return "|".join(items) if list_handling == "join" else items[0]


def _all_names(v: Any) -> Optional[str]:
    seen: List[str] = []
    for x in as_list(v):
        s = " ".join(str(x).split())
        if s and s not in seen:
            seen.append(s)
    return "|".join(seen) or None


def _norm_categories(v: Any, mapping: Dict[str, str]) -> Optional[str]:
    """Normalise every label in a cell; keep all, de-duplicated and sorted."""
    labels = set()
    for x in as_list(v):
        for part in re.split(r"[|;,]", str(x)):
            p = " ".join(part.lower().split())
            if p and p not in MISSING_TOKENS:
                labels.add(mapping.get(p, p))
    return "|".join(sorted(labels)) or None


def clean_dataframe(df: pd.DataFrame,
                    resolved: Dict[str, str],
                    fill_defaults: bool = False,
                    keep_extra: bool = False,
                    list_handling: str = LIST_HANDLING) -> pd.DataFrame:
    """Return a DataFrame with internal field names and cleaned values."""
    out = pd.DataFrame(index=df.index)

    for field, src in resolved.items():
        col = df[src]
        if field in FLOAT_FIELDS:
            out[field] = pd.to_numeric(col.map(_to_float), errors="coerce")
        elif field in INT_FIELDS:
            out[field] = (pd.to_numeric(col.map(_to_float), errors="coerce")
                          .round().astype("Int64"))
        elif field in CATEGORICAL_FIELDS:
            mapping = CATEGORY_MAPS.get(field, {})
            s = col.map(lambda v, m=mapping: _norm_categories(v, m))
            if fill_defaults and field in DEFAULTS:
                s = s.map(lambda x: x if x is not None else DEFAULTS[field])
            out[field] = s
        elif field in TEXT_FIELDS:
            out[field] = col.map(lambda v: _clean_text(v, list_handling))
            if field == "common_name":
                out["common_names"] = col.map(_all_names)
        else:
            out[field] = col.map(lambda v: clean_value(v, list_handling))

    if keep_extra:
        used = set(resolved.values())
        for c in df.columns:
            if c not in used:
                out[f"extra_{c}"] = df[c].map(
                    lambda v: clean_value(v, list_handling))
    return out


# ==========================================================================
# 7. QUALITY CHECKS
# ==========================================================================
ORDER_CHECKS = [
    ("tmin", "topmn", "topmx", "tmax"),
    ("rmin", "ropmn", "ropmx", "rmax"),
    ("ph_min", "ph_opt_min", "ph_opt_max", "ph_max"),
    ("gmin", "gmax"),
]
RANGE_CHECKS = {          # field: (lowest plausible, highest plausible)
    "tmin": (-60, 60), "tmax": (-60, 70), "topmn": (-60, 60), "topmx": (-60, 70),
    "ktmp": (-80, 60),
    "rmin": (0, 20000), "rmax": (0, 20000), "ropmn": (0, 20000), "ropmx": (0, 20000),
    "ph_min": (0, 14), "ph_max": (0, 14), "ph_opt_min": (0, 14), "ph_opt_max": (0, 14),
    "gmin": (1, 1500), "gmax": (1, 1500),
}


def add_quality_flags(clean: pd.DataFrame) -> pd.DataFrame:
    """Append `qc_issues` (text, None if clean) and `core_complete` (bool).

    Flags problems; it never silently "repairs" values.
    """
    issues: List[List[str]] = [[] for _ in range(len(clean))]
    pos = {idx: i for i, idx in enumerate(clean.index)}

    for field, (lo, hi) in RANGE_CHECKS.items():
        if field not in clean.columns:
            continue
        s = pd.to_numeric(clean[field], errors="coerce")
        for idx in clean.index[s.notna() & ((s < lo) | (s > hi))]:
            issues[pos[idx]].append(f"range:{field}")

    for chain in ORDER_CHECKS:
        cols = [c for c in chain if c in clean.columns]
        if len(cols) < 2:
            continue
        label = "order:" + "<=".join(cols)
        for idx, row in zip(clean.index, clean[cols].itertuples(index=False)):
            vals = [float(v) for v in row if pd.notna(v)]
            if any(a > b for a, b in zip(vals, vals[1:])):
                issues[pos[idx]].append(label)

    out = clean.copy()
    out["qc_issues"] = ["; ".join(x) if x else None for x in issues]

    have_core = pd.Series(True, index=out.index)
    for f in CORE_FIELDS:
        have_core &= out[f].notna() if f in out.columns else False
    core_bad = out["qc_issues"].fillna("").str.contains(
        r"order:tmin|range:(?:tmin|tmax|topmn|topmx|gmin)")
    out["core_complete"] = (have_core & ~core_bad).astype(bool)
    return out


# ==========================================================================
# 8. DEDUPE + FILTER + ONE-CALL PIPELINE
# ==========================================================================
def dedupe(clean: pd.DataFrame, how: str = "most_complete",
           key: str = "scientific_name") -> pd.DataFrame:
    """One row per species. how: 'most_complete' | 'first' | 'none'.

    Rows with no scientific name are kept as-is (never merged together).
    """
    if how == "none" or key not in clean.columns:
        return clean
    if how == "first":
        order = clean.index
    else:
        order = clean.notna().sum(axis=1).sort_values(
            ascending=False, kind="stable").index
    norm = clean.loc[order, key].map(
        lambda v: None if v is None or pd.isna(v) else str(v).strip().lower())
    dup = norm.duplicated() & norm.notna()
    dropped = clean.index.isin(order[dup.values])
    n = int(dropped.sum())
    if n:
        log(f"[dedupe] dropped {n} duplicate scientific names "
            f"(kept '{how}' record)")
    return clean[~dropped]


def filter_crops(clean: pd.DataFrame,
                 names: Optional[Iterable[str]] = None,
                 scientific_names: Optional[Iterable[str]] = None,
                 only_complete: bool = False) -> pd.DataFrame:
    """Filter by name substring (common or scientific), exact scientific
    name, and/or core completeness."""
    mask = pd.Series(True, index=clean.index)

    if names:
        pats = [n.lower() for n in names]
        hay = pd.Series("", index=clean.index)
        for col in ("scientific_name", "common_name", "common_names"):
            if col in clean.columns:
                hay = hay + " " + clean[col].fillna("").astype(str).str.lower()
        mask &= hay.map(lambda s: any(p in s for p in pats))

    if scientific_names:
        wanted = {s.lower() for s in scientific_names}
        if "scientific_name" in clean.columns:
            mask &= clean["scientific_name"].fillna("").str.lower().isin(wanted)

    if only_complete:
        mask &= clean["core_complete"]
    return clean[mask]


def prepare(raw: pd.DataFrame,
            fill_defaults: bool = False,
            keep_extra: bool = False,
            dedupe_how: str = "most_complete",
            verbose: bool = True) -> pd.DataFrame:
    """raw table -> mapped, cleaned, de-duplicated, quality-flagged table."""
    raw = raw.reset_index(drop=True)
    resolved = resolve_columns(raw)
    if "scientific_name" not in resolved and "common_name" not in resolved:
        raise RuntimeError(
            "No name column found. Columns present: "
            f"{list(raw.columns)}. Extend COLUMN_ALIASES.")
    if verbose:
        missing = [f for f in COLUMN_ALIASES if f not in resolved]
        if missing:
            log(f"[warn] unmapped fields (no matching column): {missing}")
        core_missing = [f for f in CORE_FIELDS if f not in resolved]
        if core_missing:
            log(f"[warn] CORE fields missing, no crop can be 'core_complete': "
                f"{core_missing}")
    clean = clean_dataframe(raw, resolved, fill_defaults, keep_extra)
    clean = dedupe(clean, dedupe_how)
    return add_quality_flags(clean)


def get_clean_ecocrop(names: Optional[Iterable[str]] = None,
                      scientific_names: Optional[Iterable[str]] = None,
                      only_complete: bool = False,
                      fill_defaults: bool = False,
                      keep_extra: bool = False,
                      dedupe_how: str = "most_complete",
                      **load_kwargs) -> pd.DataFrame:
    """One call: load -> clean -> dedupe -> flag -> filter."""
    clean = prepare(load_ecocrop(**load_kwargs), fill_defaults, keep_extra,
                    dedupe_how)
    return filter_crops(clean, names, scientific_names, only_complete)


# ==========================================================================
# 9. INSPECT / VALIDATE / LOOKUP / EXPORT
# ==========================================================================
def inspect(df: pd.DataFrame, n_sample: int = 2) -> None:
    """Print every raw column, how it maps, null %, and sample values."""
    resolved = resolve_columns(df)
    rev = {v: k for k, v in resolved.items()}
    print(f"\nEcoCrop raw table: {len(df)} rows, {len(df.columns)} columns\n")
    print(f"{'column':<26} {'dtype':<10} {'null%':>6}  {'maps to':<16} sample")
    print("-" * 96)
    for col in df.columns:
        sample = df[col].dropna().head(n_sample).tolist()
        s = repr(sample)
        s = s if len(s) <= 34 else s[:31] + "..."
        nullpct = 100 * df[col].map(lambda v: len(as_list(v)) == 0).mean()
        print(f"{col:<26} {str(df[col].dtype):<10} {nullpct:6.1f}  "
              f"{rev.get(col, '-'):<16} {s}")
    unmapped = [f for f in COLUMN_ALIASES if f not in resolved]
    print(f"\nInternal fields with no source column: {unmapped or 'none'}")


def quality_report(clean: pd.DataFrame) -> None:
    n = len(clean)
    print(f"\nRows (after de-duplication): {n}")
    print(f"core_complete (usable for modelling): "
          f"{int(clean['core_complete'].sum())}  "
          f"({100 * clean['core_complete'].mean():.0f}%)")

    print("\nField coverage (non-null):")
    for c in clean.columns:
        if c in ("qc_issues", "core_complete"):
            continue
        k = int(clean[c].notna().sum())
        print(f"  {c:<18} {k:>6}  {100 * k / n:5.1f}%")

    counts = Counter(i.strip() for s in clean["qc_issues"].dropna()
                     for i in s.split(";"))
    print("\nQuality issues:")
    if counts:
        for issue, k in counts.most_common():
            print(f"  {issue:<40} {k:>5}")
    else:
        print("  none")

    for f in sorted(CATEGORICAL_FIELDS):
        if f in clean.columns:
            vc = clean[f].value_counts().head(8)
            print(f"\n{f} values: " + ", ".join(f"{k}={v}" for k, v in vc.items()))


def lookup_crop(clean: pd.DataFrame, query: str) -> pd.DataFrame:
    """Exact scientific-name match first, else substring on any name."""
    q = query.strip().lower()
    if "scientific_name" in clean.columns:
        exact = clean[clean["scientific_name"].fillna("").str.lower() == q]
        if not exact.empty:
            return exact
    return filter_crops(clean, names=[q])


def print_lookup(clean: pd.DataFrame, query: str, limit: int = 3) -> None:
    hits = lookup_crop(clean, query)
    if hits.empty:
        print(f"[no match] {query}")
        return
    if len(hits) > limit:
        print(f"[{len(hits)} matches; showing {limit}. Others: "
              + ", ".join(hits['scientific_name'].dropna().iloc[limit:limit + 8])
              + (" ..." if len(hits) > limit + 8 else "") + "]")
    for _, row in hits.head(limit).iterrows():
        title = row.get("scientific_name") or row.get("common_name") or "?"
        print(f"\n{title}\n{'-' * len(str(title))}")
        for field, val in row.items():
            if field in ("scientific_name",) or pd.isna(val):
                continue
            print(f"  {field:<15} {val}")


def export_clean(df: pd.DataFrame, out_path: str,
                 names: Optional[List[str]] = None,
                 scientific_names: Optional[List[str]] = None,
                 only_complete: bool = False,
                 fmt: Optional[str] = None,
                 **prepare_kwargs) -> int:
    """Clean a RAW table, filter, and write csv/parquet/json by extension
    (or `fmt`). Returns the number of rows written."""
    clean = filter_crops(prepare(df, **prepare_kwargs),
                         names, scientific_names, only_complete)
    fmt = (fmt or Path(out_path).suffix.lstrip(".") or "csv").lower()
    if fmt == "csv":
        clean.to_csv(out_path, index=False)
    elif fmt == "parquet":
        clean.to_parquet(out_path, index=False)
    elif fmt == "json":
        clean.to_json(out_path, orient="records", indent=2)
    else:
        raise ValueError(f"unknown format '{fmt}' (use csv, parquet or json)")
    log(f"[exported] {len(clean)} rows -> {out_path}")
    return len(clean)


# ==========================================================================
# 10. CLI
# ==========================================================================
def main(argv: Optional[List[str]] = None) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--force-download", action="store_true")
    common.add_argument("--offline", action="store_true",
                        help="never touch the network; use the cache only")
    common.add_argument("--cache", type=Path, default=LOCAL_CACHE)
    common.add_argument("--url", default=ECOCROP_URL)
    common.add_argument("--max-age-days", type=float, default=None,
                        help="re-download if the cache is older than this")

    prep = argparse.ArgumentParser(add_help=False)
    prep.add_argument("--keep-duplicates", action="store_true",
                      help="don't collapse duplicate scientific names")
    prep.add_argument("--fill-defaults", action="store_true",
                      help="fill missing photoperiod/drainage with defaults "
                           "(off by default)")
    prep.add_argument("--keep-extra", action="store_true",
                      help="keep unmapped source columns as extra_<name>")

    parser = argparse.ArgumentParser(
        description="Pull, clean and validate the FAO EcoCrop database")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("inspect", parents=[common],
                   help="raw columns, null %%, and how they map")
    sub.add_parser("validate", parents=[common, prep],
                   help="data-quality report on the cleaned table")

    p_exp = sub.add_parser("export", parents=[common, prep],
                           help="export the cleaned table")
    p_exp.add_argument("--out", default="ecocrop_clean.csv")
    p_exp.add_argument("--format", choices=["csv", "parquet", "json"],
                       default=None, help="default: from file extension")
    p_exp.add_argument("--names", nargs="*", default=None,
                       help="case-insensitive substrings (common/scientific)")
    p_exp.add_argument("--scientific-names", nargs="*", default=None,
                       help="exact scientific names to keep")
    p_exp.add_argument("--only-complete", action="store_true",
                       help="only crops with valid core parameters")

    p_look = sub.add_parser("lookup", parents=[common, prep],
                            help="show one crop (scientific or common name)")
    p_look.add_argument("query")
    p_look.add_argument("--limit", type=int, default=3)

    args = parser.parse_args(argv)

    raw = load_ecocrop(url=args.url, local_path=args.cache,
                       force_download=args.force_download,
                       max_age_days=args.max_age_days, offline=args.offline)

    if args.command == "inspect":
        inspect(raw)
        return

    kw = dict(dedupe_how="none" if args.keep_duplicates else "most_complete",
              fill_defaults=args.fill_defaults, keep_extra=args.keep_extra)

    if args.command == "validate":
        quality_report(prepare(raw, **kw))
    elif args.command == "export":
        export_clean(raw, args.out, names=args.names,
                     scientific_names=args.scientific_names,
                     only_complete=args.only_complete, fmt=args.format, **kw)
    elif args.command == "lookup":
        print_lookup(prepare(raw, **kw), args.query, args.limit)


if __name__ == "__main__":
    main()