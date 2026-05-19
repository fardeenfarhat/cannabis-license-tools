"""
Sub-task 4 — Zoning Overlay Finder
=====================================
Finds the zoning district definition(s) and map/GIS resources for cannabis
retail in a given NJ municipality.

Strategy (5-step):
  0. Prohibition short-circuit — skip everything if ordinance is opt-out
  1. Discovery pass (D1-D3) — run when allowed_zones is empty; infers zone
     names from zoning code / overlay / permitted-use searches
  2. Per-zone S1 — zoning code chapter (ecode360/municode) for definition
  3. Per-zone S2 — cannabis overlay ordinance (zone scope + allowed uses)
  4. Per-zone S3 — zoning map PDF URL (returned as link, not text-extracted)
  5. Per-zone S4 — GIS / parcel-viewer portal URL

LLM (gpt-4o-mini) extracts structured zone profile from S1/S2 text.
S3/S4 are URL-only (maps are not text-processed).
Results are SQLite-cached per (municipality, zone_name).

Returns dict:
  {
    found, reason,                             # top-level status
    zones: [                                   # one per zone
      {
        name, full_name,
        cannabis_retail_permitted,             # bool
        permitted_uses,                        # list[str]
        setbacks, min_lot_size, max_height,
        parking_requirement, buffers,
        source_url, confidence
      }
    ],
    cannabis_overlay: {exists, ordinance_number, url},  # or None
    zoning_map_url,                            # PDF map
    gis_portal_url,                            # interactive viewer
    zones_source,                              # "supplied" | "discovered" | "unknown"
    needs_foia,                                # bool
    foia_note,                                 # str, populated when needs_foia=True
    queries_tried,                             # list[str]
    confidence,                                # "high" | "medium" | "low"
  }
"""

import json
import os
import re
import sqlite3
from datetime import datetime, timezone

from deep_dive.firecrawl_utils import firecrawl_scrape_urls, firecrawl_search

MAX_TEXT = 10_000

# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS town_zoning (
    municipality  TEXT NOT NULL,
    zone_name     TEXT NOT NULL,
    extracted_json TEXT,
    found_at      TEXT,
    PRIMARY KEY (municipality, zone_name)
)
"""

_CREATE_META_TABLE = """
CREATE TABLE IF NOT EXISTS town_zoning_meta (
    municipality    TEXT PRIMARY KEY,
    overlay_json    TEXT,
    zoning_map_url  TEXT,
    gis_portal_url  TEXT,
    zones_source    TEXT,
    full_result_json TEXT,
    found_at        TEXT
)
"""


def _ensure_tables(con: sqlite3.Connection) -> None:
    con.execute(_CREATE_TABLE)
    con.execute(_CREATE_META_TABLE)
    con.commit()


def get_cached_zoning(con: sqlite3.Connection, town: str) -> dict | None:
    _ensure_tables(con)
    row = con.execute(
        "SELECT full_result_json FROM town_zoning_meta WHERE municipality = ?",
        (town,),
    ).fetchone()
    if row and row[0]:
        return json.loads(row[0])
    return None


def _cache_zoning(con: sqlite3.Connection, town: str, result: dict) -> None:
    _ensure_tables(con)
    now = datetime.now(timezone.utc).isoformat()
    overlay = result.get("cannabis_overlay") or {}
    con.execute(
        """
        INSERT INTO town_zoning_meta
            (municipality, overlay_json, zoning_map_url, gis_portal_url,
             zones_source, full_result_json, found_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(municipality) DO UPDATE SET
            overlay_json     = excluded.overlay_json,
            zoning_map_url   = excluded.zoning_map_url,
            gis_portal_url   = excluded.gis_portal_url,
            zones_source     = excluded.zones_source,
            full_result_json = excluded.full_result_json,
            found_at         = excluded.found_at
        """,
        (
            town,
            json.dumps(overlay),
            result.get("zoning_map_url", ""),
            result.get("gis_portal_url", ""),
            result.get("zones_source", ""),
            json.dumps(result),
            now,
        ),
    )
    con.commit()


# ---------------------------------------------------------------------------
# URL helpers — skip PDFs for text extraction, score for quality
# ---------------------------------------------------------------------------

_ZONING_URL_KEYWORDS = {
    "zoning", "zone", "land-use", "landuse", "gis", "parcel",
    "municipal-code", "municode", "ecode360", "cannabis",
}
_STALE_YEAR_RE = re.compile(r"/(20[01]\d)/")
_MAP_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"}

_SKIP_DOMAINS = {
    "nj.com", "tapinto", "patch.com", "facebook.com", "twitter.com",
    "instagram.com", "reddit.com", "linkedin.com",
    "legiscan.com", "njleg.state.nj.us", "assembly.state.nj.us",
    "senate.nj.gov", "trackbill.com", "openstates.org",
}


def _is_map_url(url: str) -> bool:
    return any(url.lower().endswith(ext) for ext in _MAP_EXTS)


def _skip_url(url: str) -> bool:
    lower = url.lower()
    return any(d in lower for d in _SKIP_DOMAINS)


def _zoning_url_score(url: str) -> int:
    u = url.lower()
    if u.endswith(".pdf"):
        return -50          # PDFs fine for map links, bad for text extraction
    score = 0
    if ".gov" in u:
        score += 4
    if "ecode360.com" in u or "municode.com" in u or "library.municode" in u:
        score += 5
    if any(kw in u for kw in _ZONING_URL_KEYWORDS):
        score += 3
    if "cannabis" in u:
        score += 2
    if _STALE_YEAR_RE.search(u):
        score -= 5
    return score


# ---------------------------------------------------------------------------
# LLM extraction — zone definition
# ---------------------------------------------------------------------------

def _llm_extract_zone(text: str, town: str, zone_name: str) -> dict | None:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        prompt = f"""You are analyzing a zoning code page for {town}, NJ.
Find information about the "{zone_name}" zoning district.
Focus on cannabis retail (Class 5 adult-use) permissions.

Text:
{text[:MAX_TEXT]}

Respond with JSON only:
{{
  "found": true or false,
  "name": "short zone code e.g. CM2, B-2, C-1",
  "full_name": "full district name",
  "cannabis_retail_permitted": true or false or null,
  "permitted_uses": ["list", "of", "principal", "permitted", "uses"],
  "conditional_uses": ["uses requiring a conditional use permit"],
  "setbacks": "front/side/rear setback requirements, e.g. '25ft front, 10ft side'",
  "min_lot_size": "e.g. '10,000 sq ft' or empty",
  "max_height": "e.g. '35 ft / 3 stories' or empty",
  "parking_requirement": "e.g. '1 space per 250 sq ft' or empty",
  "buffers": "distance requirements from schools/parks/etc, or empty",
  "text_excerpt": "first 400 characters of relevant zoning text",
  "confidence": "high, medium, or low"
}}"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=600,
        )
        result = json.loads(response.choices[0].message.content)
        if result.get("found"):
            return result
        return None
    except Exception as e:
        print(f"      [zoning-llm] error: {e}")
        return None


def _llm_extract_overlay(text: str, town: str) -> dict | None:
    """Extract cannabis overlay ordinance details."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        prompt = f"""You are analyzing a cannabis zoning overlay ordinance for {town}, NJ.

Text:
{text[:MAX_TEXT]}

If this describes a cannabis retail overlay zone or amends existing zones to
permit cannabis retail, extract details. Otherwise set found to false.

Respond with JSON only:
{{
  "found": true or false,
  "overlay_name": "e.g. Cannabis Retail Overlay Zone",
  "ordinance_number": "e.g. 2022-15 or empty",
  "adopted_date": "ISO date or empty",
  "zones_covered": ["list of base zones the overlay applies to"],
  "geographic_areas": ["street names, block ranges, or descriptive areas"],
  "allowed_uses": ["specific cannabis uses permitted"],
  "cap": "max number of licenses e.g. '2' or 'no cap'",
  "buffers": "distance requirements e.g. '500ft from schools'",
  "text_excerpt": "first 400 chars",
  "confidence": "high, medium, or low"
}}"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=600,
        )
        result = json.loads(response.choices[0].message.content)
        if result.get("found"):
            return result
        return None
    except Exception as e:
        print(f"      [zoning-llm-overlay] error: {e}")
        return None


def _llm_discover_zones(text: str, town: str) -> list[str]:
    """
    When allowed_zones is unknown, ask LLM to find which zone names
    cannabis retail is permitted in from raw text.
    Returns list of zone name strings, or [].
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return _keyword_discover_zones(text)
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        prompt = f"""You are analyzing a zoning code or cannabis ordinance for {town}, NJ.
Find which zoning districts or zones explicitly permit cannabis retail (Class 5 / adult-use dispensary).

Text:
{text[:MAX_TEXT]}

Respond with JSON only:
{{
  "zones_found": ["list of zone short codes or names, e.g. CM2, B-2, C-1, MX"],
  "confidence": "high, medium, or low"
}}
If no zone names are found, return {{"zones_found": [], "confidence": "low"}}"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=200,
        )
        result = json.loads(response.choices[0].message.content)
        return result.get("zones_found", [])
    except Exception as e:
        print(f"      [zoning-llm-discover] error: {e}")
        return _keyword_discover_zones(text)


# ---------------------------------------------------------------------------
# Keyword fallbacks
# ---------------------------------------------------------------------------

_ZONE_CODE_RE = re.compile(
    r"\b([A-Z]{1,3}-?\d{1,2}[A-Z]?)\b"          # B-2, CM2, C1, MX
    r"|\b((?:commercial|mixed.use|industrial|retail)\s+district)\b",
    re.I,
)
_CANNABIS_NEARBY_RE = re.compile(
    r"cannabis.{0,200}", re.I | re.DOTALL
)


def _keyword_discover_zones(text: str) -> list[str]:
    zones = set()
    for match in _CANNABIS_NEARBY_RE.finditer(text):
        block = match.group(0)
        for zone_m in _ZONE_CODE_RE.finditer(block):
            name = zone_m.group(1) or zone_m.group(2)
            if name:
                zones.add(name.upper().strip())
    return list(zones)


def _keyword_extract_zone(text: str, zone_name: str) -> dict:
    """Minimal zone extract when LLM unavailable."""
    cannabis_permitted = bool(re.search(
        rf"{re.escape(zone_name)}.{{0,500}}cannabis", text, re.I | re.DOTALL
    ))
    return {
        "found": True,
        "name": zone_name,
        "full_name": zone_name,
        "cannabis_retail_permitted": cannabis_permitted,
        "permitted_uses": [],
        "conditional_uses": [],
        "setbacks": "",
        "min_lot_size": "",
        "max_height": "",
        "parking_requirement": "",
        "buffers": "",
        "text_excerpt": text[:400],
        "confidence": "low",
    }


# ---------------------------------------------------------------------------
# GIS / map URL detectors
# ---------------------------------------------------------------------------

_GIS_KEYWORDS = re.compile(
    r"arcgis|mapgeo|gis\.(?:town|township|city|borough|village)|"
    r"parcel.?viewer|zoning.?viewer|property.?viewer",
    re.I,
)
_MAP_PDF_KEYWORDS = re.compile(
    r"zoning.?map|official.?map|zone.?map|land.?use.?map", re.I
)
# Reject non-zoning PDFs (subdivision plans, surveys, site plans, etc.)
_MAP_URL_REJECT_RE = re.compile(
    r"subdivision|survey|constru|site.?plan|preliminary|parcel|deed|easement|"
    r"BL\d|lot[-_]\d|block[-_]\d",
    re.I,
)


def _extract_map_and_gis_urls(results: list[dict]) -> tuple[str, str]:
    """
    Scan a list of Firecrawl result dicts for map PDF and GIS portal URLs.
    Returns (zoning_map_url, gis_portal_url).
    """
    map_url = ""
    gis_url = ""
    for r in results:
        url = r.get("url", "")
        title = r.get("title", "") + " " + r.get("description", "")
        if not map_url and (_is_map_url(url) or _MAP_PDF_KEYWORDS.search(title)):
            map_url = url
        if not gis_url and _GIS_KEYWORDS.search(url + " " + title):
            gis_url = url
        if map_url and gis_url:
            break
    return map_url, gis_url


# ---------------------------------------------------------------------------
# Discovery queries — run when allowed_zones is empty
# ---------------------------------------------------------------------------

def _discovery_queries(town: str) -> list[str]:
    return [
        f'"{town} NJ" cannabis zoning site:ecode360.com',
        f'"{town} NJ" "cannabis overlay" OR "cannabis retail zone" ordinance',
        f'"{town} NJ" cannabis "permitted use" zoning district',
    ]


def _run_discovery(town: str) -> tuple[list[str], str]:
    """
    Run D1-D3 queries, extract zone names.
    Returns (discovered_zone_names, best_source_url).
    """
    queries = _discovery_queries(town)
    for q in queries:
        print(f"      [zoning:discovery] {q}")
        try:
            results = firecrawl_search(q, limit=5)
        except Exception as e:
            print(f"      [zoning:discovery] search error: {e}")
            continue

        to_scrape, inline_text = [], {}
        for r in results:
            url = r.get("url", "")
            if not url or _skip_url(url) or _is_map_url(url):
                continue
            md = r.get("markdown", "")
            if md and len(md) > 200:
                inline_text[url] = md
            else:
                to_scrape.append(url)

        if to_scrape[:3]:
            try:
                scraped = firecrawl_scrape_urls(to_scrape[:3])
                inline_text.update(scraped)
            except Exception as e:
                print(f"      [zoning:discovery] scrape error: {e}")

        for url, text in inline_text.items():
            if not text or len(text) < 200:
                continue
            zones = _llm_discover_zones(text, town)
            if zones:
                print(f"      [zoning:discovery] found zones {zones} at {url}")
                return zones, url

    return [], ""


# ---------------------------------------------------------------------------
# Per-zone strategies
# ---------------------------------------------------------------------------

def _zone_queries_s1(town: str, zone_name: str) -> list[str]:
    """S1 — zoning code chapter."""
    return [
        f'"{town} NJ" "{zone_name}" zoning district site:ecode360.com',
        f'"{town} NJ" "{zone_name}" zoning district site:library.municode.com',
        f'"{town} NJ" "{zone_name}" zoning permitted uses',
    ]


def _zone_queries_s2(town: str, zone_name: str) -> list[str]:
    """S2 — cannabis overlay ordinance."""
    return [
        f'"{town} NJ" "cannabis overlay" "{zone_name}"',
        f'"{town} NJ" cannabis overlay ordinance zone',
    ]


def _zone_queries_s3(town: str, zone_name: str) -> list[str]:
    """S3 — zoning map PDF."""
    return [
        f'"{town} NJ" zoning map filetype:pdf',
        f'"{town} NJ" "{zone_name}" zoning map',
        f'"{town} NJ" official zoning map',
    ]


def _zone_queries_s4(town: str) -> list[str]:
    """S4 — GIS / parcel viewer."""
    return [
        f'"{town} NJ" GIS zoning viewer',
        f'"{town} NJ" parcel viewer zoning map',
        f'"{town} NJ" ArcGIS OR MapGeo zoning',
    ]


def _run_text_strategy(
    queries: list[str],
    label: str,
) -> tuple[str, str]:
    """
    Run queries, scrape, return (best_text, source_url).
    Returns ("", "") if nothing retrieved.
    """
    tried_urls: set[str] = set()
    scored_pages: list[tuple[int, str, str]] = []   # (score, url, text)

    for q in queries:
        print(f"      [zoning:{label}] {q}")
        try:
            results = firecrawl_search(q, limit=5)
        except Exception as e:
            print(f"      [zoning:{label}] search error: {e}")
            continue

        to_scrape, inline_text = [], {}
        for r in results:
            url = r.get("url", "")
            if not url or url in tried_urls or _skip_url(url) or _is_map_url(url):
                continue
            tried_urls.add(url)
            md = r.get("markdown", "")
            if md and len(md) > 200:
                inline_text[url] = md
            else:
                to_scrape.append(url)

        if to_scrape[:3]:
            try:
                scraped = firecrawl_scrape_urls(to_scrape[:3])
                inline_text.update(scraped)
            except Exception as e:
                print(f"      [zoning:{label}] scrape error: {e}")

        for url, text in inline_text.items():
            if not text or len(text) < 200:
                continue
            score = _zoning_url_score(url)
            scored_pages.append((score, url, text))

        if scored_pages:
            break   # stop after first query that yields anything

    if not scored_pages:
        return "", ""

    scored_pages.sort(key=lambda x: x[0], reverse=True)
    _, best_url, best_text = scored_pages[0]
    return best_text, best_url


def _run_url_strategy(
    queries: list[str],
    label: str,
    url_filter,
) -> str:
    """Run queries, return first URL matching url_filter. No text scraping."""
    for q in queries:
        print(f"      [zoning:{label}] {q}")
        try:
            results = firecrawl_search(q, limit=5)
        except Exception as e:
            print(f"      [zoning:{label}] search error: {e}")
            continue

        for r in results:
            url = r.get("url", "")
            if url and not _skip_url(url) and url_filter(url, r):
                print(f"      [zoning:{label}] found {url}")
                return url

    return ""


def _process_zone(
    town: str,
    zone_name: str,
    overlay_already_found: bool,
    ordinance: dict | None = None,
) -> tuple[dict, dict | None, str, str]:
    """
    Run S0-S4 for a single zone.
    S0: scrape the cached ordinance URL directly (fastest; bypasses ecode360 when
        the town hosts its own code).
    S1: ecode360 / municode chapter search.
    S2: cannabis overlay ordinance search.
    S3: zoning map PDF URL (URL-only, not text-extracted).
    S4: GIS / parcel viewer portal URL.
    Returns (zone_profile, overlay_info_or_None, map_url, gis_url).
    """
    zone_profile: dict = {}
    overlay_info: dict | None = None
    map_url = ""
    gis_url = ""

    # S0 — scrape cached ordinance URL directly
    # Many NJ towns host their own code rather than using ecode360/municode.
    # The ordinance that adopted the zone is the authoritative definition.
    if ordinance and ordinance.get("url"):
        ord_url = ordinance["url"]
        print(f"    [zoning:S0] zone '{zone_name}' — scraping ordinance directly")
        try:
            scraped = firecrawl_scrape_urls([ord_url])
            ord_text = scraped.get(ord_url, "") or ""
            if len(ord_text) > 200:
                extracted = _llm_extract_zone(ord_text, town, zone_name)
                if extracted:
                    extracted["source_url"] = ord_url
                    zone_profile = extracted
                    print(f"    [zoning:S0] zone profile: {extracted.get('confidence','?')} confidence")
                else:
                    zone_profile = _keyword_extract_zone(ord_text, zone_name)
                    zone_profile["source_url"] = ord_url
                # Try overlay from the same text (one scrape, two extractions)
                if not overlay_already_found:
                    ov = _llm_extract_overlay(ord_text, town)
                    if ov:
                        ov["url"] = ord_url
                        overlay_info = ov
                        overlay_already_found = True
                        print(f"    [zoning:S0] overlay found from ordinance text: "
                              f"{ov.get('overlay_name', '?')}")
        except Exception as e:
            print(f"    [zoning:S0] error: {e}")

    # S1 — zoning code chapter (skip if S0 gave high/medium confidence)
    s0_confidence = zone_profile.get("confidence", "none")
    if not zone_profile or s0_confidence == "low":
        print(f"    [zoning:S1] zone '{zone_name}' — code chapter")
        text, url = _run_text_strategy(_zone_queries_s1(town, zone_name), "S1")
        if text:
            extracted = _llm_extract_zone(text, town, zone_name)
            if extracted:
                extracted["source_url"] = url
                # Keep higher-confidence result
                conf_rank = {"high": 3, "medium": 2, "low": 1, "none": 0}
                if conf_rank.get(extracted.get("confidence", "low"), 0) >= \
                   conf_rank.get(s0_confidence, 0):
                    zone_profile = extracted
                if zone_profile.get("confidence") == "high":
                    print(f"    [zoning:S1] high-confidence zone profile found")
            elif not zone_profile:
                zone_profile = _keyword_extract_zone(text, zone_name)
                zone_profile["source_url"] = url

    # S2 — cannabis overlay (skip if already found in S0)
    if not overlay_already_found and not overlay_info:
        print(f"    [zoning:S2] zone '{zone_name}' — cannabis overlay")
        text_ov, url_ov = _run_text_strategy(_zone_queries_s2(town, zone_name), "S2")
        if text_ov:
            overlay_info = _llm_extract_overlay(text_ov, town)
            if overlay_info:
                overlay_info["url"] = url_ov
                print(f"    [zoning:S2] overlay found: {overlay_info.get('overlay_name', '?')}")

    # S3 — zoning map PDF (URL only, not scraped)
    # Require: PDF extension AND map keywords in title/description/URL
    # AND absence of subdivision/survey/construction keywords (false-positive rejection)
    print(f"    [zoning:S3] zone '{zone_name}' — zoning map PDF")
    map_url = _run_url_strategy(
        _zone_queries_s3(town, zone_name),
        "S3",
        lambda url, r: (
            _is_map_url(url)
            and _MAP_PDF_KEYWORDS.search(
                r.get("title", "") + " " + r.get("description", "") + " " + url
            )
            and not _MAP_URL_REJECT_RE.search(
                url + " " + r.get("title", "") + " " + r.get("description", "")
            )
        ),
    )

    # S4 — GIS / parcel viewer (URL only)
    print(f"    [zoning:S4] zone '{zone_name}' — GIS portal")
    gis_url = _run_url_strategy(
        _zone_queries_s4(town),
        "S4",
        lambda url, r: bool(_GIS_KEYWORDS.search(
            url + " " + r.get("title", "") + " " + r.get("description", "")
        )),
    )

    return zone_profile, overlay_info, map_url, gis_url


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def find_zoning(
    town: str,
    ordinance: dict,
    con: sqlite3.Connection,
    refresh: bool = False,
) -> dict:
    """Find zoning district definitions and map resources for cannabis retail.

    Args:
        town:      municipality name (e.g. "Upper Township")
        ordinance: result from find_ordinance() — used for allowed_zones,
                   is_prohibition, ordinance_number
        con:       SQLite connection for caching
        refresh:   if True, skip cache and re-run all searches

    Returns a dict with the full zoning profile.
    """

    # Step 0 — cache check
    if not refresh:
        cached = get_cached_zoning(con, town)
        if cached:
            print(f"      [zoning] cache hit for {town}")
            return cached

    # Step 0b — prohibition short-circuit
    if ordinance.get("is_prohibition"):
        result = {
            "found":             False,
            "reason":            "prohibition",
            "note":              f"{town} opted out — no zones apply",
            "zones":             [],
            "cannabis_overlay":  None,
            "zoning_map_url":    "",
            "gis_portal_url":    "",
            "zones_source":      "n/a",
            "needs_foia":        False,
            "foia_note":         "",
            "queries_tried":     [],
            "confidence":        "high",
        }
        _cache_zoning(con, town, result)
        return result

    queries_tried: list[str] = []

    # Step 1 — get zones (supplied or discovered)
    allowed_zones: list[str] = ordinance.get("allowed_zones") or []
    zones_source = "supplied"

    if not allowed_zones:
        print(f"    [zoning] allowed_zones missing — running discovery pass...")
        discovered, disc_url = _run_discovery(town)
        if discovered:
            allowed_zones = discovered
            zones_source = "discovered"
            queries_tried += _discovery_queries(town)
            print(f"    [zoning] discovered zones: {allowed_zones}")
        else:
            queries_tried += _discovery_queries(town)
            result = {
                "found":             False,
                "reason":            "zones_unknown",
                "zones":             [],
                "cannabis_overlay":  None,
                "zoning_map_url":    "",
                "gis_portal_url":    "",
                "zones_source":      "unknown",
                "needs_foia":        True,
                "foia_note": (
                    f"Request zoning officer confirm which zones permit cannabis "
                    f"retail under {ordinance.get('ordinance_number', 'the ordinance')} "
                    f"and provide the official zoning map."
                ),
                "queries_tried":     queries_tried,
                "confidence":        "low",
            }
            _cache_zoning(con, town, result)
            return result

    # Steps 2-5 — per-zone cascade (S1-S4)
    all_zones:    list[dict] = []
    overlay_info: dict | None = None
    map_url = ""
    gis_url = ""

    for zone_name in allowed_zones:
        print(f"\n    [zoning] processing zone: {zone_name}")
        profile, ov, m_url, g_url = _process_zone(
            town, zone_name,
            overlay_already_found=overlay_info is not None,
            ordinance=ordinance,
        )
        if profile:
            profile.setdefault("name", zone_name)
            all_zones.append(profile)
        if ov and not overlay_info:
            overlay_info = ov
        if m_url and not map_url:
            map_url = m_url
        if g_url and not gis_url:
            gis_url = g_url

    # Build overall confidence
    if not all_zones:
        confidence = "low"
    elif any(z.get("confidence") == "high" for z in all_zones):
        confidence = "high"
    elif any(z.get("confidence") == "medium" for z in all_zones):
        confidence = "medium"
    else:
        confidence = "low"

    found = bool(all_zones) or bool(overlay_info) or bool(map_url) or bool(gis_url)

    result = {
        "found":            found,
        "reason":           "ok" if found else "no_data",
        "zones":            all_zones,
        "cannabis_overlay": overlay_info,
        "zoning_map_url":   map_url,
        "gis_portal_url":   gis_url,
        "zones_source":     zones_source,
        "needs_foia":       not found,
        "foia_note": (
            ""
            if found
            else (
                f"Request zoning officer confirm permitted zones and provide "
                f"the official zoning map for cannabis retail in {town}."
            )
        ),
        "queries_tried":    queries_tried,
        "confidence":       confidence,
    }

    _cache_zoning(con, town, result)
    return result
