"""
Sub-task 2 — Ordinance Finder
==============================
Finds the cannabis retail ordinance for a given NJ municipality.

Strategy (short-circuits on strong hit):
  1. SQLite cache check (skipped when refresh=True)
  2. Firecrawl search → ecode360.com
  3. Firecrawl search → library.municode.com
  4. Firecrawl search → broad NJ cannabis ordinance query
  5. LLM extracts 13 structured fields from top candidates (gpt-4o-mini)
  6. Keyword/regex fallback if LLM unavailable
  7. Winner scored, cached, returned

Returns dict with keys:
  found, is_prohibition, url, title, ordinance_number, adopted_date,
  effective_date, license_classes, allowed_zones, cap, application_fee,
  annual_fee, buffers, hours, local_tax, text_excerpt, confidence,
  runners_up (if multiple candidates)
"""
import json
import os
import re
import sqlite3
from datetime import datetime, timezone

from deep_dive.firecrawl_utils import firecrawl_scrape_urls, firecrawl_search

MAX_TEXT = 10_000   # chars sent to LLM

# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS town_ordinances (
    municipality     TEXT PRIMARY KEY,
    ordinance_url    TEXT,
    ordinance_number TEXT,
    adopted_date     TEXT,
    is_prohibition   INTEGER DEFAULT 0,
    extracted_json   TEXT,
    found_at         TEXT
)
"""


def _ensure_table(con: sqlite3.Connection) -> None:
    con.execute(_CREATE_TABLE)
    con.commit()


def get_cached_ordinance(con: sqlite3.Connection, town: str) -> dict | None:
    _ensure_table(con)
    row = con.execute(
        "SELECT extracted_json FROM town_ordinances WHERE municipality = ?",
        (town,),
    ).fetchone()
    if row and row[0]:
        return json.loads(row[0])
    return None


def _cache_ordinance(con: sqlite3.Connection, town: str, result: dict) -> None:
    _ensure_table(con)
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        """
        INSERT INTO town_ordinances
            (municipality, ordinance_url, ordinance_number, adopted_date,
             is_prohibition, extracted_json, found_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(municipality) DO UPDATE SET
            ordinance_url    = excluded.ordinance_url,
            ordinance_number = excluded.ordinance_number,
            adopted_date     = excluded.adopted_date,
            is_prohibition   = excluded.is_prohibition,
            extracted_json   = excluded.extracted_json,
            found_at         = excluded.found_at
        """,
        (
            town,
            result.get("url", ""),
            result.get("ordinance_number", ""),
            result.get("adopted_date", ""),
            1 if result.get("is_prohibition") else 0,
            json.dumps(result),
            now,
        ),
    )
    con.commit()


# ---------------------------------------------------------------------------
# LLM extraction  (gpt-4o-mini — house pattern from intent_extractor.py)
# ---------------------------------------------------------------------------

def llm_extract_ordinance(text: str, town: str) -> dict | None:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        prompt = f"""You are analyzing a cannabis ordinance or municipal code page for {town}, NJ.

Extract the cannabis RETAIL (Class 5 / adult-use) ordinance details.
If this page is a prohibition or opt-out ordinance, still extract it and set is_prohibition to true.
If the page is not about a cannabis ordinance at all, set found to false.

Text:
{text[:MAX_TEXT]}

Respond with JSON only:
{{
  "found": true or false,
  "is_prohibition": true or false,
  "title": "full ordinance or chapter title",
  "ordinance_number": "e.g. 2022-31, or empty string",
  "adopted_date": "ISO date YYYY-MM-DD or plain date string, empty if not found",
  "effective_date": "ISO date or empty",
  "license_classes": ["Class 5 Retail"],
  "allowed_zones": ["zone names where retail cannabis is permitted"],
  "cap": "max number of retail establishments, e.g. '2', or 'no cap', or empty",
  "application_fee": "dollar amount, e.g. '$10,000', or empty",
  "annual_fee": "dollar amount or empty",
  "buffers": "distance requirements, e.g. '1000 ft from schools, 500 ft from parks', or empty",
  "hours": "allowed hours of operation, e.g. '9 AM – 10 PM', or empty",
  "local_tax": "local transfer tax rate, e.g. '2%', or empty",
  "text_excerpt": "first 500 characters of the actual ordinance text",
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
        print(f"      [LLM-ordinance] error: {e}")
        return None


# ---------------------------------------------------------------------------
# Keyword / regex fallback
# ---------------------------------------------------------------------------

_ORD_NUMBER_RE = re.compile(
    r"(?:ordinance|ord\.?)\s*(?:no\.?)?\s*(\d{4}[-–]\d+)", re.I
)
_DATE_RE = re.compile(
    r"(?:adopted|passed|approved|effective)[^\n]{0,40}"
    r"(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    re.I,
)
_TITLE_RE = re.compile(r"#{1,3}\s+(.+cannabis.+)", re.I)
_PROHIBITION_RE = re.compile(
    r"\bprohibit(?:s|ed|ion)?\s+cannabis\b"
    r"|\bopt(?:ed)?\s+out\b"
    r"|\bno\s+cannabis\s+(?:business|establishment|retail)\b",
    re.I,
)


def keyword_extract_ordinance(text: str, town: str) -> dict:
    title_match = _TITLE_RE.search(text)
    title = title_match.group(1).strip() if title_match else f"{town} Cannabis Ordinance"

    ord_match = _ORD_NUMBER_RE.search(text)
    ordinance_number = ord_match.group(1) if ord_match else ""

    date_match = _DATE_RE.search(text)
    adopted_date = date_match.group(0).strip() if date_match else ""

    return {
        "found":           True,
        "is_prohibition":  bool(_PROHIBITION_RE.search(text)),
        "title":           title,
        "ordinance_number": ordinance_number,
        "adopted_date":    adopted_date,
        "effective_date":  "",
        "license_classes": [],
        "allowed_zones":   [],
        "cap":             "",
        "application_fee": "",
        "annual_fee":      "",
        "buffers":         "",
        "hours":           "",
        "local_tax":       "",
        "text_excerpt":    text[:500],
        "confidence":      "low",
    }


# ---------------------------------------------------------------------------
# Scoring — picks the winner when we have multiple candidates
# ---------------------------------------------------------------------------

def _score(candidate: dict) -> float:
    score = {"high": 3.0, "medium": 2.0, "low": 1.0}.get(
        candidate.get("confidence", "low"), 1.0
    )
    if candidate.get("ordinance_number"):
        score += 1.0
    if candidate.get("adopted_date"):
        score += 1.0
    if candidate.get("allowed_zones"):
        score += 1.0
    if candidate.get("cap"):
        score += 0.5
    if candidate.get("application_fee"):
        score += 0.5
    return score


# ---------------------------------------------------------------------------
# Search queries — tried in order, short-circuit on high-confidence hit
# ---------------------------------------------------------------------------

def _queries(town: str) -> list[str]:
    return [
        f'"{town} NJ" cannabis ordinance site:ecode360.com',
        f'"{town} NJ" cannabis ordinance site:library.municode.com',
        f'"{town}" New Jersey cannabis retail ordinance Class 5',
        f'"{town} NJ" cannabis dispensary ordinance',
    ]


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def find_ordinance(
    town: str,
    con: sqlite3.Connection,
    refresh: bool = False,
) -> dict:
    """Find the cannabis retail ordinance for `town`.

    Returns a dict with all extracted fields.
    Returns {"found": False, ...} if nothing turns up.
    """
    # 1. Cache check
    if not refresh:
        cached = get_cached_ordinance(con, town)
        if cached:
            print(f"      [ordinance] cache hit: {cached.get('url', 'no URL')}")
            return cached

    # 2. Search each query, collect candidates, short-circuit early
    candidates: list[dict] = []
    tried_urls: set[str] = set()

    for query in _queries(town):
        print(f"      [ordinance] searching: {query}")
        try:
            results = firecrawl_search(query, limit=5)
        except Exception as e:
            print(f"      [ordinance] search error: {e}")
            continue

        # Pull out new URLs (and whatever markdown search already returned)
        to_scrape: list[str] = []
        inline_text: dict[str, str] = {}

        for r in results:
            url = r.get("url", "")
            if not url or url in tried_urls:
                continue
            tried_urls.add(url)
            md = r.get("markdown", "")
            if md and len(md) > 200:
                inline_text[url] = md          # search returned full content
            else:
                to_scrape.append(url)           # need a separate scrape

        # Fetch any URLs the search didn't inline (up to 3 per query)
        if to_scrape[:3]:
            print(f"      [ordinance] scraping {len(to_scrape[:3])} additional URLs...")
            try:
                scraped = firecrawl_scrape_urls(to_scrape[:3])
                inline_text.update(scraped)
            except Exception as e:
                print(f"      [ordinance] scrape error: {e}")

        # Extract from every page we now have text for
        for url, text in inline_text.items():
            if not text or len(text) < 200:
                continue
            extracted = llm_extract_ordinance(text, town) or keyword_extract_ordinance(text, town)
            if extracted:
                extracted["url"] = url
                candidates.append(extracted)

        # Short-circuit: stop if we already have a high-confidence hit
        if any(c.get("confidence") == "high" for c in candidates):
            print(f"      [ordinance] high-confidence hit -- stopping search early")
            break

    # 3. Pick winner (or build a not-found result)
    if not candidates:
        result = {
            "found":         False,
            "url":           "",
            "title":         "",
            "ordinance_number": "",
            "adopted_date":  "",
            "is_prohibition": False,
            "queries_tried": _queries(town),
            "note":          "No ordinance found — verify manually",
        }
    else:
        candidates.sort(key=_score, reverse=True)
        result = candidates[0]
        result["found"] = True
        if len(candidates) > 1:
            result["runners_up"] = [
                {
                    "url":             c.get("url", ""),
                    "ordinance_number": c.get("ordinance_number", ""),
                    "confidence":      c.get("confidence", ""),
                }
                for c in candidates[1:]
            ]

    # 4. Cache and return
    _cache_ordinance(con, town, result)
    return result
