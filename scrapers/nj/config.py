"""
NJ city/platform configuration — reads from nj_portals.csv at runtime.

Effective platform priority:
  detected_platform (from sweep) > platform (original CSV field)

Only rows with a URL and a recognized platform are returned.
"""

import csv
import os
from datetime import date, timedelta
from ..types import CityConfig, Platform

KEYWORDS = ["cannabis", "cannabis retail", "dispensary", "marijuana license"]

# 2-year window (NJ legalization is more recent than VA)
_today = date.today()
START_DATE = (_today - timedelta(days=730)).strftime("%Y-%m-%d")
END_DATE   = _today.strftime("%Y-%m-%d")

_PORTALS_CSV = os.path.join(
    os.path.dirname(__file__), "..", "..", "nj_cannabis", "data", "nj_portals.csv"
)

_PLATFORM_MAP = {
    "agendacenter": Platform.AGENDACENTER,
    "civicplus":    Platform.CUSTOM_PDF,    # NJ civicplus towns use GovOffice CMS — civic_scraper returns 0; treat as custom PDF crawl
    "custom_pdf":   Platform.CUSTOM_PDF,
    "legistar":     Platform.LEGISTAR,
    "civicclerk":   Platform.CIVICCLERK,
    "civicweb":     Platform.CIVICWEB,
    "iqm2":         Platform.IQM2,
    "municode":     Platform.MUNICODE,
}


def _effective_platform(row: dict) -> str:
    dp = row.get("detected_platform", "").strip()
    op = row.get("platform", "").strip()
    if dp and dp not in ("skip", "", "error", "unknown"):
        return dp
    if op and op not in ("unknown", ""):
        return op
    return ""


def load_cities(platform: Platform | None = None) -> list[CityConfig]:
    """Load NJ cities from the portals CSV, optionally filtered by platform."""
    cities: list[CityConfig] = []
    seen_urls: set[str] = set()

    with open(_PORTALS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = row.get("base_url", "").strip()
            if not url:
                continue

            plat_str = _effective_platform(row)
            if not plat_str or plat_str not in _PLATFORM_MAP:
                continue

            plat = _PLATFORM_MAP[plat_str]
            if platform is not None and plat != platform:
                continue

            # Deduplicate same URL under same platform (e.g. Lebanon Twp + Borough share a URL)
            key = (url, plat)
            if key in seen_urls:
                continue
            seen_urls.add(key)

            name = f"{row['municipality']} {row['type']}, {row['county']} Co."
            cities.append(CityConfig(name=name, platform=plat, url=url))

    return cities


def cities_for_platform(platform: Platform) -> list[CityConfig]:
    return load_cities(platform)
