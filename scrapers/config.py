"""
Backward-compatibility shim.
VA config now lives in scrapers/va/config.py.
CityConfig now lives in scrapers/types.py.
"""
from .types import CityConfig, Platform          # noqa: F401
from .va.config import (                         # noqa: F401
    KEYWORDS, START_DATE, END_DATE,
    CITIES, cities_for_platform,
)
