"""
Sub-task 6 — Attorney Finder
================================
Identifies the top 1-3 private-practice attorneys with the strongest track
record before THIS town's boards (planning board, ZBA, council) across ALL
practice areas. Cannabis experience is a bonus signal, not a filter.

Strategy (all run — no cascade):
  S1  Town solicitor / special counsel — identified and excluded from picks
  S2  Planning Board minutes (last 24mo) — attorney appearances + outcomes
  S3  ZBA minutes (last 24mo)           — attorney appearances + outcomes
  S4  Council minutes (last 24mo)       — reuses council_votes URL + fresh search
  S5  Town legal-notices page           — attorney/applicant pairs from nj_legal_notices.csv
  S6  Cannabis bonus                    — per-attorney NJ cannabis-matter search

Scoring (0-90, 10 reserved for Phase B political signals):
  Local appearances:   30  (6 pts each, capped)
  Local win rate:      20  (20 × wins/total, min 2 reps to count)
  Recency bonus:       10  (any appearance <12mo) / 5 (12-24mo)
  County appearances:  10  (Phase B — NJ Appellate Division)
  Cannabis bonus:      15  (5 × verified reps, capped at 3)
  Industry recognition: 5  (Phase B)
  Tier: A ≥70 / B 40-69 / C <40. Only A+B in top_picks.

2-tier cache:
  attorney_profiles — 30d TTL, keyed (name_slug, firm_slug), cross-town reusable
  town_attorneys    — 7d TTL, keyed by town

Risk controls:
  1. No LLM-only entries — every attorney needs ≥1 verifiable source URL
  2. Every appearance carries source_url
  3. Name dedupe: (last_name, first_initial, firm_normalized)
  4. Town solicitor always in town_solicitor field, never in top_picks
  5. Cannabis-rep claims: attorney name must appear verbatim in source text

Returns dict:
  {
    found, attorneys: [{
      name, firm, email, phone,
      appearances: [{board, matter, applicant, date, outcome, source_url}],
      this_town_wins, this_town_losses, this_town_win_rate,
      cannabis_experience, cannabis_reps, score, tier, sources, confidence
    }],
    top_picks: [{name, firm, email, score, why}],
    town_solicitor: {name, firm, role, conflict_note} | None,
    needs_foia, confidence, queries_tried
  }
"""

import csv
import json
import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from deep_dive.firecrawl_utils import firecrawl_scrape_urls, firecrawl_search

MAX_TEXT         = 10_000
PROFILE_TTL_DAYS = 30
TOWN_TTL_DAYS    = 7
LOOKBACK_YEARS   = 2

_LEGAL_NOTICES_CSV = Path(__file__).parent.parent.parent / "data" / "nj_legal_notices.csv"

# ---------------------------------------------------------------------------
# Domain filters
# ---------------------------------------------------------------------------

_SKIP_DOMAINS = {
    "nj.com", "tapinto", "patch.com", "facebook.com", "twitter.com",
    "instagram.com", "reddit.com", "linkedin.com", "youtube.com",
    "legiscan.com", "njleg.state.nj.us", "assembly.state.nj.us",
    "senate.nj.gov", "trackbill.com", "openstates.org",
    "avvo.com", "martindale.com", "justia.com", "lawyers.com",
}


def _skip(url: str) -> bool:
    u = url.lower()
    return any(d in u for d in _SKIP_DOMAINS)


# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

_CREATE_PROFILES = """
CREATE TABLE IF NOT EXISTS attorney_profiles (
    name_slug    TEXT NOT NULL,
    firm_slug    TEXT NOT NULL,
    profile_json TEXT,
    found_at     TEXT,
    PRIMARY KEY (name_slug, firm_slug)
)
"""

_CREATE_TOWN = """
CREATE TABLE IF NOT EXISTS town_attorneys (
    municipality     TEXT PRIMARY KEY,
    full_result_json TEXT,
    found_at         TEXT
)
"""


def _ensure_tables(con: sqlite3.Connection) -> None:
    con.execute(_CREATE_PROFILES)
    con.execute(_CREATE_TOWN)
    con.commit()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "-", s.lower().strip())[:60]


def _get_cached_town(con: sqlite3.Connection, town: str) -> dict | None:
    _ensure_tables(con)
    row = con.execute(
        "SELECT full_result_json, found_at FROM town_attorneys WHERE municipality = ?",
        (town,),
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        cached_at = datetime.fromisoformat(row[1])
    except (TypeError, ValueError):
        return None
    if datetime.now(timezone.utc) - cached_at > timedelta(days=TOWN_TTL_DAYS):
        return None
    return json.loads(row[0])


def _cache_town(con: sqlite3.Connection, town: str, result: dict) -> None:
    _ensure_tables(con)
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        """
        INSERT INTO town_attorneys (municipality, full_result_json, found_at)
        VALUES (?, ?, ?)
        ON CONFLICT(municipality) DO UPDATE SET
            full_result_json = excluded.full_result_json,
            found_at         = excluded.found_at
        """,
        (town, json.dumps(result), now),
    )
    con.commit()


def _get_cached_profile(con: sqlite3.Connection, name_slug: str, firm_slug: str) -> dict | None:
    row = con.execute(
        "SELECT profile_json, found_at FROM attorney_profiles WHERE name_slug = ? AND firm_slug = ?",
        (name_slug, firm_slug),
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        cached_at = datetime.fromisoformat(row[1])
    except (TypeError, ValueError):
        return None
    if datetime.now(timezone.utc) - cached_at > timedelta(days=PROFILE_TTL_DAYS):
        return None
    return json.loads(row[0])


def _cache_profile(con: sqlite3.Connection, name_slug: str, firm_slug: str, profile: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        """
        INSERT INTO attorney_profiles (name_slug, firm_slug, profile_json, found_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name_slug, firm_slug) DO UPDATE SET
            profile_json = excluded.profile_json,
            found_at     = excluded.found_at
        """,
        (name_slug, firm_slug, json.dumps(profile), now),
    )
    con.commit()


# ---------------------------------------------------------------------------
# Name normalization and dedup
# ---------------------------------------------------------------------------

_NAME_STOP = {
    "mr", "mrs", "ms", "dr", "jr", "sr", "ii", "iii", "iv",
    "esq", "attorney", "atty", "counsel", "counselor",
}


def _clean_name_parts(name: str) -> list[str]:
    parts = []
    for word in name.split():
        w = re.sub(r"[^a-z]", "", word.lower())
        if w and w not in _NAME_STOP and len(w) > 1:
            parts.append(w)
    return parts


def _name_key(name: str, firm: str) -> tuple[str, str, str]:
    """Return (last_name, first_initial, firm_normalized) for dedup keying."""
    parts = _clean_name_parts(name)
    last  = parts[-1] if parts else ""
    first = parts[0][0] if len(parts) > 1 else ""
    firm_n = re.sub(r"[^a-z0-9]", "", firm.lower())[:20]
    return (last, first, firm_n)


def _names_match(a: str, b: str, a_firm: str = "", b_firm: str = "") -> bool:
    """True if a and b are plausibly the same attorney."""
    a_parts = _clean_name_parts(a)
    b_parts = _clean_name_parts(b)
    if not a_parts or not b_parts:
        return False
    if a_parts[-1] != b_parts[-1]:
        return False
    a_first = a_parts[0][0] if len(a_parts) > 1 else ""
    b_first = b_parts[0][0] if len(b_parts) > 1 else ""
    if a_first and b_first and a_first != b_first:
        return False
    if a_firm and b_firm:
        af = re.sub(r"[^a-z0-9]", "", a_firm.lower())[:15]
        bf = re.sub(r"[^a-z0-9]", "", b_firm.lower())[:15]
        if af and bf and af != bf and not (af in bf or bf in af):
            return False
    return True


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _scrape_first_good(urls: list[str], min_len: int = 300) -> tuple[str, str]:
    if not urls:
        return "", ""
    try:
        scraped = firecrawl_scrape_urls(urls[:4])
        for url in urls:
            text = scraped.get(url, "")
            if text and len(text) >= min_len:
                return text, url
    except Exception as e:
        print(f"      [attorneys] scrape error: {e}")
    return "", ""


def _recent_years() -> list[str]:
    now = datetime.now(timezone.utc)
    return [str(now.year - i) for i in range(LOOKBACK_YEARS + 1)]


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _llm_extract_attorneys_from_minutes(
    text: str, town: str, board: str, source_url: str
) -> list[dict]:
    """Extract private attorney appearances from board meeting minutes."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return _keyword_extract_attorneys(text, board, source_url)
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        prompt = f"""You are reading {town}, NJ {board} board meeting minutes.

Extract PRIVATE ATTORNEYS who appeared REPRESENTING APPLICANTS or PARTIES before this board.
DO NOT include:
- The town solicitor, municipal attorney, or board attorney (they work for the town/board)
- State or county officials
- Engineers, planners, architects, or consultants

For each attorney, extract each distinct MATTER (application/case) as a separate entry.
Determine outcome: "approved", "denied", "withdrawn", "tabled", "pending", or "unknown".

Minutes text:
{text[:MAX_TEXT]}

JSON only — list ([] if none found):
[
  {{
    "name": "Full Name",
    "firm": "Law Firm Name or empty string",
    "matter": "brief description e.g. bulk variance, use variance, site plan",
    "applicant": "applicant/client name or empty",
    "outcome": "approved|denied|withdrawn|tabled|pending|unknown",
    "date_mentioned": "date string from the minutes or empty"
  }}
]"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=1200,
        )
        raw = json.loads(response.choices[0].message.content)
        items = raw if isinstance(raw, list) else next(
            (v for v in raw.values() if isinstance(v, list)), []
        )
        for item in items:
            item["source_url"] = source_url
            item["board"]      = board
        return [i for i in items if i.get("name") and len(i["name"].strip()) > 3]
    except Exception as e:
        print(f"      [attorneys] LLM extract error: {e}")
        return _keyword_extract_attorneys(text, board, source_url)


def _keyword_extract_attorneys(text: str, board: str, source_url: str) -> list[dict]:
    """Regex fallback: match 'Attorney John Smith appeared on behalf of...' patterns."""
    pattern = re.compile(
        r"(?:Attorney|Counsel|Esq\.?)\s+"
        r"([A-Z][a-zA-Z\-']+(?:\s+[A-Z][a-zA-Z\-']+){1,4})"
        r"(?:\s+(?:of|from)\s+([A-Z][a-zA-Z\s&,\.]+?))?"
        r"(?:\s+(?:appeared|represented|on behalf|presented))",
        re.I,
    )
    results = []
    for m in pattern.finditer(text):
        results.append({
            "name":          m.group(1).strip(),
            "firm":          (m.group(2) or "").strip(),
            "matter":        "",
            "applicant":     "",
            "outcome":       "unknown",
            "date_mentioned": "",
            "source_url":    source_url,
            "board":         board,
        })
    return results


def _llm_extract_solicitor(text: str, town: str) -> dict:
    """Extract the town solicitor / municipal attorney from a government page."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        m = re.search(
            r"(?:Town|Municipal|Borough|Township)\s+Solicitor[:\s]+"
            r"([A-Z][a-zA-Z\s\-'\.]+?)(?:\n|,|;|Esq)",
            text, re.I,
        )
        if m:
            return {"name": m.group(1).strip(), "firm": "", "role": "town solicitor"}
        return {}
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content":
                f"""Find the Town Solicitor, Municipal Attorney, or Special Counsel for {town}, NJ in this text.

{text[:5000]}

JSON only: {{"name": "...", "firm": "...", "role": "town solicitor|municipal attorney|special counsel|other"}}
Return empty strings if not found. Do not guess or invent names."""}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=150,
        )
        result = json.loads(response.choices[0].message.content)
        name = (result.get("name") or "").strip()
        return result if name and len(name) > 3 and name.lower() not in ("unknown", "n/a") else {}
    except Exception:
        return {}


_BUSINESS_ENTITY_RE = re.compile(
    r"\b(llc|inc\.?|corp\.?|ltd\.?|l\.p\.|llp|associates|development|"
    r"corporation|company|co\.|group|holdings|enterprises|properties|realty|"
    r"management|solutions|services|industries|technologies|ventures)\b",
    re.I,
)


def _looks_like_attorney(name: str, applicant: str) -> bool:
    """Return True only if name plausibly belongs to a licensed attorney (a person)."""
    if not name or len(name.strip()) < 4:
        return False
    # Company name indicators → not an attorney
    if _BUSINESS_ENTITY_RE.search(name):
        return False
    # Name identical to applicant → LLM filled attorney slot with applicant
    if applicant and name.strip().lower() == applicant.strip().lower():
        return False
    # Must look like a human name: at least two words, each starting uppercase
    parts = name.strip().split()
    if len(parts) < 2:
        return False
    if not all(p[0].isupper() for p in parts if p):
        return False
    return True


def _llm_extract_legal_notice_attorneys(text: str, town: str, source_url: str) -> list[dict]:
    """Extract attorney-applicant pairs from a legal notices page.

    Legal notices list the APPLICANT (company/person seeking variance) and sometimes
    their ATTORNEY (the licensed lawyer representing them). We want the attorney, not
    the applicant. The LLM prompt and post-filter enforce this distinction.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return []
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content":
                f"""Read these {town}, NJ legal notices and extract attorney-applicant pairs.
Look for variance applications, site plan appeals, ZBA hearings, board of adjustment notices.

IMPORTANT DISTINCTION:
- "applicant" = the business or person APPLYING for the variance/approval (e.g., "Smith LLC", "John Doe")
- "name" = the LICENSED ATTORNEY representing the applicant before the board — a human lawyer
  Do NOT put the applicant's name in the "name" field. If no attorney name appears, omit the entry.

{text[:MAX_TEXT]}

JSON only — list ([] if no attorney names found):
[
  {{
    "name": "licensed attorney's full personal name (First Last) — NOT the applicant company",
    "firm": "law firm name or empty",
    "applicant": "the applicant/client company or person name",
    "matter": "type of application e.g. use variance, bulk variance, site plan"
  }}
]
Exclude town solicitor, board attorney, and municipal officials.
If you cannot identify a human attorney name (only the applicant), return []."""}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=800,
        )
        raw = json.loads(response.choices[0].message.content)
        items = raw if isinstance(raw, list) else next(
            (v for v in raw.values() if isinstance(v, list)), []
        )
        for item in items:
            item["source_url"]     = source_url
            item["board"]          = "legal_notice"
            item["outcome"]        = "unknown"
            item["date_mentioned"] = ""
        # Post-filter: keep only entries whose "name" looks like a human attorney
        valid = [
            i for i in items
            if _looks_like_attorney(i.get("name", ""), i.get("applicant", ""))
        ]
        if len(items) > 0 and len(valid) == 0:
            print(f"      [attorneys:S5] {len(items)} entries dropped (all look like applicants, not attorneys)")
        return valid
    except Exception as e:
        print(f"      [attorneys] LLM legal notice error: {e}")
        return []


def _llm_cannabis_check(text: str, attorney_name: str) -> dict:
    """
    Verify cannabis experience for a named attorney.
    Risk control: attorney name must appear verbatim in source text before
    we even attempt LLM extraction — prevents hallucinated experience claims.
    """
    if attorney_name.lower() not in text.lower():
        return {"verified": False, "reps": 0, "notes": "name not in source"}

    has_cannabis_keyword = bool(
        re.search(r"\bcannabis\b|\bmarijuana\b|\bdispensary\b|\bcrc\b|\bnjrc\b", text, re.I)
    )
    if not has_cannabis_keyword:
        return {"verified": False, "reps": 0, "notes": ""}

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return {"verified": True, "reps": 1, "notes": "keyword match (no API key)"}

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content":
                f"""Does {attorney_name} appear in this text with evidence of NJ cannabis/marijuana legal work?

{text[:5000]}

JSON only: {{"verified": true/false, "reps": <integer count of distinct cannabis matters>, "notes": "brief note or empty"}}"""}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=120,
        )
        return json.loads(response.choices[0].message.content)
    except Exception:
        return {"verified": True, "reps": 1, "notes": "keyword match fallback"}


# ---------------------------------------------------------------------------
# Strategy S1 — Town solicitor identification
# ---------------------------------------------------------------------------

def s1_town_solicitor(town: str) -> dict:
    """Find and flag the town solicitor. Never placed in top_picks."""
    queries = [
        f'"{town} NJ" "town solicitor" OR "municipal attorney" site:.gov OR site:.nj.us',
        f'"{town} NJ" town solicitor attorney official government',
        f'"{town} NJ" "board attorney" OR "special counsel" governing body officials',
    ]
    tried: set[str] = set()
    for query in queries:
        print(f"      [attorneys:S1] {query}")
        try:
            results = firecrawl_search(query, limit=3)
        except Exception as e:
            print(f"      [attorneys:S1] search error: {e}")
            continue
        to_scrape = [
            r["url"] for r in results
            if r.get("url") and r["url"] not in tried and not _skip(r["url"])
        ]
        for url in to_scrape:
            tried.add(url)

        scraped_s1: dict[str, str] = {}
        if to_scrape[:3]:
            try:
                scraped_s1 = firecrawl_scrape_urls(to_scrape[:3])
            except Exception:
                pass

        for url, text in scraped_s1.items():
            if not text:
                continue
            info = _llm_extract_solicitor(text, town)
            name = (info.get("name") or "").strip()
            firm = (info.get("firm") or "").strip()
            if name and len(name) > 3:
                print(f"      [attorneys:S1] solicitor: {name} / {firm}")
                return {
                    "name":         name,
                    "firm":         firm,
                    "role":         info.get("role", "town solicitor"),
                    "source_url":   url,
                    "conflict_note": (
                        "Serves as town solicitor/municipal attorney — "
                        "conflict of interest for applicant representation."
                    ),
                }
    return {}


# ---------------------------------------------------------------------------
# Strategy S2 / S3 / S4 — Meeting minutes per board body
# ---------------------------------------------------------------------------

_BOARD_QUERY_TEMPLATES: dict[str, list[str]] = {
    "planning": [
        '"{town} NJ" "planning board" meeting minutes {years}',
        '"{town} NJ" planning board minutes attorney appeared represented',
    ],
    "zba": [
        '"{town} NJ" "zoning board of adjustment" OR "ZBA" meeting minutes {years}',
        '"{town} NJ" "board of adjustment" minutes attorney variance appeal',
    ],
    "council": [
        '"{town} NJ" governing body council minutes attorney {years}',
        '"{town} NJ" council meeting minutes "appeared" OR "represented" attorney',
    ],
}


def strategy_meeting_minutes(town: str, body: str) -> list[dict]:
    """
    Search and scrape meeting minutes for a given board body over the last
    LOOKBACK_YEARS. body: "planning" | "zba" | "council"
    Returns list of raw appearance dicts.
    """
    years_str  = " OR ".join(_recent_years())
    templates  = _BOARD_QUERY_TEMPLATES.get(body, _BOARD_QUERY_TEMPLATES["planning"])
    appearances: list[dict] = []
    tried: set[str] = set()

    for tmpl in templates:
        query = tmpl.format(town=town, years=years_str)
        print(f"      [attorneys:{body}] {query}")
        try:
            results = firecrawl_search(query, limit=3)
        except Exception as e:
            print(f"      [attorneys:{body}] search error: {e}")
            continue

        to_scrape = [
            r["url"] for r in results
            if r.get("url") and r["url"] not in tried and not _skip(r["url"])
        ]
        for url in to_scrape:
            tried.add(url)

        scraped: dict[str, str] = {}
        if to_scrape[:3]:
            try:
                scraped = firecrawl_scrape_urls(to_scrape[:3])
            except Exception as e:
                print(f"      [attorneys:{body}] scrape error: {e}")

        for url, text in scraped.items():
            if not text or len(text) < 200:
                continue
            # Quick gate: only process pages that mention attorneys
            if not re.search(
                r"\b(attorney|counsel|esquire|esq\.?|represented\s+by)\b", text, re.I
            ):
                continue
            print(f"      [attorneys:{body}] extracting from {url[:60]}...")
            found = _llm_extract_attorneys_from_minutes(text, town, body, url)
            if found:
                print(f"      [attorneys:{body}] {len(found)} appearances")
                appearances.extend(found)

    return appearances


# ---------------------------------------------------------------------------
# Strategy S5 — Legal-notices page
# ---------------------------------------------------------------------------

def _get_legal_notice_url(town: str) -> str:
    if not _LEGAL_NOTICES_CSV.exists():
        return ""
    try:
        with open(_LEGAL_NOTICES_CSV, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                muni = row.get("Municipality", "") or row.get("Agency/Entity Name", "")
                if town.lower() in muni.lower():
                    return row.get("Public Notice URL", "")
    except Exception:
        pass
    return ""


def s5_legal_notices(town: str) -> list[dict]:
    url = _get_legal_notice_url(town)
    if not url:
        return []
    print(f"      [attorneys:S5] {url}")
    try:
        scraped = firecrawl_scrape_urls([url])
        text = scraped.get(url, "")
    except Exception as e:
        print(f"      [attorneys:S5] scrape error: {e}")
        return []
    if not text or len(text) < 100:
        return []
    return _llm_extract_legal_notice_attorneys(text, town, url)


# ---------------------------------------------------------------------------
# Strategy S6 — Cannabis bonus per attorney
# ---------------------------------------------------------------------------

def s6_cannabis_bonus(name: str, firm: str) -> dict:
    """Search for verified NJ cannabis experience for one attorney."""
    queries = [
        f'"{name}" cannabis attorney NJ "planning board" OR "ZBA" OR "board of adjustment"',
        f'"{name}" NJ cannabis marijuana dispensary license application',
    ]
    if firm:
        queries.append(f'"{name}" "{firm}" cannabis marijuana NJ')

    for query in queries:
        print(f"      [attorneys:S6] {query}")
        try:
            results = firecrawl_search(query, limit=3)
        except Exception as e:
            print(f"      [attorneys:S6] search error: {e}")
            continue
        urls = [r["url"] for r in results if r.get("url") and not _skip(r["url"])]
        if not urls:
            continue
        try:
            scraped = firecrawl_scrape_urls(urls[:2])
        except Exception:
            continue
        for url, text in scraped.items():
            if not text:
                continue
            result = _llm_cannabis_check(text, name)
            if result.get("verified"):
                reps = result.get("reps", 1)
                print(f"      [attorneys:S6] {name}: verified ({reps} cannabis matter(s))")
                return result
    return {"verified": False, "reps": 0, "notes": ""}


# ---------------------------------------------------------------------------
# Aggregate appearances into per-attorney profiles
# ---------------------------------------------------------------------------

def _aggregate(appearances: list[dict], solicitor: dict) -> dict[tuple, dict]:
    """
    Merge all appearances into per-attorney dicts.
    Key: (last_name, first_initial, firm_normalized)
    Skips the town solicitor.
    """
    profiles: dict[tuple, dict] = {}
    solicitor_name = solicitor.get("name", "")

    for app in appearances:
        name = (app.get("name") or "").strip()
        firm = (app.get("firm") or "").strip()
        if not name or len(name) < 4:
            continue
        if solicitor_name and _names_match(name, solicitor_name):
            continue
        if re.match(r"^(unknown|placeholder|n/a|attorney|counsel|esq)$", name.lower()):
            continue

        key = _name_key(name, firm)
        if key not in profiles:
            profiles[key] = {
                "name":               name,
                "firm":               firm,
                "email":              "",
                "phone":              "",
                "appearances":        [],
                "this_town_wins":     0,
                "this_town_losses":   0,
                "cannabis_experience": False,
                "cannabis_reps":      0,
                "sources":            [],
                "confidence":         "low",
            }
        p = profiles[key]
        if len(name) > len(p["name"]):
            p["name"] = name
        if firm and not p["firm"]:
            p["firm"] = firm

        outcome = (app.get("outcome") or "unknown").lower()
        p["appearances"].append({
            "board":      app.get("board", ""),
            "matter":     app.get("matter", ""),
            "applicant":  app.get("applicant", ""),
            "date":       app.get("date_mentioned", ""),
            "outcome":    outcome,
            "source_url": app.get("source_url", ""),
        })
        if outcome == "approved":
            p["this_town_wins"] += 1
        elif outcome == "denied":
            p["this_town_losses"] += 1
        src = app.get("source_url", "")
        if src and src not in p["sources"]:
            p["sources"].append(src)

    return profiles


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _most_recent_date(appearances: list[dict]) -> datetime | None:
    latest = None
    for app in appearances:
        ds = app.get("date", "")
        if not ds:
            continue
        for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m/%d/%y"):
            try:
                dt = datetime.strptime(ds.strip(), fmt).replace(tzinfo=timezone.utc)
                if latest is None or dt > latest:
                    latest = dt
                break
            except ValueError:
                continue
    return latest


def _score(attorney: dict) -> int:
    now    = datetime.now(timezone.utc)
    total  = len(attorney["appearances"])
    wins   = attorney["this_town_wins"]
    losses = attorney["this_town_losses"]

    score = min(total * 6, 30)                         # local appearances, cap 30

    if wins + losses >= 2:                              # win rate, min 2 reps
        score += round(20 * wins / (wins + losses))

    recent = _most_recent_date(attorney["appearances"])
    if recent:
        months_ago = (now - recent).days / 30
        if months_ago <= 12:
            score += 10
        elif months_ago <= 24:
            score += 5

    if attorney.get("cannabis_experience"):             # cannabis bonus, cap 15
        score += min(attorney.get("cannabis_reps", 1) * 5, 15)

    return min(score, 90)


def _tier(score: int) -> str:
    if score >= 70:
        return "A"
    if score >= 40:
        return "B"
    return "C"


def _win_rate(attorney: dict) -> float:
    w = attorney["this_town_wins"]
    l = attorney["this_town_losses"]
    return round(w / (w + l), 2) if (w + l) > 0 else 0.0


def _why_string(attorney: dict) -> str:
    now    = datetime.now(timezone.utc)
    n      = len(attorney["appearances"])
    w      = attorney["this_town_wins"]
    l      = attorney["this_town_losses"]
    recent = _most_recent_date(attorney["appearances"])
    months = round((now - recent).days / 30) if recent else 999

    parts = [f"{n} board appearance{'s' if n != 1 else ''} in town"]
    if w + l >= 2:
        parts.append(f"{w}W-{l}L")
    if months <= 12:
        parts.append("active last 12 months")
    elif months <= 24:
        parts.append("active last 24 months")
    if attorney.get("cannabis_experience"):
        reps = attorney.get("cannabis_reps", 1)
        parts.append(f"NJ cannabis experience ({reps} matter{'s' if reps != 1 else ''})")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def find_attorneys(
    town: str,
    con: sqlite3.Connection,
    ordinance: dict | None = None,
    council_votes: dict | None = None,
) -> dict:
    """
    Find top 1-3 private-practice attorneys with the strongest track record
    before this town's boards across all practice areas.

    ordinance     — from sub-task 2 (reserved for future context use)
    council_votes — from sub-task 3 (reuses vote_source_url for S4)
    """
    _ensure_tables(con)

    cached = _get_cached_town(con, town)
    if cached is not None:
        n = len(cached.get("attorneys", []))
        print(f"      [attorneys] cache hit: {n} attorneys for {town}")
        return cached

    queries_tried: list[str] = []
    all_appearances: list[dict] = []

    # -------------------------------------------------------------------
    # S1: Identify town solicitor (excluded from picks, never top_picks)
    # -------------------------------------------------------------------
    print(f"  [attorneys] S1: identifying town solicitor...")
    solicitor = s1_town_solicitor(town)
    queries_tried.append("S1:solicitor")
    if solicitor.get("name"):
        print(f"  [attorneys] solicitor identified: {solicitor['name']}")
    else:
        print(f"  [attorneys] solicitor not found")

    # -------------------------------------------------------------------
    # S2: Planning board minutes
    # -------------------------------------------------------------------
    print(f"  [attorneys] S2: planning board minutes...")
    apps = strategy_meeting_minutes(town, "planning")
    print(f"  [attorneys] S2: {len(apps)} appearances")
    all_appearances.extend(apps)
    queries_tried.append("S2:planning_minutes")

    # -------------------------------------------------------------------
    # S3: ZBA minutes
    # -------------------------------------------------------------------
    print(f"  [attorneys] S3: ZBA / board of adjustment minutes...")
    apps = strategy_meeting_minutes(town, "zba")
    print(f"  [attorneys] S3: {len(apps)} appearances")
    all_appearances.extend(apps)
    queries_tried.append("S3:zba_minutes")

    # -------------------------------------------------------------------
    # S4: Council minutes — reuse sub-task 3 source if available, then search
    # -------------------------------------------------------------------
    print(f"  [attorneys] S4: council minutes...")
    if council_votes and council_votes.get("vote_source_url"):
        src_url = council_votes["vote_source_url"]
        print(f"      [attorneys:S4] reusing council_votes source: {src_url[:60]}")
        try:
            scraped = firecrawl_scrape_urls([src_url])
            text = scraped.get(src_url, "")
            if text and len(text) > 200:
                found = _llm_extract_attorneys_from_minutes(text, town, "council", src_url)
                all_appearances.extend(found)
                print(f"      [attorneys:S4] {len(found)} appearances from cached source")
        except Exception as e:
            print(f"      [attorneys:S4] reuse error: {e}")
    apps = strategy_meeting_minutes(town, "council")
    print(f"  [attorneys] S4: {len(apps)} appearances (fresh search)")
    all_appearances.extend(apps)
    queries_tried.append("S4:council_minutes")

    # -------------------------------------------------------------------
    # S5: Town legal-notices page
    # -------------------------------------------------------------------
    print(f"  [attorneys] S5: legal notices page...")
    apps = s5_legal_notices(town)
    print(f"  [attorneys] S5: {len(apps)} appearances")
    all_appearances.extend(apps)
    queries_tried.append("S5:legal_notices")

    # -------------------------------------------------------------------
    # Aggregate raw appearances into per-attorney profiles
    # -------------------------------------------------------------------
    print(f"  [attorneys] aggregating {len(all_appearances)} total appearances...")
    profiles = _aggregate(all_appearances, solicitor)
    print(f"  [attorneys] {len(profiles)} unique attorneys before scoring")

    # -------------------------------------------------------------------
    # S6: Cannabis bonus — run per unique attorney, profile cache first
    # -------------------------------------------------------------------
    print(f"  [attorneys] S6: cannabis bonus checks for {len(profiles)} attorneys...")
    queries_tried.append("S6:cannabis_bonus")
    for key, p in profiles.items():
        name_s = _slug(p["name"])
        firm_s = _slug(p["firm"])
        cached_profile = _get_cached_profile(con, name_s, firm_s)
        if cached_profile and "cannabis_experience" in cached_profile:
            p["cannabis_experience"] = cached_profile["cannabis_experience"]
            p["cannabis_reps"]       = cached_profile.get("cannabis_reps", 0)
            print(f"      [attorneys:S6] {p['name']}: profile cache hit")
            continue
        result = s6_cannabis_bonus(p["name"], p["firm"])
        p["cannabis_experience"] = result.get("verified", False)
        p["cannabis_reps"]       = result.get("reps", 0)
        _cache_profile(con, name_s, firm_s, {
            "name":                p["name"],
            "firm":                p["firm"],
            "cannabis_experience": p["cannabis_experience"],
            "cannabis_reps":       p["cannabis_reps"],
        })

    # -------------------------------------------------------------------
    # Score, rank, build output
    # -------------------------------------------------------------------
    scored: list[dict] = []
    for p in profiles.values():
        p["this_town_win_rate"] = _win_rate(p)
        p["score"]              = _score(p)
        p["tier"]               = _tier(p["score"])
        p["confidence"]         = (
            "high"   if len(p["sources"]) >= 3 else
            "medium" if len(p["sources"]) >= 1 else
            "low"
        )
        scored.append(p)

    # Risk control: drop anyone with no verifiable source URL
    scored = [p for p in scored if p["sources"]]
    scored.sort(key=lambda p: p["score"], reverse=True)

    top_picks = [
        {
            "name":  p["name"],
            "firm":  p["firm"],
            "email": p["email"],
            "score": p["score"],
            "why":   _why_string(p),
        }
        for p in scored
        if p["tier"] in ("A", "B")
    ][:3]

    found      = bool(scored)
    needs_foia = not found
    confidence = (
        "high"   if len(scored) >= 2 and scored[0]["confidence"] == "high" else
        "medium" if found else
        "low"
    )

    result = {
        "found":          found,
        "attorneys":      scored,
        "top_picks":      top_picks,
        "town_solicitor": solicitor if solicitor.get("name") else None,
        "needs_foia":     needs_foia,
        "confidence":     confidence,
        "queries_tried":  queries_tried,
    }

    _cache_town(con, town, result)
    return result
