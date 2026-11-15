"""Data pullers: one file per dataset, all following the same rules.

  - location first: lat, lon in decimal degrees
  - dates as "YYYY-MM-DD" (or years for CropScape)
  - downloaded once, saved in source/databases/, read from disk after; refresh=True re-downloads
  - every function returns a pandas DataFrame

    from data_pullers import get_climate, get_soil, get_crop_history
    climate = get_climate(42.065, -93.73, "2015-01-01", "2024-12-31")
"""

from ._common import DATA_DIR, TEST_FIELD
from .FAO_EcoCrop_pull import get_crop_requirements
from .FAOSTAT_pull import find_country, get_country, get_crop_economics
from .NASA_POWER_pull import get_climate
from .NASA_SMAP_pull import get_soil_moisture
from .USDA_CropScape_pull import get_crop_history
from .USDA_SSURGO_pull import get_soil
from .US_ZipCode_pull import get_zip_location

__all__ = ["get_climate", "get_soil_moisture", "get_crop_history", "get_soil", "get_zip_location",
           "get_crop_requirements", "get_country", "get_crop_economics", "find_country",
           "TEST_FIELD", "DATA_DIR"]
