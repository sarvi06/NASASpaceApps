# Field Shift: Adapting Farms with NASA Data

NASA Space Apps 2026 challenge. Give the tool a location and a date range; it pulls NASA and USDA
data for that spot, scores ~36 field, cover and forage crops against the field's climate and soil,
and recommends the **top 3 crop rotations** next to the field's **current rotation**. For each one it
explains why it was suggested, the evidence, the benefits, the information gaps, and the risks to
check locally. It supports, and does not replace, farmer judgement and local expertise.

## Quick start

```
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe source\demo.py                         # Iowa test field, last 10 years
.venv\Scripts\python.exe source\demo.py --lat 42.065 --lon -93.73 --start 2015-01-01 --end 2024-12-31 --priority build_soil
.venv\Scripts\python.exe source\demo.py --lat 51.45 --lon -2.58 --current wheat barley    # outside the US
.venv\Scripts\python.exe source\demo.py --json result.json      # also save everything as JSON
```

Priorities: `balanced` (default), `save_water`, `build_soil`, `extra_income`.

## For the front end: one function

```python
from backend import recommend          # with source/ on the Python path

rec = recommend(42.065, -93.73, "2015-01-01", "2024-12-31",
                priorities="balanced",          # or a dict of weights
                current_rotation=None,          # e.g. ["corn", "soybean"]; default: from CropScape
                rotation_years=3, irrigated=False, use_smap=False,
                on_progress=print)              # status messages for a loading screen
rec.to_text()     # the full report as text
rec.to_dict()     # everything as JSON-safe dicts: field, current_rotation, recommended_rotations, ...
```

Bad inputs raise `ValueError` with a plain message (e.g. "The date range must cover at least 12 months").

## How it works

```
front end / demo.py  ->  backend.recommend()
   data_pullers/            fetch each dataset (saved to source/databases/ the first time)
   decision/field_profile   climate by month, soil in EcoCrop terms, trends, current rotation
   decision/crops           candidate crops and their needs (FAO EcoCrop)
   decision/suitability     score every crop x planting month, 0-1, with the limiting factor
   decision/rotations       search rotations, rate on a report card, pick top 3, score current
   decision/report          why / evidence / benefits / gaps / risks, text report
```

| File | What it does |
|---|---|
| `source/backend.py` | `recommend()`: the single entry point; routes all data to the decision scripts |
| `source/demo.py` | Command-line front end |
| `source/data_pullers/NASA_POWER_pull.py` | Daily climate (temperature, rain, humidity, sun, wind, soil wetness) |
| `source/data_pullers/NASA_SMAP_pull.py` | Daily satellite soil moisture (optional, needs a NASA Earthdata login) |
| `source/data_pullers/USDA_CropScape_pull.py` | What was grown on the field each year (US only) |
| `source/data_pullers/USDA_SSURGO_pull.py` | Soil: pH, texture, drainage, organic matter, slope... (US only) |
| `source/data_pullers/FAO_EcoCrop_pull.py` | What ~2,500 crops need (temperature, rain, pH, soil, season length) |
| `source/data_pullers/_common.py` | Settings, input checks, the shared "save it the first time" helper |
| `source/decision/field_profile.py` | Turns the raw data into one `FieldProfile` |
| `source/decision/crops.py` | The curated candidate crop list (family, role, value, winter hardiness) |
| `source/decision/suitability.py` | Scores each crop for each planting month (harvest or cover crop) |
| `source/decision/sequence.py` | What can follow what: banned sequences, and a 0-1 score for each crop hand-over |
| `source/decision/rotations.py` | Rotation search, report card, farmer priorities, top-3 picking, where to start after the last crop, current rotation |
| `source/decision/report.py` | Plain-English explanations, glossary, text report |

### Requesting data directly

Every puller works the same way: location first, then dates. It downloads the first time, reads the
saved copy after, and `refresh=True` downloads again. Each one returns a pandas DataFrame.

| Function | Needs | Optional | Limits |
|---|---|---|---|
| `get_climate(lat, lon, start_date, end_date)` | location, dates | `refresh` | worldwide, 1981 onwards |
| `get_soil_moisture(lat, lon, start_date, end_date)` | location, dates, Earthdata login | `product`, `refresh` | 2015-03-31 onwards; slow queue |
| `get_crop_history(lat, lon, start_year, end_year)` | location | years (default 2008 to last year), `refresh` | contiguous US |
| `get_soil(lat, lon)` | location | `refresh` | US (empty table elsewhere) |
| `get_crop_requirements()` | nothing | `refresh` | global table |

```python
from data_pullers import get_climate, get_soil
climate = get_climate(42.065, -93.73, "2015-01-01", "2024-12-31")
```

SMAP needs a free account from https://urs.earthdata.nasa.gov/. Set the `EARTHDATA_USERNAME` and
`EARTHDATA_PASSWORD` environment variables, then use `demo.py --smap`.

### The report card (each item scored 0 to 1)

| Item | Meaning |
|---|---|
| fit | How well each crop's EcoCrop needs match the field's NASA POWER climate and SSURGO soil |
| cover | Share of months with something growing (bare soil erodes and loses nutrients) |
| nitrogen | Legumes in the rotation (cover and forage legumes count fully, grain legumes half) |
| diversity | Number of plant families, which breaks pest and disease cycles |
| water | Crops' rainfall needs compared with the field's rainfall (allowing for a falling trend) |
| income | Rough relative value; crops the field hasn't grown are discounted (unknown market) |

The overall score is a weighted sum of these, with weights set by the farmer's priority. Rotation
rules: no two harvest crops from the same family back to back; a cover crop is never followed by its
own family; one harvest crop a year where summers are short (two where 8+ months are warm).

## Tests

```
.venv\Scripts\python.exe -m pytest -m "not live"     # offline, a few seconds
.venv\Scripts\python.exe -m pytest -m live           # real NASA/USDA services, needs internet
```

## Known limits
- Monthly time steps; real planting dates depend on the season, variety and machinery.
- EcoCrop ranges are for a whole species, not a local variety; winter hardiness and crop values
  are curated estimates.
- There's no market price data yet (USDA AMS Market News would be the next dataset to add).
- NASA POWER is a ~50 km grid, and soil and crop history are US-only.
