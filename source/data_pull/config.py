"""Shared settings for the data pullers."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Field:
    name: str
    lat: float
    lon: float


# Test field: a corn/soybean field in Story County, Iowa, ~7 km north-west of Ames.
# CropScape shows a clean corn <-> soybean alternation here from 2017 onwards,
# which makes it a good "existing rotation" baseline.
TEST_FIELD = Field(name="story_county_ia", lat=42.065, lon=-93.73)

# Where pulled data gets cached (CSV files). Contents are gitignored.
DATA_DIR = Path(__file__).resolve().parents[1] / "databases"

# Network timeout for every API call, in seconds.
TIMEOUT = 60
