# Field Shift: Adapting Farms with NASA Data

NASA Space Apps 2026 challenge. Give the tool a location and a date range; it pulls NASA, USDA and
FAO data for that spot, scores every rotation crop in FAO EcoCrop (several hundred, no hand-picked
list) against the field's climate and soil, prices them with FAOSTAT yields and farm prices for the
field's country, and recommends the **top 3 crop rotations** next to the field's **current
rotation**. For each one it explains why it was suggested, the evidence, the money, the benefits,
the information gaps, and the risks to check locally. It supports, and does not replace, farmer
judgement and local expertise.

## Quick start

```
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe source\demo.py                         # Iowa test field, last 10 years
.venv\Scripts\python.exe source\demo.py --lat 42.065 --lon -93.73 --start 2015-01-01 --end 2024-12-31 --priority build_soil
.venv\Scripts\python.exe source\demo.py --lat 51.45 --lon -2.58 --current wheat barley    # outside the US
.venv\Scripts\python.exe source\demo.py --previous corn         # what should follow corn?
.venv\Scripts\python.exe source\demo.py --must-grow rice soybean                # build a rotation around these
.venv\Scripts\python.exe source\demo.py --price corn=180 --cost corn=900        # your own price and cost (USD)
.venv\Scripts\python.exe source\demo.py --json result.json      # also save everything as JSON
```

Priorities: `balanced` (default), `save_water`, `build_soil`, `extra_income`.

## For the front end: two questions, two functions

```python
from backend import recommend_after_crop, recommend_around_crops   # with source/ on the Python path

# 1. "I just grew corn on this plot. What rotation should follow it?"
rec = recommend_after_crop(42.065, -93.73, "2015-01-01", "2024-12-31", last_crop="corn")

# 2. "I have to grow these one or two crops. Build a rotation around them."
rec = recommend_around_crops(32.617, 130.629, "2015-01-01", "2024-12-31", must_grow=["rice"])

rec.to_text()     # the full report as text
rec.to_dict()     # everything as JSON-safe dicts: field, recommended_rotations, economics, ...
```

Both take the same optional settings:

```python
priorities="balanced",            # or a dict of weights
current_rotation=None,            # e.g. ["corn", "soybean"]; default: from CropScape (US)
rotation_years=3, irrigated=False, use_smap=False,
local_prices={"corn": 180},       # the farmer's own prices, US dollars per tonne
costs={"corn": 900},              # the farmer's costs, US dollars per hectare
country=None,                     # for FAOSTAT prices, e.g. "Japan"; default: found from lat/lon
on_progress=print,                # status messages for a loading screen
```

`recommend(lat, lon, start_date, end_date, ...)` is the pipeline both call; it still works on its
own, with `previous_crop=` and `must_grow=` as optional settings.

Bad inputs raise `ValueError` with a plain message (e.g. "The date range must cover at least 12
months", or "sugarcane cannot be grown to harvest at this location in any month").

### Where the money figures come from

Income per hectare = average yield x price paid to farmers, both from FAOSTAT for the country the
field is in (average of the latest 5 years with data), in US dollars. A price from the farmer
replaces FAOSTAT's. FAOSTAT has no seed or other production costs, so income is before costs
unless the farmer enters a cost for that crop. Without costs, high-cost crops such as vegetables
look better than they are.

## How it works

```
front end / demo.py  ->  backend.recommend_after_crop() / recommend_around_crops()
   data_pullers/            fetch each dataset (saved to source/databases/ the first time)
   decision/field_profile   climate by month, soil in EcoCrop terms, trends, current rotation
   decision/crops           every rotation crop in EcoCrop and its needs (trees etc. filtered out)
   decision/economics       income per hectare of each crop in the field's country (FAOSTAT)
   decision/suitability     score every crop x planting month, 0-1; first cut by suitability x income
   decision/sequence        what can follow what
   decision/rotations       search rotations, rate on a report card, pick top 3, score current
   decision/report          why / evidence / benefits / gaps / risks, text report
```

| File | What it does |
|---|---|
| `source/backend.py` | `recommend_after_crop()`, `recommend_around_crops()` and the shared `recommend()` pipeline |
| `source/demo.py` | Command-line front end |
| `source/data_pullers/NASA_POWER_pull.py` | Daily climate (temperature, rain, humidity, sun, wind, soil wetness) |
| `source/data_pullers/NASA_SMAP_pull.py` | Daily satellite soil moisture (optional, needs a NASA Earthdata login) |
| `source/data_pullers/USDA_CropScape_pull.py` | What was grown on the field each year (US only) |
| `source/data_pullers/USDA_SSURGO_pull.py` | Soil: pH, texture, drainage, organic matter, slope... (US only) |
| `source/data_pullers/FAO_EcoCrop_pull.py` | What ~2,500 crops need (temperature, rain, pH, soil, season length) |
| `source/data_pullers/FAOSTAT_pull.py` | Farm prices and yields per country, and which country a point is in |
| `source/data_pullers/_common.py` | Settings, input checks, the shared "save it the first time" helper |
| `source/decision/field_profile.py` | Turns the raw data into one `FieldProfile` |
| `source/decision/crops.py` | Builds the crop list from EcoCrop: filters out trees, ornamentals and medicinals; reads family, uses and winter hardiness |
| `source/decision/economics.py` | Income per hectare from FAOSTAT (or the farmer's prices and costs), and the FAOSTAT-to-EcoCrop name table |
| `source/decision/suitability.py` | Scores each crop for each planting month (harvest or cover crop); first cut of the crop list |
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
| `get_crop_economics(country)` | country name or code | `refresh` | national yearly averages; no costs; first call downloads ~45 MB |
| `get_country(lat, lon)` | location | `refresh` | returns a dict (name, ISO code, FAOSTAT code), not a table |

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
| sequence | How well each harvest crop follows the crop before it (after a legume is best; same family is worst), including the crop the field grew last |
| water | Crops' rainfall needs compared with the field's rainfall (allowing for a falling trend) |
| income | Income per hectare in the field's country, on a log scale from the lowest to the highest earning crop; crops the field hasn't grown are discounted (unknown market) |

The overall score is a weighted sum of these, with weights set by the farmer's priority. Rotation
rules: no two harvest crops from the same family back to back; a cover crop is never followed by its
own family; one harvest crop a year where summers are short (two where 8+ months are warm); every
must-grow crop is in the rotation.

Which crops are considered: every EcoCrop plant except trees, plants that are only timber,
ornamental, medicinal or weeds, and perennials that cannot sit in a 1-4 year rotation. Harvest
crops must also have a known income (FAOSTAT or the farmer's price), be a crop the field already
grows, or be a must-grow crop. Cover crops are the plants EcoCrop labels "cover crop".

## Tests

```
.venv\Scripts\python.exe -m pytest -m "not live"     # offline, a few seconds
.venv\Scripts\python.exe -m pytest -m live           # real NASA/USDA services, needs internet
```

## Known limits
- Monthly time steps; real planting dates depend on the season, variety and machinery.
- EcoCrop ranges are for a whole species, not a local variety. Its winter-hardiness figures are
  cautious (e.g. rye to -18 degC), and its "cover crop" label includes plants few farmers would
  use, so check cover-crop suggestions locally.
- Prices and yields are national yearly averages, not local ones, and there are no costs unless
  the farmer enters them. Forage crops (hay) and cover crops have no FAOSTAT price.
- All money is in US dollars.
- NASA POWER is a ~50 km grid, and soil and crop history are US-only.
