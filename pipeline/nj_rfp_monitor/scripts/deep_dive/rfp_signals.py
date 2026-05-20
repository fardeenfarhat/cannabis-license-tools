"""
Sub-task 5 — RFP Signal Check
================================
Five-strategy cascade that gathers the complete picture of cannabis RFP /
license activity for a town — not just live RFPs.

Strategy:
  S1  NJ CRC license database     -> awarded license records (authoritative)
  S2  Town RFP / bids pages       -> live + past RFPs (reuses seed URLs + search)
  S3  Council agendas             -> upcoming votes / amendments
  S4  NJ bid aggregator portals   -> bidnetdirect, gov.deals, opengov
  S5  News coverage (whitelist)   -> litigation, award announcements

LLM categorizes each page into one of:
  LIVE_RFP | ANTICIPATED_WINDOW | RECENT_AWARDS | MORATORIUM |
  ORDINANCE_AMENDMENT | LITIGATION | PAST_RFP | NONE

Cap math: combines ordinance.cap + S1 awards -> {cap, awarded, slots_open, saturated}

Cache TTL: 24 hours (RFP signals are time-sensitive — stale cache is worse than refetch).

Returns dict:
  {
    found, signals, awarded_licenses, cap_status, next_action_date,
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

MAX_TEXT          = 10_000
CACHE_TTL_HOURS   = 24

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SEED_FILE = Path(__file__).parent.parent.parent / "data" / "rfp_seed_urls.csv"


# ---------------------------------------------------------------------------
# Domain filters
# ---------------------------------------------------------------------------

# News allowlist — only honored inside S5; everywhere else news domains skip.
_NEWS_ALLOWLIST = {
    "nj.com", "tapinto.net", "patch.com", "njbiz.com",
    "northjersey.com", "njspotlight.com", "njherald.com",
    "njcannabisinsider.biz", "njcannabis.business",
    "app.com",          # Asbury Park Press
    "courierpostonline.com",
}

# Always skip — social, state legislature trackers, video
_SKIP_DOMAINS = {
    "facebook.com", "twitter.com", "instagram.com", "reddit.com",
    "linkedin.com", "youtube.com", "tiktok.com",
    "legiscan.com", "njleg.state.nj.us", "assembly.state.nj.us",
    "senate.nj.gov", "trackbill.com", "openstates.org",
}


def _skip(url: str, allow_news: bool = False) -> bool:
    u = url.lower()
    if any(d in u for d in _SKIP_DOMAINS):
        return True
    if not allow_news and any(d in u for d in _NEWS_ALLOWLIST):
        return True
    return False


# ---------------------------------------------------------------------------
# SQLite cache (with TTL)
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS town_rfp_signals (
    municipality     TEXT PRIMARY KEY,
    full_result_json TEXT,
    found_at         TEXT
)
"""


def _ensure_table(con: sqlite3.Connection) -> None:
    con.execute(_CREATE_TABLE)
    con.commit()


def get_cached_signals(con: sqlite3.Connection, town: str) -> dict | None:
    _ensure_table(con)
    row = con.execute(
        "SELECT full_result_json, found_at FROM town_rfp_signals WHERE municipality = ?",
        (town,),
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        cached_at = datetime.fromisoformat(row[1])
    except (TypeError, ValueError):
        return None
    if datetime.now(timezone.utc) - cached_at > timedelta(hours=CACHE_TTL_HOURS):
        return None
    return json.loads(row[0])


def _cache_signals(con: sqlite3.Connection, town: str, result: dict) -> None:
    _ensure_table(con)
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        """
        INSERT INTO town_rfp_signals (municipality, full_result_json, found_at)
        VALUES (?, ?, ?)
        ON CONFLICT(municipality) DO UPDATE SET
            full_result_json = excluded.full_result_json,
            found_at         = excluded.found_at
        """,
        (town, json.dumps(result), now),
    )
    con.commit()


# ---------------------------------------------------------------------------
# LLM signal categorization
# ---------------------------------------------------------------------------

_VALID_SIGNAL_TYPES = {
    "LIVE_RFP", "ANTICIPATED_WINDOW", "RECENT_AWARDS", "MORATORIUM",
    "ORDINANCE_AMENDMENT", "LITIGATION", "PAST_RFP", "NONE",
}


def _llm_categorize_signal(text: str, town: str, source_strategy: str) -> dict | None:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return _keyword_categorize_signal(text)
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        prompt = f"""You are analyzing a page about cannabis activity in {town}, NJ.
Categorize this content into EXACTLY ONE signal type:

  LIVE_RFP            — currently accepting applications (open window)
  ANTICIPATED_WINDOW  — future opening with a stated date
  RECENT_AWARDS       — town/state has already awarded cannabis licenses
  MORATORIUM          — temporary halt on cannabis applications
  ORDINANCE_AMENDMENT — proposed changes coming to a council vote
  LITIGATION          — pending lawsuit affecting cannabis licensing
  PAST_RFP            — expired RFP, no current activity
  NONE                — not actually about cannabis licensing in {town}

Only extract real dates from the text — do not infer.
Use ISO format YYYY-MM-DD where possible.

Text:
{text[:MAX_TEXT]}

Respond with JSON only:
{{
  "type": "one of the categories above",
  "title": "short title of the document or page",
  "snippet": "first 400 characters describing the cannabis activity",
  "application_deadline": "ISO date or empty",
  "questions_deadline":   "ISO date or empty",
  "window_opens":         "ISO date or empty",
  "window_closes":        "ISO date or empty",
  "moratorium_expires":   "ISO date or empty",
  "amendment_vote_date":  "ISO date or empty",
  "confidence": "high, medium, or low"
}}"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=500,
        )
        result = json.loads(response.choices[0].message.content)
        sig_type = result.get("type", "NONE")
        if sig_type not in _VALID_SIGNAL_TYPES:
            sig_type = "NONE"
        result["type"] = sig_type
        result["source_strategy"] = source_strategy
        return result if sig_type != "NONE" else None
    except Exception as e:
        print(f"      [signals-llm] error: {e}")
        return _keyword_categorize_signal(text)


# ---------------------------------------------------------------------------
# Keyword fallback
# ---------------------------------------------------------------------------

_CANNABIS_GATE_RE  = re.compile(
    r"\bcannabis\b|\bmarijuana\b|\bdispensary\b|\bClass\s*5\b|\bCRC\b|\bNJRC\b|\brecreational\b",
    re.I,
)

_LIVE_RFP_RE       = re.compile(r"\b(?:request for proposals?|RFP|RFQ|RFB)\b.{0,300}cannabis", re.I | re.DOTALL)
_LIVE_RFP_RE2      = re.compile(r"cannabis.{0,300}\b(?:request for proposals?|RFP|RFQ)\b", re.I | re.DOTALL)
_AWARDS_RE         = re.compile(r"\b(?:awarded|granted|issued|approved)\b.{0,200}(?:license|permit)", re.I | re.DOTALL)
_MORATORIUM_RE     = re.compile(r"\bmoratorium\b.{0,200}cannabis|cannabis.{0,200}moratorium", re.I | re.DOTALL)
_AMENDMENT_RE      = re.compile(r"\b(?:amend|amendment|proposed ordinance)\b.{0,200}cannabis", re.I | re.DOTALL)
_LITIGATION_RE     = re.compile(r"\b(?:lawsuit|litigation|complaint|petition|appeal)\b.{0,200}cannabis", re.I | re.DOTALL)
_DEADLINE_RE       = re.compile(
    r"(?:deadline|due|close[sd]?|expires?|submit by|no later than)[^\n]{0,40}"
    r"(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{1,2},?\s+\d{4}",
    re.I,
)


def _keyword_categorize_signal(text: str) -> dict | None:
    """Fallback when LLM unavailable."""
    sig_type = "NONE"
    if _LIVE_RFP_RE.search(text) or _LIVE_RFP_RE2.search(text):
        sig_type = "LIVE_RFP"
    elif _AWARDS_RE.search(text):
        sig_type = "RECENT_AWARDS"
    elif _MORATORIUM_RE.search(text):
        sig_type = "MORATORIUM"
    elif _AMENDMENT_RE.search(text):
        sig_type = "ORDINANCE_AMENDMENT"
    elif _LITIGATION_RE.search(text):
        sig_type = "LITIGATION"
    if sig_type == "NONE":
        return None
    deadline = ""
    m = _DEADLINE_RE.search(text)
    if m:
        deadline = m.group(0)
    return {
        "type":                 sig_type,
        "title":                "",
        "snippet":              text[:400],
        "application_deadline": deadline,
        "questions_deadline":   "",
        "window_opens":         "",
        "window_closes":        "",
        "moratorium_expires":   "",
        "amendment_vote_date":  "",
        "confidence":           "low",
    }


# ---------------------------------------------------------------------------
# LLM award extraction (S1 — CRC)
# ---------------------------------------------------------------------------

def _llm_extract_awards(text: str, town: str) -> list[dict]:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return []
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        prompt = f"""You are analyzing an NJ Cannabis Regulatory Commission license listing.
Extract any awarded or pending cannabis RETAIL licenses (Class 5 / adult-use)
located in {town}, NJ.  Ignore other towns.

Text:
{text[:MAX_TEXT]}

Respond with JSON only:
{{
  "licenses": [
    {{
      "licensee":       "full business or applicant name",
      "license_class":  "Class 5 Retail or specific class",
      "license_status": "annual, conditional, or pending",
      "address":        "street address if listed, else empty",
      "license_number": "license number if listed, else empty"
    }}
  ]
}}
If no licenses in {town} are found, return {{"licenses": []}}."""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=600,
        )
        return json.loads(response.choices[0].message.content).get("licenses", []) or []
    except Exception as e:
        print(f"      [signals-llm-awards] error: {e}")
        return []


# ---------------------------------------------------------------------------
# Seed URL loader
# ---------------------------------------------------------------------------

def _load_seed_urls(town: str) -> list[str]:
    """Pull all seed URLs for `town` from rfp_seed_urls.csv."""
    if not _SEED_FILE.exists():
        return []
    urls = []
    with open(_SEED_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("municipality", "").strip().lower() == town.lower():
                u = row.get("monitor_url", "").strip()
                if u:
                    urls.append(u)
    return urls


# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------

def _scrape_and_categorize(
    urls: list[str],
    town: str,
    source_strategy: str,
) -> list[dict]:
    """Scrape URLs, categorize each page, return signal dicts."""
    if not urls:
        return []
    try:
        scraped = firecrawl_scrape_urls(urls)
    except Exception as e:
        print(f"      [signals:{source_strategy}] scrape error: {e}")
        return []

    signals = []
    for url, text in scraped.items():
        if not text or len(text) < 200:
            continue
        if not _CANNABIS_GATE_RE.search(text):
            continue  # skip pages with no cannabis-related content
        sig = _llm_categorize_signal(text, town, source_strategy) \
              or _keyword_categorize_signal(text)
        if sig and sig.get("type") != "NONE":
            sig["url"]            = url
            sig["source_strategy"] = source_strategy
            sig["extracted_at"]   = datetime.now(timezone.utc).isoformat()
            signals.append(sig)
    return signals


def _search_and_categorize(
    queries: list[str],
    town: str,
    source_strategy: str,
    allow_news: bool = False,
    max_per_query: int = 3,
) -> tuple[list[dict], list[str]]:
    """
    Run search queries, scrape new URLs, categorize each.
    Returns (signals, queries_actually_run).
    """
    signals: list[dict] = []
    tried_urls: set[str] = set()
    queries_run: list[str] = []

    for q in queries:
        print(f"      [signals:{source_strategy}] {q}")
        queries_run.append(q)
        try:
            results = firecrawl_search(q, limit=3)
        except Exception as e:
            print(f"      [signals:{source_strategy}] search error: {e}")
            continue

        to_scrape = [
            r["url"] for r in results
            if r.get("url") and r["url"] not in tried_urls
            and not _skip(r["url"], allow_news=allow_news)
        ]
        for url in to_scrape:
            tried_urls.add(url)

        scraped: dict[str, str] = {}
        if to_scrape[:max_per_query]:
            try:
                scraped = firecrawl_scrape_urls(to_scrape[:max_per_query])
            except Exception as e:
                print(f"      [signals:{source_strategy}] scrape error: {e}")

        for url, text in scraped.items():
            if not text or len(text) < 200:
                continue
            if not _CANNABIS_GATE_RE.search(text):
                continue  # skip pages with no cannabis-related content
            sig = _llm_categorize_signal(text, town, source_strategy) \
                  or _keyword_categorize_signal(text)
            if sig and sig.get("type") != "NONE":
                sig["url"]             = url
                sig["source_strategy"] = source_strategy
                sig["extracted_at"]    = datetime.now(timezone.utc).isoformat()
                signals.append(sig)

    return signals, queries_run


# ---------------------------------------------------------------------------
# Per-strategy entry points
# ---------------------------------------------------------------------------

def _strategy1_crc(town: str) -> tuple[list[dict], list[dict], list[str]]:
    """NJ CRC license database lookup.
    Returns (signals, awarded_licenses, queries_run).
    """
    queries = [
        f'"{town}" site:nj.gov cannabis license',
        f'"{town}" NJ cannabis "Class 5" license issued',
        f'NJ Cannabis Regulatory Commission "{town}" approved',
    ]
    awarded: list[dict] = []
    signals: list[dict] = []
    queries_run: list[str] = []
    tried: set[str] = set()

    for q in queries:
        print(f"      [signals:S1] {q}")
        queries_run.append(q)
        try:
            results = firecrawl_search(q, limit=3)
        except Exception as e:
            print(f"      [signals:S1] search error: {e}")
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
                print(f"      [signals:S1] scrape error: {e}")

        for url, text in scraped.items():
            if not text or len(text) < 200:
                continue
            licenses = _llm_extract_awards(text, town)
            if licenses:
                for lic in licenses:
                    lic["source_url"] = url
                awarded.extend(licenses)
                signals.append({
                    "type":             "RECENT_AWARDS",
                    "url":              url,
                    "title":            f"NJ CRC license listing — {town}",
                    "snippet":          f"{len(licenses)} cannabis license(s) found via CRC",
                    "application_deadline": "",
                    "questions_deadline":   "",
                    "window_opens":         "",
                    "window_closes":        "",
                    "moratorium_expires":   "",
                    "amendment_vote_date":  "",
                    "confidence":          "high",
                    "source_strategy":     "S1",
                    "extracted_at":        datetime.now(timezone.utc).isoformat(),
                })

        if awarded:
            break   # short-circuit once CRC returned anything

    # Dedupe awarded licenses — normalize company names before comparing so
    # "COLUMBIA CARE NEW JERSEY LLC" and "Columbia Care NJ/The Cannabist" collapse to one.
    def _norm_licensee(name: str) -> str:
        n = re.sub(r"[^a-z0-9 ]", " ", name.lower())
        n = re.sub(r"\b(llc|inc|corp|ltd|lp|llp|nj|new jersey|the|a|an)\b", " ", n)
        return re.sub(r"\s+", " ", n).strip()

    seen_licensees: set[str] = set()
    unique_awarded = []
    for lic in awarded:
        raw = lic.get("licensee", "")
        if not raw:
            continue
        norm = _norm_licensee(raw)
        # Check if any already-seen licensee shares ≥2 tokens with this one
        norm_tokens = set(norm.split())
        duplicate = any(
            len(norm_tokens & set(seen.split())) >= 2
            for seen in seen_licensees
        )
        if duplicate:
            continue
        seen_licensees.add(norm)
        unique_awarded.append(lic)

    return signals, unique_awarded, queries_run


def _strategy2_town_rfps(town: str) -> tuple[list[dict], list[str]]:
    """Town's own RFP pages + targeted RFP search."""
    queries_run: list[str] = []

    # First: re-scrape any seed URLs for this town
    # Seed URLs: skip re-scrape here — the daily monitor already covers these
    signals: list[dict] = []
    queries = [
        f'"{town} NJ" cannabis RFP OR "request for proposal"',
        f'"{town} NJ" cannabis dispensary application',
    ]
    extra, qrun = _search_and_categorize(queries, town, "S2")
    signals += extra
    queries_run += qrun
    return signals, queries_run


def _strategy3_council_agendas(town: str) -> tuple[list[dict], list[str]]:
    """Upcoming council agenda search."""
    year = datetime.now().year
    queries = [
        f'"{town} NJ" council agenda cannabis {year}',
        f'"{town} NJ" "council meeting" cannabis ordinance',
    ]
    return _search_and_categorize(queries, town, "S3")


def _strategy4_news(town: str) -> tuple[list[dict], list[str]]:
    """News coverage — only strategy that allows news domains."""
    year = datetime.now().year
    queries = [
        f'"{town}" cannabis dispensary {year} NJ',
        f'"{town}" NJ cannabis license awarded OR approved',
    ]
    return _search_and_categorize(queries, town, "S4", allow_news=True)


# ---------------------------------------------------------------------------
# Cap math + aggregation
# ---------------------------------------------------------------------------

def _parse_cap_int(cap_str: str) -> int | None:
    """Extract integer cap from strings like '2', 'two', 'max 3'."""
    if not cap_str:
        return None
    if "no cap" in cap_str.lower() or "unlimited" in cap_str.lower():
        return -1
    m = re.search(r"\d+", cap_str)
    return int(m.group(0)) if m else None


def _compute_cap_status(ordinance_cap: str, awarded: list[dict]) -> dict:
    cap_int = _parse_cap_int(ordinance_cap or "")
    awarded_count = len([a for a in awarded if a.get("license_status") in ("annual", "conditional")])
    if cap_int is None:
        return {
            "cap":         ordinance_cap or "",
            "awarded":     awarded_count,
            "slots_open":  None,
            "saturated":   None,
            "note":        "Cap not extracted from ordinance",
        }
    if cap_int == -1:
        return {
            "cap":         "no cap",
            "awarded":     awarded_count,
            "slots_open":  None,
            "saturated":   False,
            "note":        "Ordinance imposes no cap",
        }
    slots_open = max(0, cap_int - awarded_count)
    return {
        "cap":         cap_int,
        "awarded":     awarded_count,
        "slots_open":  slots_open,
        "saturated":   slots_open == 0,
        "note":        "" if slots_open > 0 else "Cap reached — no slots remain",
    }


_DATE_FIELDS = (
    "application_deadline", "questions_deadline",
    "window_opens", "window_closes",
    "moratorium_expires", "amendment_vote_date",
)


def _earliest_future_date(signals: list[dict]) -> str:
    """Find the earliest future date across all date fields in all signals."""
    today = datetime.now(timezone.utc).date()
    candidates: list[datetime] = []
    for sig in signals:
        for field in _DATE_FIELDS:
            val = sig.get(field, "")
            if not val:
                continue
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
                try:
                    dt = datetime.strptime(val[:10], fmt).date()
                    if dt >= today:
                        candidates.append(dt)
                    break
                except ValueError:
                    continue
    if not candidates:
        return ""
    return min(candidates).isoformat()


def _dedupe_signals(signals: list[dict]) -> list[dict]:
    """Dedupe by (type, url)."""
    seen = set()
    out = []
    for s in signals:
        key = (s.get("type"), s.get("url"))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def check_rfp_signals(
    town: str,
    con: sqlite3.Connection,
    ordinance: dict | None = None,
    refresh: bool = False,
) -> dict:
    """Five-strategy RFP signal sweep for `town`.

    Args:
        town:      municipality name
        con:       SQLite connection
        ordinance: result from find_ordinance(); used for cap math
        refresh:   bypass cache (24h TTL otherwise)
    """
    if not refresh:
        cached = get_cached_signals(con, town)
        if cached:
            print(f"      [signals] cache hit (within 24h)")
            return cached

    ordinance = ordinance or {}
    all_signals:  list[dict] = []
    all_queries:  list[str]  = []
    awarded_licenses: list[dict] = []

    # ---- S1: CRC ----
    print(f"\n    [signals] S1 — NJ CRC license lookup")
    sigs, awarded_licenses, qs = _strategy1_crc(town)
    all_signals  += sigs
    all_queries  += qs

    # ---- S2: Town RFPs ----
    print(f"\n    [signals] S2 — Town RFP pages + seed URLs")
    sigs, qs = _strategy2_town_rfps(town)
    all_signals += sigs
    all_queries += qs

    # ---- S3: Council agendas ----
    print(f"\n    [signals] S3 — Council agendas")
    sigs, qs = _strategy3_council_agendas(town)
    all_signals += sigs
    all_queries += qs

    # ---- S4: News (whitelist) ----
    print(f"\n    [signals] S4 — News coverage")
    sigs, qs = _strategy4_news(town)
    all_signals += sigs
    all_queries += qs

    # ---- Dedupe + cap math + next-action ----
    all_signals       = _dedupe_signals(all_signals)
    cap_status        = _compute_cap_status(ordinance.get("cap", ""), awarded_licenses)
    next_action_date  = _earliest_future_date(all_signals)

    # Overall confidence
    has_high = any(s.get("confidence") == "high" for s in all_signals)
    has_live = any(s.get("type") == "LIVE_RFP" for s in all_signals)
    confidence = "high" if (has_high and has_live) else ("medium" if all_signals else "low")

    result = {
        "found":             bool(all_signals or awarded_licenses),
        "signals":           all_signals,
        "awarded_licenses":  awarded_licenses,
        "cap_status":        cap_status,
        "next_action_date":  next_action_date,
        "needs_foia":        not bool(all_signals),
        "confidence":        confidence,
        "queries_tried":     all_queries,
        "cached_at":         datetime.now(timezone.utc).isoformat(),
    }

    _cache_signals(con, town, result)
    return result
