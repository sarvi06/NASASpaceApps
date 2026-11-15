# Field Shift: Adapting Farms with NASA Data

NASA Space Apps 2026 challenge. Give the tool a US zip code (or a latitude and longitude) and a date
range; it pulls NASA, USDA and FAO data for that spot, scores every rotation crop in FAO EcoCrop (several hundred, no hand-picked
list) against the field's climate and soil, prices them with FAOSTAT yields and farm prices for the
field's country, and recommends the **top 3 crop rotations** next to the field's **current
rotation**. For each one it explains why it was suggested, the evidence, the money, the benefits,
the information gaps, and the risks to check locally. It supports, and does not replace, farmer
judgement and local expertise.

**Where it works: the contiguous United States (the 48 states).** Field-level soil (USDA SSURGO)
and crop history (USDA CropScape) only exist there, so other locations are refused with a plain
message rather than answered with half the checks missing.

## Quick start

```
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe source\demo.py                         # default test field, last 10 years
.venv\Scripts\python.exe source\demo.py --zip 50010             # the centre of a US zip code area
.venv\Scripts\python.exe source\demo.py --lat 42.065 --lon -93.73 --start 2015-01-01 --end 2024-12-31 --priority build_soil
.venv\Scripts\python.exe source\demo.py --current corn corn soybean          # your rotation, if CropScape has it wrong
.venv\Scripts\python.exe source\demo.py --previous corn         # what should follow corn?
.venv\Scripts\python.exe source\demo.py --must-grow rice soybean                # build a rotation around these
.venv\Scripts\python.exe source\demo.py --price corn=180 --yield corn=12.5 --cost corn=900   # your own figures (USD)
.venv\Scripts\python.exe source\demo.py --json result.json      # also save everything as JSON
```

Priorities: `balanced` (default), `save_water`, `build_soil`, `extra_income`.

## The app

```
.venv\Scripts\python.exe source\user_interface.py
```

- **Home page:** the plots are side bars on the left, 5 to start with. "Add plot" asks for a name
  and a size and stops at 10. Plots are saved in `source/databases/gui/plots.json`.
- **Click a plot** to open it. Set its size (hectares) and last rotation at the top. For its
  location, type the zip code and press **Find location**: the latitude and longitude of the
  centre of that zip area are filled in. That point is often a town or woodland, and soil and
  crop history are looked up at one exact point, so change the two numbers to the field's own
  position if you know it. Press Save, then use the tabs:
  - **Budget** - what you can spend on growing costs a year for the whole plot; needs the cost per
    hectare of at least one crop you know.
  - **Crop planting** - one or two crops you want to grow; rotations are built around them.
  - **Rotation** - the best rotations for the plot, following its last crop if it is filled in.
- Every tab has the same settings row, an optional "Your numbers" table (your own price, yield and
  cost per crop) and a results box. Runs happen in the background, so the window stays usable.

**Adding a tab:** write a small `BaseTab` subclass in `source/gui/tabs/` (`rotation.py` is the
smallest example) and add it to `TABS` in `source/gui/tabs/__init__.py`.

| File | What it does |
|---|---|
| `source/user_interface.py` | Home page: window, side bar, and the open plot |
| `source/gui/theme.py` | Colours, fonts and cursor |
| `source/gui/plots.py` | The plots and saving them (no tkinter) |
| `source/gui/home.py` | Side bar of plot buttons, "Add plot" |
| `source/gui/plot_view.py` | One plot: its details and its tabs |
| `source/gui/runner.py` | Runs a back-end call in the background |
| `source/gui/tabs/` | `base.py` (what every tab shares), `budget.py`, `crops.py`, `rotation.py` |

## For the front end: three questions, three functions

```python
from backend import recommend_after_crop, recommend_around_crops   # with source/ on the Python path

# 1. "I just grew corn on this plot. What rotation should follow it?"
rec = recommend_after_crop(42.065, -93.73, "2015-01-01", "2024-12-31", last_crop="corn")

# 2. "I have to grow these one or two crops. Build a rotation around them."
rec = recommend_around_crops(34.75, -91.5, "2015-01-01", "2024-12-31", must_grow=["rice"])

# 3. "I can spend $9,000 a year on this 12 ha plot. What can I afford?"
#    (from backend import recommend_within_budget; needs at least one crop's cost)
rec = recommend_within_budget(42.065, -93.73, "2015-01-01", "2024-12-31", budget_usd=9000,
                              plot_size_ha=12, farm_numbers={"corn": {"cost": 900}})

rec.to_text()     # the full report as text
rec.to_dict()     # everything as JSON-safe dicts: field, recommended_rotations, economics, ...
```

All three take the same optional settings:

```python
priorities="balanced",            # or a dict of weights
current_rotation=None,            # e.g. ["corn", "soybean"]; default: from CropScape (US)
rotation_years=3, irrigated=False, use_smap=False,
farm_numbers={"corn": {"price": 180, "yield": 12.5, "cost": 900}},
                                  # the farmer's own figures, each optional: price in US dollars
                                  # per tonne, yield in tonnes per hectare, cost in US dollars per hectare
place=None,                       # a name for the spot, shown in the report, e.g. "Ames, Iowa (zip 50010)"
on_progress=print,                # status messages for a loading screen
```

`recommend(lat, lon, start_date, end_date, ...)` is the pipeline both call; it still works on its
own, with `previous_crop=` and `must_grow=` as optional settings.

The location is always a latitude and longitude. To start from a zip code:

```python
from data_pullers import get_zip_location
spot = get_zip_location("50010")   # {"zip", "place": "Ames", "state": "Iowa", "state_code", "lat", "lon"}
rec = recommend(spot["lat"], spot["lon"], "2015-01-01", "2024-12-31")
```

Bad inputs raise `ValueError` with a plain message (e.g. "The date range must cover at least 12
months", "sugarcane cannot be grown to harvest at this location in any month", or "Latitude 51.45,
longitude -2.58 is outside the contiguous United States").

### Where the money figures come from

All of it is in `source/decision/economics.py`, which builds one `Economy` object; no other
decision module reads prices.

- **Income per hectare** = average yield x price paid to farmers, both from FAOSTAT for the
  United States (average of the latest 5 years with data), in US dollars. The farmer's own price
  or yield replaces FAOSTAT's; with both, a crop FAOSTAT does not cover (e.g. alfalfa hay) can be
  priced. A missing local price is estimated from the world median at the country's price level.
- **Typical hectare**: the area-weighted average income of everything the country grows (about
  $2,400 in the US). Income is scored against it: 0.5 = typical, 1 = ten times
  typical. A rotation is scored once, on its real dollars per hectare per year.
- **Local market**: the crop's share of the country's harvested area. FAOSTAT has no costs, but
  what farmers actually plant shows what pays after costs and what can be sold.
- **Trusted income**: income above the typical hectare counts only as far as the crop is grown
  (`typical x (income / typical) ^ market`). US tomatoes show 46 times the typical income on 0.1%
  of the land, which points to costs or market limits FAOSTAT cannot show. The report prints both
  the full estimate and the part that was counted. A crop the farmer gave a price or a cost for
  is trusted in full.
- **Costs**: FAOSTAT has none. If the farmer enters costs for some crops, the other crops are
  assumed to cost the same share of their income (the median share entered), so profit is
  compared with profit. With no costs entered, everything is income before costs.

## How it works

```
front end / demo.py  ->  backend.recommend_after_crop() / recommend_around_crops()
   data_pullers/            fetch each dataset (saved to source/databases/ the first time)
   decision/field_profile   climate by month, soil in EcoCrop terms, trends, current rotation
   decision/crops           every rotation crop in EcoCrop and its needs (trees etc. filtered out)
   decision/economics       one Economy: what each crop earns and how widely it is grown (FAOSTAT)
   decision/suitability     score every crop x planting month, 0-1; first cut ranked by the Economy
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
| `source/data_pullers/FAOSTAT_pull.py` | Farm prices and yields per country (the tool uses the United States) |
| `source/data_pullers/US_ZipCode_pull.py` | Where a US zip code is: place name, state, latitude and longitude of its centre |
| `source/data_pullers/_common.py` | Settings, input checks, the shared "save it the first time" helper |
| `source/decision/field_profile.py` | Turns the raw data into one `FieldProfile` |
| `source/decision/crops.py` | Builds the crop list from EcoCrop: filters out trees, ornamentals and medicinals; reads family, uses and winter hardiness |
| `source/decision/economics.py` | The `Economy`: income per hectare, typical hectare, local market, trusted income, cost sharing |
| `source/decision/data/faostat_to_ecocrop.csv` | Name table between FAOSTAT crop items and EcoCrop plants |
| `source/decision/suitability.py` | Scores each crop for each planting month (harvest or cover crop); first cut of the crop list by a rank it is given |
| `source/decision/sequence.py` | What can follow what: banned sequences, and a 0-1 score for each crop hand-over |
| `source/decision/rotations.py` | Rotation search, report card, farmer priorities, top-3 picking, where to start after the last crop, current rotation |
| `source/decision/report.py` | Plain-English explanations, glossary, text report |

### Requesting data directly

Every puller works the same way: location first, then dates. It downloads the first time, reads the
saved copy after, and `refresh=True` downloads again. Each one returns a pandas DataFrame.

| Function | Needs | Optional | Limits |
|---|---|---|---|
| `get_zip_location(zip_code)` | a US zip code | `refresh` | returns a dict; the point is the centre of the zip area, not a field |
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
| income | The rotation's trusted income per hectare per year against the country's typical hectare (0.5 = typical, 1 = ten times typical) |
| market | How widely the rotation's harvest crops are grown in the field's country (share of harvested area, log scale) |

The overall score is a weighted sum of these, with weights set by the farmer's priority. Rotation
rules: no two harvest crops from the same family back to back; a cover crop is never followed by its
own family; one harvest crop a year where summers are short (two where 8+ months are warm); every
must-grow crop is in the rotation.

Which crops are considered: every EcoCrop plant except trees, plants that are only timber,
ornamental, medicinal or weeds, and perennials that cannot sit in a 1-4 year rotation. Harvest
crops must also have something known to sell them for (a FAOSTAT price, here or as a world
estimate, or the farmer's own), be a crop the field already grows, or be a must-grow crop. A crop
not grown in the country can be suggested, but starts with a market score of 0. Cover crops are
the plants EcoCrop labels "cover crop".

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
- Prices and yields are national yearly averages, not local ones, unless the farmer enters their
  own. There are no costs unless the farmer enters them; "trusted income" is an inference from
  what farmers plant, not a measured cost.
- Forage crops (hay) and cover crops have no FAOSTAT price; hay needs the farmer's price and yield.
- One FAOSTAT item can price several similar crops (wheat and durum wheat, cauliflower and broccoli).
- All money is in US dollars.
- NASA POWER is a ~50 km grid.
- Contiguous United States only: soil and crop history do not exist elsewhere in this form.
- A zip code gives the centre of its area, not a field. Soil and crop history describe that one
  point until the latitude and longitude are moved onto the field.
