"""
Sub-task 3 -- Council Vote Tagger
===================================
Roll-call vote cascade (short-circuits on first success):

  Strategy 0 -- Town's official legal-notices page (from nj_legal_notices.csv)
  Strategy 1 -- Adopting-ordinance PDF (searched by ordinance number)
  Strategy 2 -- Council meeting minutes (searched by adoption date)

After vote extraction:
  + Sponsor extraction  -- always runs on ordinance text; sponsors flagged friendly
  + Current roster      -- Firecrawl -> town site -> contact info
  + CRM enrichment      -- cannabis_crm_enriched.csv (phone/email fill-in)

Returns dict:
  {
    "members":         [{name, role_at_vote, vote, sponsor, friendly,
                         still_in_office, current_title, email, phone,
                         vote_source_url, vote_source_type}],
    "rollcall_found":  bool,
    "needs_foia":      bool,   -- True when all vote strategies failed
    "vote_source_type": str,   -- "legal_notice"|"ordinance_pdf"|"minutes"|"none"
    "vote_source_url":  str,
  }
"""

import csv
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from deep_dive.firecrawl_utils import firecrawl_scrape_urls, firecrawl_search

_CRM_PATH          = Path(__file__).parent.parent.parent / "cannabis_hits" / "crm" / "cannabis_crm_enriched.csv"
_LEGAL_NOTICES_CSV = Path(__file__).parent.parent.parent / "data" / "nj_legal_notices.csv"

MAX_TEXT      = 12_000
SKIP_DOMAINS  = {
    # News / social
    "nj.com", "tapinto", "patch.com", "facebook.com", "twitter.com",
    "instagram.com", "reddit.com", "linkedin.com",
    # State legislature trackers — these have state bill votes, not local council
    "legiscan.com", "njleg.state.nj.us", "assembly.state.nj.us",
    "senate.nj.gov", "trackbill.com", "openstates.org",
}
NEWS_DOMAINS = SKIP_DOMAINS   # alias kept for backward compat

# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS town_council (
    municipality   TEXT PRIMARY KEY,
    extracted_json TEXT,
    found_at       TEXT
)
"""


def _ensure_table(con: sqlite3.Connection) -> None:
    con.execute(_CREATE_TABLE)
    con.commit()


def get_cached_council(con: sqlite3.Connection, town: str) -> dict | None:
    _ensure_table(con)
    row = con.execute(
        "SELECT extracted_json FROM town_council WHERE municipality = ?",
        (town,),
    ).fetchone()
    if row and row[0]:
        return json.loads(row[0])
    return None


def _cache_council(con: sqlite3.Connection, town: str, result: dict) -> None:
    _ensure_table(con)
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        """
        INSERT INTO town_council (municipality, extracted_json, found_at)
        VALUES (?, ?, ?)
        ON CONFLICT(municipality) DO UPDATE SET
            extracted_json = excluded.extracted_json,
            found_at       = excluded.found_at
        """,
        (town, json.dumps(result), now),
    )
    con.commit()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _is_skip_url(url: str) -> bool:
    return any(d in url for d in SKIP_DOMAINS)


_is_news_url = _is_skip_url   # alias kept for existing callers


def _scrape_first_good(urls: list[str], min_len: int = 300) -> tuple[str, str]:
    """Batch-scrape a list of URLs; return (text, url) of the first with content."""
    if not urls:
        return "", ""
    try:
        scraped = firecrawl_scrape_urls(urls[:4])
        for url in urls:
            text = scraped.get(url, "")
            if text and len(text) >= min_len:
                return text, url
    except Exception as e:
        print(f"      [council] scrape error: {e}")
    return "", ""


def _format_date_variants(date_str: str) -> list[str]:
    """Return multiple human-readable formats for a date string."""
    variants = [date_str]   # always include the raw value
    for fmt_in in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt_in)
            variants.append(dt.strftime("%B %-d, %Y"))   # July 13, 2021
            variants.append(dt.strftime("%-m/%-d/%Y"))   # 7/13/2021
            variants.append(dt.strftime("%Y-%m-%d"))      # 2021-07-13
            break
        except ValueError:
            continue
    return list(dict.fromkeys(variants))   # deduplicate while preserving order


# ---------------------------------------------------------------------------
# Ordinance metadata from SQLite cache
# ---------------------------------------------------------------------------

def _get_ordinance_metadata(town: str, con: sqlite3.Connection) -> dict:
    """Return the cached ordinance dict (url, number, adopted_date, text_excerpt)."""
    row = con.execute(
        "SELECT extracted_json FROM town_ordinances WHERE municipality = ?",
        (town,),
    ).fetchone()
    if row and row[0]:
        return json.loads(row[0])
    return {}


def _scrape_ordinance_page(ordinance_url: str) -> str:
    """Re-scrape the cached ordinance page for its full text."""
    if not ordinance_url:
        return ""
    print(f"      [council] scraping ordinance page: {ordinance_url[:80]}...")
    try:
        scraped = firecrawl_scrape_urls([ordinance_url])
        return scraped.get(ordinance_url, "")
    except Exception as e:
        print(f"      [council] ordinance scrape error: {e}")
        return ""


# ---------------------------------------------------------------------------
# Strategy 0 -- official legal-notices page (nj_legal_notices.csv)
# ---------------------------------------------------------------------------

def _get_legal_notice_url(town: str) -> str:
    """Look up the town's official legal-notices URL from the local CSV."""
    if not _LEGAL_NOTICES_CSV.exists():
        return ""
    try:
        with open(_LEGAL_NOTICES_CSV, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                muni = row.get("Municipality", "") or row.get("Agency/Entity Name", "")
                if town.lower() in muni.lower() and "Local Government" in row.get("Type", ""):
                    return row.get("Public Notice URL", "")
    except Exception:
        pass
    return ""


def strategy0_legal_notice_page(town: str, ordinance_number: str) -> tuple[str, str]:
    """Scrape the town's official legal-notices page; search for the ordinance."""
    url = _get_legal_notice_url(town)
    if not url:
        return "", ""
    print(f"      [council:S0] scraping legal-notices page: {url}")
    try:
        scraped = firecrawl_scrape_urls([url])
        text = scraped.get(url, "")
        if not text:
            return "", ""
        # Only useful if it contains our ordinance number or cannabis keywords
        if ordinance_number and ordinance_number.lower() in text.lower():
            return text, url
        if re.search(r"cannabis|marijuana|dispensary", text, re.I):
            return text, url
    except Exception as e:
        print(f"      [council:S0] error: {e}")
    return "", ""


# ---------------------------------------------------------------------------
# Strategy 1 -- adopting-ordinance PDF (by ordinance number)
# ---------------------------------------------------------------------------

def strategy1_ordinance_pdf(town: str, ordinance_number: str) -> tuple[str, str]:
    """Search for the adopting ordinance PDF and return (text, source_url)."""
    if not ordinance_number:
        return "", ""

    queries = [
        f'"{town} NJ" "Ordinance {ordinance_number}" cannabis "roll call" OR "ayes" OR "nays"',
        f'"{town} NJ" "Ordinance {ordinance_number}" filetype:pdf',
        f'"{town} NJ" "Ordinance No. {ordinance_number}" cannabis vote adopted',
        f'"{town}" "{ordinance_number}" cannabis ordinance adopted council vote',
    ]

    tried: set[str] = set()
    for query in queries:
        print(f"      [council:S1] {query}")
        try:
            results = firecrawl_search(query, limit=5)
        except Exception as e:
            print(f"      [council:S1] search error: {e}")
            continue

        to_scrape, inline = [], {}
        for r in results:
            url = r.get("url", "")
            if not url or url in tried or _is_news_url(url):
                continue
            tried.add(url)
            md = r.get("markdown", "")
            if md and len(md) > 200:
                inline[url] = md
            else:
                to_scrape.append(url)

        if to_scrape:
            text, url = _scrape_first_good(to_scrape)
            if text:
                inline[url] = text

        for url, text in inline.items():
            if not text or len(text) < 200:
                continue
            # Must contain something that looks like a roll-call vote
            if re.search(
                r"\b(ayes?|nays?|abstain|roll\s*call|voted\s+yes|voted\s+no)\b",
                text, re.I
            ):
                print(f"      [council:S1] roll-call indicators found: {url[:60]}")
                return text, url

    return "", ""


# ---------------------------------------------------------------------------
# Strategy 2 -- council meeting minutes (by adoption date)
# ---------------------------------------------------------------------------

def strategy2_meeting_minutes(town: str, adopted_date: str) -> tuple[str, str]:
    """Search for council minutes from the adoption date. Returns (text, url)."""
    if not adopted_date:
        return "", ""

    date_variants = _format_date_variants(adopted_date)

    tried: set[str] = set()
    for date_str in date_variants:
        queries = [
            f'"{town} NJ" council minutes "{date_str}" cannabis ordinance',
            f'"{town} NJ" "council meeting" "{date_str}" minutes',
            f'"{town}" governing body minutes "{date_str}"',
        ]
        for query in queries:
            print(f"      [council:S2] {query}")
            try:
                results = firecrawl_search(query, limit=5)
            except Exception as e:
                print(f"      [council:S2] search error: {e}")
                continue

            to_scrape, inline = [], {}
            for r in results:
                url = r.get("url", "")
                if not url or url in tried or _is_news_url(url):
                    continue
                tried.add(url)
                md = r.get("markdown", "")
                if md and len(md) > 200:
                    inline[url] = md
                else:
                    to_scrape.append(url)

            if to_scrape:
                text, url = _scrape_first_good(to_scrape)
                if text:
                    inline[url] = text

            for url, text in inline.items():
                if not text or len(text) < 200:
                    continue
                if re.search(
                    r"\b(ayes?|nays?|abstain|roll\s*call|voted\s+yes|voted\s+no|cannabis|ordinance)\b",
                    text, re.I,
                ):
                    print(f"      [council:S2] minutes found: {url[:60]}")
                    return text, url

    return "", ""


# ---------------------------------------------------------------------------
# LLM roll-call extraction (shared by all strategies)
# ---------------------------------------------------------------------------

def llm_extract_rollcall(text: str, town: str) -> list[dict]:
    """Use gpt-4o-mini to extract roll-call votes from any page text."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return []
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        prompt = f"""You are reading a LOCAL government document for {town}, NJ.

Extract the roll-call vote for a LOCAL MUNICIPAL cannabis ordinance adoption.
Look for: "Roll Call", "Ayes", "Nays", "Abstain", "Absent", vote tables, or "voted yes/no".
Also note anyone who SPONSORED or INTRODUCED the ordinance.

IMPORTANT: Only extract LOCAL council members, mayor, or commissioners.
Do NOT include NJ state senators, NJ assembly members, or federal officials.
If the document is about a state bill (not a local ordinance), return [].

Text:
{text[:MAX_TEXT]}

Respond with JSON only -- a list (empty list [] if no local votes found):
[
  {{
    "name": "Full Name",
    "title_at_vote": "Council Member / Mayor / Deputy Mayor / Commissioner / etc.",
    "vote": "yes" or "no" or "abstain" or "absent" or "unknown",
    "sponsor": true or false
  }}
]

Include ONLY local elected officials in the roll-call, not state/federal legislators.
CRITICAL: Use actual names only. If you cannot find real person names (only vote counts like "2-1"), return [].
Never use placeholders like "Full Name", "Unknown", or "Council Member"."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=900,
        )
        raw = json.loads(response.choices[0].message.content)
        votes = raw if isinstance(raw, list) else next(
            (v for v in raw.values() if isinstance(v, list)), []
        )
        # Strip placeholder entries the LLM occasionally generates
        _PLACEHOLDERS = {"full name", "unknown", "council member", "name", "member"}
        return [
            v for v in votes
            if v.get("name", "").lower().strip() not in _PLACEHOLDERS
            and len(v.get("name", "").strip()) > 2
        ]
    except Exception as e:
        print(f"      [council] LLM roll-call error: {e}")
        return []


def keyword_extract_rollcall(text: str) -> list[dict]:
    """Regex fallback: match 'Councilman Smith - Aye' style lines."""
    pattern = re.compile(
        r"(?:Council(?:man|woman|member|person)?|Mayor|Deputy\s+Mayor)\s+"
        r"([A-Z][a-zA-Z\-']+(?:\s+[A-Z][a-zA-Z\-']+){0,3})"
        r"\s*[-:]\s*(Aye|Nay|Yes|No|Abstain|Absent)",
        re.I,
    )
    results = []
    for m in pattern.finditer(text):
        vote_raw = m.group(2).lower()
        vote = "yes" if vote_raw in ("aye", "yes") else (
               "no" if vote_raw in ("nay", "no") else vote_raw)
        results.append({
            "name":          m.group(1).strip(),
            "title_at_vote": m.group(0).split(m.group(1))[0].strip().rstrip("-: "),
            "vote":          vote,
            "sponsor":       False,
        })
    return results


def llm_extract_sponsors(text: str, town: str) -> list[dict]:
    """Extract sponsors/introducers from the ordinance text — cheap win."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return []
    # Quick keyword scan first — skip LLM call if no sponsor language
    if not re.search(r"\b(introduc|sponsor|motion\s+by|moved\s+by)\b", text, re.I):
        return []
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        prompt = f"""Read this {town}, NJ government document and find anyone who:
- Introduced, sponsored, or made the motion to adopt a cannabis ordinance
- Is listed as the author or primary sponsor

Text:
{text[:MAX_TEXT]}

JSON only -- list (empty [] if none found):
[
  {{
    "name": "Full Name",
    "title_at_vote": "their title",
    "vote": "yes",
    "sponsor": true
  }}
]"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=400,
        )
        raw = json.loads(response.choices[0].message.content)
        if isinstance(raw, list):
            return raw
        for v in raw.values():
            if isinstance(v, list):
                return v
        return []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Current council roster
# ---------------------------------------------------------------------------

_ROSTER_QUERIES = [
    '"{town} NJ" city council members official government site',
    '"{town} NJ" mayor council members contact directory',
    '"{town} NJ" governing body elected officials',
]


def llm_extract_roster(text: str, town: str) -> list[dict]:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return []
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        prompt = f"""You are reading a government website page for {town}, NJ.
Extract the CURRENT elected officials and council members.

Text:
{text[:MAX_TEXT]}

JSON only -- list ([] if none found):
[
  {{
    "name": "Full Name",
    "current_title": "Mayor / Council Member / Deputy Mayor / etc.",
    "email": "email or empty string",
    "phone": "phone or empty string"
  }}
]
Only include elected officials. Exclude staff, directors, and department heads."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=800,
        )
        raw = json.loads(response.choices[0].message.content)
        if isinstance(raw, list):
            return raw
        for v in raw.values():
            if isinstance(v, list):
                return v
        return []
    except Exception as e:
        print(f"      [council] LLM roster error: {e}")
        return []


_ROSTER_URL_KEYWORDS = {"council", "governing", "officials", "mayor", "committee",
                        "elected", "members", "board", "commissioners"}
_STALE_YEAR_RE = re.compile(r"/(20[01]\d)/")   # URLs with years 2000-2019


def _roster_url_score(url: str) -> int:
    """Score a URL for how likely it is to be a current official council page."""
    score = 0
    u = url.lower()
    if u.endswith(".pdf"):
        return -99                             # never use PDFs for roster
    if ".gov" in u:
        score += 4
    if any(kw in u for kw in _ROSTER_URL_KEYWORDS):
        score += 3
    if _STALE_YEAR_RE.search(u):
        score -= 5                             # old-year path in URL
    return score


def find_current_roster(town: str) -> list[dict]:
    tried: set[str] = set()
    for query_tmpl in _ROSTER_QUERIES:
        query = query_tmpl.format(town=town)
        print(f"      [council] roster search: {query}")
        try:
            results = firecrawl_search(query, limit=5)
        except Exception as e:
            print(f"      [council] roster search error: {e}")
            continue

        to_scrape, inline = [], {}
        for r in results:
            url = r.get("url", "")
            if not url or url in tried or _is_skip_url(url):
                continue
            if url.lower().endswith(".pdf"):    # skip PDFs — rosters are web pages
                continue
            tried.add(url)
            md = r.get("markdown", "")
            if md and len(md) > 200:
                inline[url] = md
            else:
                to_scrape.append(url)

        # Sort to_scrape by officialness before scraping
        to_scrape.sort(key=_roster_url_score, reverse=True)
        if to_scrape:
            text, url = _scrape_first_good(to_scrape)
            if text:
                inline[url] = text

        # Try inline pages in descending URL quality order
        ranked = sorted(inline.items(), key=lambda kv: _roster_url_score(kv[0]), reverse=True)
        for url, text in ranked:
            if not text or len(text) < 100:
                continue
            members = llm_extract_roster(text, town)
            if members:
                print(f"      [council] roster: {len(members)} members from {url[:60]}")
                return members

    return []


# ---------------------------------------------------------------------------
# Targeted contact enrichment for individual voters
# ---------------------------------------------------------------------------

def _llm_extract_contact(text: str, name: str) -> dict:
    """Pull email + phone for a specific named person from page text."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return {}
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content":
                f"Find the email and phone for {name} in this text.\n\n"
                f"{text[:5000]}\n\n"
                'JSON only: {"email": "...", "phone": "..."}'}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=80,
        )
        return json.loads(response.choices[0].message.content)
    except Exception:
        return {}


def enrich_voter_contacts(members: list[dict], town: str) -> list[dict]:
    """For roll-call voters missing contact info, search individually."""
    to_enrich = [
        m for m in members
        if m.get("vote") in ("yes", "aye", "no")      # only real voters
        and not m.get("email")
        and not m.get("phone")
        and m.get("name")
    ]
    if not to_enrich:
        return members

    print(f"      [council] enriching {len(to_enrich)} voters with no contact info...")
    for member in to_enrich:
        name = member["name"]
        query = f'"{name}" "{town} NJ" council email OR phone contact'
        try:
            results = firecrawl_search(query, limit=3)
        except Exception as e:
            print(f"      [council] enrich search error for {name}: {e}")
            continue

        for r in results:
            url = r.get("url", "")
            if not url or _is_skip_url(url) or url.lower().endswith(".pdf"):
                continue
            text = r.get("markdown", "") or ""
            if len(text) < 100:
                # Scrape if search didn't inline content
                try:
                    scraped = firecrawl_scrape_urls([url])
                    text = scraped.get(url, "")
                except Exception:
                    continue

            contact = _llm_extract_contact(text, name)
            email = contact.get("email", "").strip()
            phone = contact.get("phone", "").strip()

            # Sanity-check: reject generic/placeholder values
            if email and "@" in email and "example" not in email:
                member["email"] = email
                member["contact_source"] = url
            if phone and any(c.isdigit() for c in phone):
                member["phone"] = phone
                member.setdefault("contact_source", url)

            if member.get("email") or member.get("phone"):
                print(f"      [council] enriched {name}: {email or phone}")
                break

    return members


# ---------------------------------------------------------------------------
# CRM enrichment
# ---------------------------------------------------------------------------

def _load_crm(town: str) -> list[dict]:
    if not _CRM_PATH.exists():
        return []
    try:
        with open(_CRM_PATH, newline="", encoding="utf-8") as f:
            return [
                r for r in csv.DictReader(f)
                if r.get("municipality", "").lower() == town.lower()
            ]
    except Exception as e:
        print(f"      [council] CRM load error: {e}")
        return []


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------

_NAME_STOP = {"mr", "mrs", "ms", "dr", "jr", "sr", "ii", "iii", "esq"}


def _clean_name_parts(name: str) -> list[str]:
    """Return name tokens in original order, stripping stop words and initials."""
    parts = []
    for word in name.split():
        w = re.sub(r"[^a-z]", "", word.lower())   # strip punctuation
        if w and w not in _NAME_STOP and len(w) > 1:  # skip 'W.' style initials
            parts.append(w)
    return parts


def _name_similarity(a: str, b: str) -> float:
    a_parts = _clean_name_parts(a)
    b_parts = _clean_name_parts(b)
    if not a_parts or not b_parts:
        return 0.0
    # Use the LAST token as the surname (order-preserving, punctuation stripped)
    a_last, b_last = a_parts[-1], b_parts[-1]
    if a_last == b_last:
        # Same surname — require matching first initial to confirm same person.
        # Prevents "Samuel Palombo" from matching "Richard Palombo".
        a_first = a_parts[0] if len(a_parts) > 1 else ""
        b_first = b_parts[0] if len(b_parts) > 1 else ""
        if a_first and b_first:
            return 0.9 if a_first[0] == b_first[0] else 0.35
        return 0.7   # only surname available — treat as weak match
    return SequenceMatcher(None,
                           " ".join(sorted(a_parts)),
                           " ".join(sorted(b_parts))).ratio()


def _best_match(name: str, pool: list[dict], name_key: str = "name") -> tuple[dict | None, float]:
    best, score = None, 0.0
    for item in pool:
        s = _name_similarity(name, item.get(name_key, ""))
        if s > score:
            score, best = s, item
    return (best, score) if score >= 0.75 else (None, 0.0)


# ---------------------------------------------------------------------------
# Merge -- roll-call + roster + CRM
# ---------------------------------------------------------------------------

def _merge(
    rollcall: list[dict],
    sponsors: list[dict],
    roster: list[dict],
    crm: list[dict],
    vote_source_url: str,
    vote_source_type: str,
) -> list[dict]:
    merged: list[dict] = []

    # De-duplicate sponsors into roll-call (avoid double-listing)
    rollcall_names = [v.get("name", "") for v in rollcall]
    for sp in sponsors:
        already = any(_name_similarity(sp.get("name", ""), n) >= 0.75 for n in rollcall_names)
        if not already:
            rollcall.append(sp)
            rollcall_names.append(sp.get("name", ""))

    # Build member records from roll-call (authoritative vote source)
    for voter in rollcall:
        name = voter.get("name", "")
        roster_match, _ = _best_match(name, roster)
        crm_match, _    = _best_match(name, crm)

        still_in_office = roster_match is not None
        friendly        = voter.get("vote", "").lower() in ("yes", "aye") or voter.get("sponsor", False)

        merged.append({
            "name":             name,
            "role_at_vote":     voter.get("title_at_vote", ""),
            "vote":             voter.get("vote", "unknown"),
            "sponsor":          voter.get("sponsor", False),
            "friendly":         friendly,
            "still_in_office":  still_in_office,
            "current_title":    (roster_match or {}).get("current_title", ""),
            "email":            (roster_match or {}).get("email", "")  or (crm_match or {}).get("email", ""),
            "phone":            (roster_match or {}).get("phone", "")  or (crm_match or {}).get("phone", ""),
            "vote_source_url":  vote_source_url,
            "vote_source_type": vote_source_type,
            "source":           "ordinance_rollcall",
        })

    # Add current roster members not in roll-call (joined council after the vote)
    merged_names = [m["name"] for m in merged]
    for rm in roster:
        if any(_name_similarity(rm.get("name", ""), n) >= 0.75 for n in merged_names):
            continue
        crm_match, _ = _best_match(rm.get("name", ""), crm)
        merged.append({
            "name":             rm.get("name", ""),
            "role_at_vote":     "",
            "vote":             "not_on_council_at_vote",
            "sponsor":          False,
            "friendly":         False,
            "still_in_office":  True,
            "current_title":    rm.get("current_title", ""),
            "email":            rm.get("email", "") or (crm_match or {}).get("email", ""),
            "phone":            rm.get("phone", "") or (crm_match or {}).get("phone", ""),
            "vote_source_url":  "",
            "vote_source_type": "",
            "source":           "current_roster",
        })

    # Sort: still-in-office first, friendlies first within that group
    merged.sort(key=lambda m: (not m["still_in_office"], not m["friendly"]))
    return merged


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def find_council_votes(
    town: str,
    con: sqlite3.Connection,
    refresh: bool = False,
) -> dict:
    """
    Returns:
      {
        "members":          [...],
        "rollcall_found":   bool,
        "needs_foia":       bool,
        "vote_source_type": str,
        "vote_source_url":  str,
      }
    """
    if not refresh:
        cached = get_cached_council(con, town)
        if cached is not None:
            n = len(cached.get("members", []))
            print(f"      [council] cache hit: {n} members")
            return cached

    # Pull ordinance metadata from sub-task 2 cache
    ordinance = _get_ordinance_metadata(town, con)
    ordinance_url    = ordinance.get("url", "")
    ordinance_number = ordinance.get("ordinance_number", "")
    adopted_date     = ordinance.get("adopted_date", "")

    # Re-scrape the eCode360/Municode page (used for sponsor extraction)
    ordinance_text = _scrape_ordinance_page(ordinance_url)

    # -----------------------------------------------------------------------
    # Vote cascade: try each strategy, run extraction, stop on first real votes
    # A strategy "wins" only when we actually extract named voters from its text.
    # -----------------------------------------------------------------------
    rollcall: list[dict] = []
    vote_source_url, vote_source_type = "", "none"

    strategies = [
        ("S0-legal-notice", lambda: strategy0_legal_notice_page(town, ordinance_number)),
        ("S1-ordinance-pdf", lambda: strategy1_ordinance_pdf(town, ordinance_number)),
        ("S2-minutes",       lambda: strategy2_meeting_minutes(town, adopted_date)),
    ]

    for label, run in strategies:
        text, url = run()
        if not text:
            continue
        print(f"      [council:{label}] got {len(text)} chars -- extracting votes...")
        votes = llm_extract_rollcall(text, town)
        if not votes:
            votes = keyword_extract_rollcall(text)
        if votes:
            rollcall           = votes
            vote_source_url    = url
            vote_source_type   = label.split("-", 1)[1]   # "legal-notice", "ordinance-pdf", "minutes"
            print(f"      [council:{label}] {len(rollcall)} voters found -- stopping cascade")
            break
        else:
            print(f"      [council:{label}] no votes in this source, continuing cascade...")

    if not rollcall:
        print("      [council] all vote strategies exhausted -- needs FOIA")

    # Always try sponsor extraction from the eCode360/Municode text
    sponsors: list[dict] = []
    if ordinance_text:
        sponsors = llm_extract_sponsors(ordinance_text, town)
        if sponsors:
            print(f"      [council] sponsors found: {[s['name'] for s in sponsors]}")

    # -----------------------------------------------------------------------
    # Current roster + CRM
    # -----------------------------------------------------------------------
    print("      [council] fetching current council roster...")
    roster = find_current_roster(town)
    print(f"      [council] roster: {len(roster)} current members")

    crm = _load_crm(town)
    if crm:
        print(f"      [council] CRM: {len(crm)} entries for {town}")

    # -----------------------------------------------------------------------
    # Merge
    # -----------------------------------------------------------------------
    members = _merge(rollcall, sponsors, roster, crm, vote_source_url, vote_source_type)

    # Targeted contact enrichment: search individually for any real voter
    # (yes/no) who still has no email or phone after roster + CRM lookup.
    members = enrich_voter_contacts(members, town)

    rollcall_found = bool(rollcall)
    needs_foia     = not rollcall_found

    result = {
        "members":          members,
        "rollcall_found":   rollcall_found,
        "needs_foia":       needs_foia,
        "vote_source_type": vote_source_type,
        "vote_source_url":  vote_source_url,
    }

    _cache_council(con, town, result)
    return result
