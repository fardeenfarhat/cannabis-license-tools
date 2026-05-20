"""
NJ Cannabis Retail RFP Monitor
==============================
Daily cron job that:
  1. Reads monitoring URLs from the Notion RFPs Monitoring Database (default)
     or falls back to rfp_seed_urls.csv (--csv flag)
  2. For each URL: fetches content via Firecrawl (handles JS/anti-bot)
  3. Hashes the content — skips if unchanged since last run
  4. If new/changed: runs LLM classifier to detect cannabis retail RFPs
  5. Saves hits to SQLite + alerts to console / CSV

Usage:
  python rfp_monitor.py                          # run all towns from Notion
  python rfp_monitor.py --town "Vineland"        # single town debug
  python rfp_monitor.py --limit 1               # test with 1 URL only
  python rfp_monitor.py --priority              # only hand-curated high-value towns
  python rfp_monitor.py --reset                 # clear snapshot DB — force re-scan
  python rfp_monitor.py --csv                   # use rfp_seed_urls.csv instead of Notion
  python rfp_monitor.py --deep "Asbury Park"    # deep-dive research on one town

Environment (loaded from nj_rfp_monitor/.env if present):
  FIRECRAWL_API_KEY   (required)
  NOTION_TOKEN        (required for Notion source — default)
  OPENAI_API_KEY      (optional — falls back to keyword classifier)

Output:
  nj_rfp_monitor/data/rfp_monitor.db   (SQLite — dedup snapshots + hits)
  nj_rfp_monitor/hits/rfp_hits.csv     (all confirmed hits, appended)
"""

import argparse
import csv
import hashlib
import json
import os
import re
import smtplib
import sqlite3
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests

# Deep-dive sub-task modules (one file per sub-task, lives in scripts/deep_dive/)
from deep_dive.ordinance      import find_ordinance
from deep_dive.council_votes  import find_council_votes
from deep_dive.zoning         import find_zoning
from deep_dive.rfp_signals    import check_rfp_signals
from deep_dive.attorneys      import find_attorneys
from deep_dive.email_drafter  import draft_emails
from deep_dive.firecrawl_utils import reset_run_state, credits_used, BudgetExceededError

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT       = Path(__file__).parent.parent
SEED_FILE  = ROOT / "data" / "rfp_seed_urls.csv"
DB_FILE    = ROOT / "data" / "rfp_monitor.db"
HITS_FILE  = ROOT / "hits" / "rfp_hits.csv"
ENV_FILE   = ROOT / ".env"


# ---------------------------------------------------------------------------
# .env loader (lightweight, no dotenv dep required)
# ---------------------------------------------------------------------------

def load_env_file(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        # Strip inline comments (# must be preceded by whitespace)
        val = re.sub(r"\s+#.*$", "", val)
        if key and key not in os.environ:
            os.environ[key] = val


load_env_file(ENV_FILE)

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
NOTION_TOKEN      = os.environ.get("NOTION_TOKEN", "")

# Email alert config
SMTP_HOST    = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT    = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER    = os.environ.get("SMTP_USER", "")
SMTP_PASS    = os.environ.get("SMTP_PASS", "")
ALERT_TO     = os.environ.get("ABBAS_EMAIL", "")

FC_BASE_URL    = "https://api.firecrawl.dev/v1"
NOTION_DB_ID   = "34c61279-b083-8097-9d84-fed2a9c31570"
OPT_IN_FILE    = ROOT / "data" / "nj_opted_in_municipalities.csv"

BATCH_SIZE     = 20       # URLs per Firecrawl batch submission
POLL_INTERVAL  = 8        # Seconds between batch status polls
MAX_TEXT_CHARS = 8_000    # Max chars of page text sent to LLM classifier

FIRST_RUN_FILE = ROOT / "data" / "first_run_summary.csv"
DEEP_DIVE_DIR  = ROOT / "hits" / "deep_dives"   # one JSON report per town


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS page_snapshots (
            municipality TEXT,
            monitor_url  TEXT,
            content_hash TEXT,
            first_seen   TEXT,
            last_seen    TEXT,
            PRIMARY KEY (municipality, monitor_url)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS rfp_hits (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            municipality         TEXT,
            county               TEXT,
            monitor_url          TEXT,
            rfp_title            TEXT,
            deadline             TEXT,
            application_deadline TEXT,
            questions_deadline   TEXT,
            license_types        TEXT,
            confidence           TEXT,
            snippet              TEXT,
            first_seen           TEXT
        )
    """)
    con.commit()
    # Migrate existing DBs that predate the two-deadline columns
    for col in ("application_deadline", "questions_deadline"):
        try:
            con.execute(f"ALTER TABLE rfp_hits ADD COLUMN {col} TEXT DEFAULT ''")
            con.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
    return con


def get_snapshot(con, muni, url):
    row = con.execute(
        "SELECT content_hash FROM page_snapshots WHERE municipality=? AND monitor_url=?",
        (muni, url)
    ).fetchone()
    return row[0] if row else None


def upsert_snapshot(con, muni, url, content_hash):
    now = datetime.now(timezone.utc).isoformat()
    if get_snapshot(con, muni, url) is None:
        con.execute(
            "INSERT INTO page_snapshots (municipality, monitor_url, content_hash, first_seen, last_seen) VALUES (?,?,?,?,?)",
            (muni, url, content_hash, now, now)
        )
    else:
        con.execute(
            "UPDATE page_snapshots SET content_hash=?, last_seen=? WHERE municipality=? AND monitor_url=?",
            (content_hash, now, muni, url)
        )
    con.commit()


def save_hit(con, hit):
    con.execute("""
        INSERT INTO rfp_hits (municipality, county, monitor_url, rfp_title, deadline, application_deadline, questions_deadline, license_types, confidence, snippet, first_seen)
        VALUES (:municipality, :county, :monitor_url, :rfp_title, :deadline, :application_deadline, :questions_deadline, :license_types, :confidence, :snippet, :first_seen)
    """, hit)
    con.commit()


# ---------------------------------------------------------------------------
# Firecrawl batch fetch
# ---------------------------------------------------------------------------

def _fc_headers() -> dict:
    return {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }


def firecrawl_batch_scrape(urls: list[str]) -> dict[str, str]:
    """Submit a batch of URLs to Firecrawl and return {url: markdown_text}.

    Uses the /v1/batch/scrape endpoint so Firecrawl processes them in parallel
    across all available concurrent browser slots (2 on free plan, 5 on paid).
    """
    if not FIRECRAWL_API_KEY:
        raise RuntimeError("FIRECRAWL_API_KEY not set")

    headers = _fc_headers()

    # Submit batch job
    resp = requests.post(
        f"{FC_BASE_URL}/batch/scrape",
        json={"urls": urls, "formats": ["markdown"], "onlyMainContent": True},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise ValueError(f"Firecrawl batch start error: {data}")

    batch_id = data["id"]
    print(f"  [batch] submitted {len(urls)} URLs -> job {batch_id[:12]}...")

    # Poll until complete, handling paginated results
    results: dict[str, str] = {}
    while True:
        time.sleep(POLL_INTERVAL)
        status_resp = requests.get(
            f"{FC_BASE_URL}/batch/scrape/{batch_id}",
            headers=headers,
            timeout=30,
        )
        status_resp.raise_for_status()
        status_data = status_resp.json()

        completed = status_data.get("completed", 0)
        total     = status_data.get("total", len(urls))
        status    = status_data.get("status", "")
        print(f"  [batch] {status} — {completed}/{total}")

        if status == "failed":
            raise ValueError(f"Firecrawl batch failed: {status_data.get('error', '')}")

        if status == "completed":
            # Collect this page of results
            for item in status_data.get("data", []):
                src = item.get("metadata", {}).get("sourceURL", "")
                md  = item.get("markdown", "") or ""
                if src:
                    results[src] = md

            # Follow pagination if Firecrawl returns a next cursor
            next_url = status_data.get("next")
            while next_url:
                page_resp = requests.get(next_url, headers=headers, timeout=30)
                page_resp.raise_for_status()
                page_data = page_resp.json()
                for item in page_data.get("data", []):
                    src = item.get("metadata", {}).get("sourceURL", "")
                    md  = item.get("markdown", "") or ""
                    if src:
                        results[src] = md
                next_url = page_data.get("next")

            return results


# ---------------------------------------------------------------------------
# Keyword classifier (default path)
# ---------------------------------------------------------------------------

CANNABIS_TERMS = re.compile(
    r"\bcannabis\b|\bmarijuana\b|\bdispensary\b|\bcrc\b|"
    r"\bclass\s*5\b|\bclass\s*five\b|\brecreational\b|\badult.?use\b|"
    r"\bATCO\b|\bclass\s*[123456]\b",
    re.I
)

RFP_TERMS = re.compile(
    r"\bRFP\b|\bRFQ\b|\brequest\s+for\s+proposal\b|\brequest\s+for\s+qualifications?\b|"
    r"\bapplication\s+window\b|\bopen\s+period\b|\blicense\s+application\b|"
    r"\bnow\s+accepting\b|\bsubmit\s+proposal\b|\bbid\s+notice\b",
    re.I
)

EXCLUSION_TERMS = re.compile(
    r"\bliquor\b|\balcohol\b|\blottery\b|\btobacco\b|\bvape\b|\bvaping\b|\bhemp\b|"
    r"\bplenary\s+retail\b|\bfarm\s+labor\b",
    re.I
)

DEADLINE_RE = re.compile(
    r"(?:deadline|due\s+date|submit\s+by|due\s+by|closes?|closing\s+date)[^\n]{0,60}"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"[^\n]{0,30}\d{4}",
    re.I
)

QUESTIONS_DEADLINE_RE = re.compile(
    r"(?:questions?\s+(?:due|deadline|due\s+by|must\s+be\s+submitted)|submit\s+questions?\s+by|"
    r"Q&A\s+deadline|inquiry\s+deadline|written\s+questions?\s+due)[^\n]{0,60}"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"[^\n]{0,30}\d{4}",
    re.I
)

DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}",
    re.I
)


def keyword_classify(text: str) -> dict | None:
    cannabis_hits = CANNABIS_TERMS.findall(text)
    rfp_hits      = RFP_TERMS.findall(text)
    if not cannabis_hits or not rfp_hits:
        return None

    exclusion_hits = EXCLUSION_TERMS.findall(text)
    if len(exclusion_hits) > len(cannabis_hits) * 2:
        return None

    deadline_match = DEADLINE_RE.search(text)
    deadline = deadline_match.group(0).strip() if deadline_match else ""
    questions_match = QUESTIONS_DEADLINE_RE.search(text)
    questions_deadline = questions_match.group(0).strip() if questions_match else ""
    dates = DATE_RE.findall(text)

    combined = re.compile(
        r"(?:cannabis|marijuana|dispensary|class\s*5|rfp|rfq|request\s+for\s+proposal)",
        re.I
    )
    match = combined.search(text)
    if match:
        start = max(0, match.start() - 200)
        end   = min(len(text), match.end() + 400)
        snippet = text[start:end].replace("\n", " ").strip()
    else:
        snippet = text[:400]

    score = len(cannabis_hits) + len(rfp_hits) - len(exclusion_hits)
    confidence = "high" if score >= 4 else "medium" if score >= 2 else "low"

    lt = re.findall(r"Class\s+[123456]|Class\s+(?:One|Two|Three|Four|Five|Six)|medical|adult.?use|retail", text, re.I)
    license_types = "; ".join(sorted(set(t.strip() for t in lt)))[:200]

    return {
        "rfp_title":            "",
        "application_deadline": deadline or (dates[0] if dates else ""),
        "questions_deadline":   questions_deadline,
        "license_types":        license_types,
        "confidence":           confidence,
        "snippet":              snippet[:600],
    }


# ---------------------------------------------------------------------------
# LLM classifier (fires when OPENAI_API_KEY is set)
# ---------------------------------------------------------------------------

def llm_extract(text: str, municipality: str) -> dict | None:
    if not OPENAI_API_KEY:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        prompt = f"""You are analyzing text from {municipality}'s official website.

Determine if this page contains a cannabis retail license RFP or application window (Class 5 / adult-use / recreational dispensary).

Text (truncated):
{text[:MAX_TEXT_CHARS]}

Respond with JSON only:
{{
  "is_cannabis_rfp": true/false,
  "rfp_title": "exact title or empty string",
  "application_deadline": "date the application is due — ISO format (YYYY-MM-DD) or plain date string, empty if not found",
  "questions_deadline": "date by which questions must be submitted to the township — ISO format or plain date string, empty if not found",
  "license_types": "e.g. Class 5 Retailer",
  "confidence": "high/medium/low",
  "snippet": "2-3 sentences answering: when is the application due, when must questions be submitted to the township, and where is the RFP posted or expected to be posted"
}}"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=350,
        )
        result = json.loads(response.choices[0].message.content)
        if result.get("is_cannabis_rfp"):
            return {
                "rfp_title":            result.get("rfp_title", ""),
                "application_deadline": result.get("application_deadline", ""),
                "questions_deadline":   result.get("questions_deadline", ""),
                "license_types":        result.get("license_types", ""),
                "confidence":           result.get("confidence", "medium"),
                "snippet":              result.get("snippet", ""),
            }
        return None
    except Exception as e:
        print(f"    [LLM] error: {e} — falling back to keyword classifier")
        return None


# ---------------------------------------------------------------------------
# First-run broad summarizers (any cannabis content, not just active RFPs)
# ---------------------------------------------------------------------------

def keyword_summarize(text: str) -> dict | None:
    """Return {date, summary} for any page with a cannabis mention.
    Does NOT require RFP terms — catches moratoriums, ordinances, windows, etc.
    """
    if not CANNABIS_TERMS.search(text):
        return None

    # Prefer a date near a cannabis mention; fall back to any date in the page
    cannabis_match = CANNABIS_TERMS.search(text)
    start = max(0, cannabis_match.start() - 300)
    end   = min(len(text), cannabis_match.end() + 600)
    window = text[start:end]

    deadline_match = DEADLINE_RE.search(window) or DEADLINE_RE.search(text)
    date = deadline_match.group(0).strip() if deadline_match else ""
    if not date:
        dates = DATE_RE.findall(window) or DATE_RE.findall(text)
        date = dates[0] if dates else ""

    snippet = window.replace("\n", " ").strip()[:500]

    return {"date": date, "summary": snippet}


def llm_summarize(text: str, municipality: str) -> dict | None:
    """Use GPT-4o-mini to extract any cannabis-related date + summary.
    Broader than llm_extract — catches moratoriums, ordinances, windows, etc.
    Returns {date, summary} or None if no cannabis content found.
    """
    if not OPENAI_API_KEY:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        prompt = f"""Analyze this page from {municipality}'s official website.

Does it mention anything about cannabis licensing, retail applications, moratoriums,
ordinances, application windows, or Class 5 (adult-use/recreational dispensary) activity?

Text (truncated):
{text[:MAX_TEXT_CHARS]}

Respond with JSON only:
{{
  "has_cannabis_content": true/false,
  "date": "the single most important date found (moratorium end, deadline, ordinance date, window open/close) — or empty string",
  "summary": "1-2 sentences describing what this page says about cannabis licensing. Empty string if nothing relevant."
}}"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=200,
        )
        result = json.loads(response.choices[0].message.content)
        if result.get("has_cannabis_content"):
            return {
                "date":    result.get("date", ""),
                "summary": result.get("summary", ""),
            }
        return None
    except Exception as e:
        print(f"    [LLM-summary] error: {e} — falling back to keyword summarizer")
        return None


# ---------------------------------------------------------------------------
# Seed loader
# ---------------------------------------------------------------------------

# Priority towns (hand-curated) — used by --priority flag
PRIORITY_TOWNS = {
    "Vineland", "Morristown", "East Windsor", "Jersey City", "Newark",
    "Paterson", "Trenton", "Camden City", "Ewing Township", "Atlantic City",
    "Edison", "Fort Lee", "Lodi", "Cliffside Park", "Secaucus", "Bayonne",
    "Red Bank", "Hackensack", "Hamilton Township", "Long Branch",
}


def _load_county_map() -> dict[str, str]:
    """municipality name (lower) -> county, loaded from opted-in CSV."""
    county_map = {}
    if not OPT_IN_FILE.exists():
        return county_map
    with open(OPT_IN_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row.get("municipality", "").strip()
            county = row.get("county", "").strip()
            if name:
                county_map[name.lower()] = county
    return county_map


def load_seeds_from_notion(town_filter=None, priority_only=False) -> list[dict]:
    """Read monitoring URLs from the Notion RFPs Monitoring Database."""
    if not NOTION_TOKEN:
        raise RuntimeError("NOTION_TOKEN not set in .env — cannot load from Notion")

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    county_map = _load_county_map()
    rows = []
    cursor = None

    while True:
        payload: dict = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor

        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        for page in data.get("results", []):
            props = page.get("properties", {})

            title_parts = props.get("Name", {}).get("title", [])
            muni = title_parts[0]["plain_text"].strip() if title_parts else ""
            if not muni:
                continue

            if town_filter and muni.lower() != town_filter.lower():
                continue
            if priority_only and muni not in PRIORITY_TOWNS:
                continue

            county = county_map.get(muni.lower(), "")

            files = props.get("Monitoring URL", {}).get("files", [])
            for f in files:
                url = f.get("external", {}).get("url", "").strip()
                if url:
                    rows.append({
                        "municipality": muni,
                        "county":       county,
                        "monitor_url":  url,
                    })

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return rows


def load_seeds_from_csv(town_filter=None, priority_only=False) -> list[dict]:
    rows = []
    with open(SEED_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if town_filter and row["municipality"].lower() != town_filter.lower():
                continue
            if priority_only and row["municipality"] not in PRIORITY_TOWNS:
                continue
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Core monitor loop  (batch mode)
# ---------------------------------------------------------------------------

def send_hit_alert(hit: dict):
    """Send a professional HTML email alert for a confirmed cannabis RFP hit."""
    if not all([SMTP_USER, SMTP_PASS, ALERT_TO]):
        return

    muni      = hit.get("municipality", "Unknown")
    county    = hit.get("county", "")
    deadline  = hit.get("deadline") or "Not specified"
    lic_type  = hit.get("license_types") or "Cannabis License"
    confidence= hit.get("confidence", "").upper()
    url       = hit.get("monitor_url", "")
    snippet   = hit.get("snippet", "")[:400]
    rfp_title = hit.get("rfp_title", "")
    location  = f"{muni}, NJ" + (f" ({county} County)" if county else "")
    run_date  = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    # Detect signal type from content
    snippet_lower = (snippet + rfp_title).lower()
    dl_lower = deadline.lower()
    if any(k in snippet_lower or k in rfp_title.lower() for k in ["request for proposal", "rfp", "notice of rfp", "proposals due"]):
        signal_type  = "ACTIVE RFP"
        signal_color = "#16a34a"   # green
        signal_bg    = "#f0fdf4"
        signal_icon  = "🟢"
        signal_desc  = "An active Request for Proposals has been posted. This is a live bidding opportunity with a submission deadline."
        header_grad  = "linear-gradient(135deg,#14532d 0%,#166534 100%)"
    elif "no deadline" in dl_lower or "rolling" in dl_lower or "open" in dl_lower:
        signal_type  = "OPEN APPLICATION"
        signal_color = "#2563eb"   # blue
        signal_bg    = "#eff6ff"
        signal_icon  = "🔵"
        signal_desc  = "An open/rolling application process is available. No fixed deadline — apply at your own pace."
        header_grad  = "linear-gradient(135deg,#1e3a8a 0%,#1d4ed8 100%)"
    elif any(k in snippet_lower for k in ["ordinance", "amendment", "amend", "supplementing", "chapter", "prohibition"]):
        signal_type  = "ORDINANCE / AMENDMENT"
        signal_color = "#b45309"   # amber
        signal_bg    = "#fffbeb"
        signal_icon  = "🟡"
        signal_desc  = "A cannabis-related ordinance or code amendment was detected. This is NOT an RFP — monitor this municipality for an upcoming application window."
        header_grad  = "linear-gradient(135deg,#78350f 0%,#b45309 100%)"
    else:
        signal_type  = "LEGISLATIVE PRECURSOR"
        signal_color = "#7c3aed"   # purple
        signal_bg    = "#f5f3ff"
        signal_icon  = "🟣"
        signal_desc  = "Cannabis licensing legislation detected. An RFP or application window may follow — watch this municipality closely."
        header_grad  = "linear-gradient(135deg,#4c1d95 0%,#7c3aed 100%)"

    conf_color = {"HIGH": "#16a34a", "MEDIUM": "#d97706", "LOW": "#6b7280"}.get(confidence, "#6b7280")
    deadline_urgent = deadline not in ("Not specified", "unknown", "", "No deadline — rolling/open process")

    subject = f"[{signal_type}] {muni}, NJ — Cannabis License Alert"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:32px 0;">
    <tr><td align="center">
      <table width="620" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

        <!-- Header -->
        <tr>
          <td style="background:{header_grad};padding:32px 40px;text-align:center;">
            <p style="margin:0 0 6px 0;color:rgba(255,255,255,0.7);font-size:12px;font-weight:600;letter-spacing:2px;text-transform:uppercase;">NJ Cannabis RFP Monitor</p>
            <h1 style="margin:0;color:#ffffff;font-size:26px;font-weight:700;line-height:1.3;">Cannabis License Signal Detected</h1>
            <p style="margin:10px 0 0 0;color:rgba(255,255,255,0.6);font-size:13px;">{run_date}</p>
          </td>
        </tr>

        <!-- Signal Type Banner -->
        <tr>
          <td style="padding:0;">
            <div style="background:{signal_bg};border-bottom:3px solid {signal_color};padding:16px 40px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td>
                    <p style="margin:0 0 4px 0;font-size:18px;font-weight:800;color:{signal_color};">{signal_type}</p>
                    <p style="margin:0;font-size:13px;color:#475569;line-height:1.5;">{signal_desc}</p>
                  </td>
                  <td width="60" style="text-align:right;font-size:32px;vertical-align:middle;">{signal_icon}</td>
                </tr>
              </table>
            </div>
          </td>
        </tr>

        <!-- Confidence Badge -->
        <tr>
          <td style="padding:0;text-align:center;background:#f8fafc;">
            <div style="display:inline-block;margin:0;padding:8px 40px;background:{conf_color};color:#fff;font-size:12px;font-weight:700;letter-spacing:1px;">
              {confidence} CONFIDENCE MATCH
            </div>
          </td>
        </tr>

        <!-- Municipality Hero -->
        <tr>
          <td style="padding:32px 40px 0 40px;text-align:center;">
            <h2 style="margin:0;font-size:32px;font-weight:800;color:#1e3a5f;">{muni}</h2>
            <p style="margin:6px 0 0 0;color:#64748b;font-size:15px;">{county + " County, NJ" if county else "New Jersey"}</p>
          </td>
        </tr>

        <!-- Key Details -->
        <tr>
          <td style="padding:24px 40px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <!-- Deadline -->
                <td width="50%" style="padding-right:10px;">
                  <div style="background:{'#fef2f2' if deadline_urgent else '#f8fafc'};border:1px solid {'#fca5a5' if deadline_urgent else '#e2e8f0'};border-radius:10px;padding:18px;text-align:center;">
                    <p style="margin:0 0 4px 0;font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;">Deadline</p>
                    <p style="margin:0;font-size:15px;font-weight:700;color:{'#dc2626' if deadline_urgent else '#475569'};">{deadline}</p>
                  </div>
                </td>
                <!-- License Type -->
                <td width="50%" style="padding-left:10px;">
                  <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:10px;padding:18px;text-align:center;">
                    <p style="margin:0 0 4px 0;font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;">License Type</p>
                    <p style="margin:0;font-size:15px;font-weight:700;color:#15803d;">{lic_type or "Cannabis License"}</p>
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        {"<!-- RFP Title --><tr><td style='padding:0 40px 16px 40px;'><div style='background:#eff6ff;border-left:4px solid #3b82f6;border-radius:4px;padding:14px 18px;'><p style='margin:0 0 4px 0;font-size:11px;font-weight:700;color:#3b82f6;text-transform:uppercase;letter-spacing:1px;'>RFP Title</p><p style='margin:0;font-size:14px;color:#1e40af;font-weight:600;'>" + rfp_title + "</p></div></td></tr>" if rfp_title else ""}

        <!-- Snippet -->
        <tr>
          <td style="padding:0 40px 24px 40px;">
            <p style="margin:0 0 10px 0;font-size:12px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;">Detected Content</p>
            <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px 18px;">
              <p style="margin:0;font-size:13px;color:#475569;line-height:1.7;">{snippet}{"..." if len(hit.get("snippet","")) > 400 else ""}</p>
            </div>
          </td>
        </tr>

        <!-- CTA Button -->
        <tr>
          <td style="padding:0 40px 32px 40px;text-align:center;">
            <a href="{url}" style="display:inline-block;background:linear-gradient(135deg,#1e3a5f,#2d6a4f);color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;padding:14px 36px;border-radius:8px;">
              View Source Page &rarr;
            </a>
            <p style="margin:12px 0 0 0;font-size:12px;color:#94a3b8;">{url}</p>
          </td>
        </tr>

        <!-- Divider -->
        <tr><td style="padding:0 40px;"><hr style="border:none;border-top:1px solid #e2e8f0;"></td></tr>

        <!-- Footer -->
        <tr>
          <td style="padding:20px 40px;text-align:center;">
            <p style="margin:0;font-size:12px;color:#94a3b8;">This alert was generated automatically by the <strong>NJ Cannabis RFP Monitor</strong>.<br>
            Verify all details directly with the municipality before taking action.</p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    plain = (
        f"NJ CANNABIS ALERT — {signal_type} | {confidence} CONFIDENCE\n"
        f"{'='*55}\n"
        f"SIGNAL TYPE  : {signal_type}\n"
        f"  {signal_desc}\n\n"
        f"Municipality : {location}\n"
        f"License Type : {lic_type}\n"
        f"Deadline     : {deadline}\n"
        f"Source URL   : {url}\n\n"
        f"Detected Content:\n{snippet}\n\n"
        f"Generated: {run_date}\n"
        f"Verify details directly with the municipality before acting."
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"NJ RFP Monitor <{SMTP_USER}>"
    msg["To"]      = ALERT_TO
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    sent = False
    # Try STARTTLS (port 587) then SSL (port 465)
    for attempt in [("starttls", SMTP_HOST, SMTP_PORT), ("ssl", SMTP_HOST, 465)]:
        try:
            if attempt[0] == "starttls":
                with smtplib.SMTP(attempt[1], attempt[2], timeout=15) as server:
                    server.starttls()
                    server.login(SMTP_USER, SMTP_PASS)
                    server.sendmail(SMTP_USER, ALERT_TO, msg.as_string())
            else:
                import ssl as _ssl
                ctx = _ssl.create_default_context()
                with smtplib.SMTP_SSL(attempt[1], attempt[2], context=ctx, timeout=15) as server:
                    server.login(SMTP_USER, SMTP_PASS)
                    server.sendmail(SMTP_USER, ALERT_TO, msg.as_string())
            print(f"  [EMAIL] Alert sent to {ALERT_TO} via {attempt[0].upper()}")
            sent = True
            break
        except Exception as e:
            print(f"  [EMAIL] {attempt[0].upper()} failed: {e}")

    if not sent:
        # Fallback: save alert to local file
        alerts_dir = ROOT / "hits" / "pending_alerts"
        alerts_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        alert_file = alerts_dir / f"alert_{muni.replace(' ','_')}_{ts}.html"
        alert_file.write_text(html, encoding="utf-8")
        print(f"  [EMAIL] SMTP blocked — alert saved to {alert_file}")


def _process_result(seed, text, con, hits_this_run, verbose):
    """Classify one scraped page and record any hit. Returns True if a hit."""
    muni = seed["municipality"]
    url  = seed["monitor_url"]

    if not text or len(text) < 50:
        if verbose:
            print(f"  empty/tiny   {url[:70]}")
        # Still record the attempt so future runs know this was tried
        upsert_snapshot(con, muni, url, "EMPTY")
        return False

    content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    old_hash     = get_snapshot(con, muni, url)

    if old_hash == content_hash:
        if verbose:
            print(f"  unchanged    {url[:70]}")
        return False

    print(f"  NEW/CHANGED  {url[:70]}")
    upsert_snapshot(con, muni, url, content_hash)

    hit = llm_extract(text, muni) or keyword_classify(text)

    if hit:
        print(f"  *** CANNABIS RFP HIT [{hit['confidence'].upper()}] ***")
        print(f"      App deadline : {hit.get('application_deadline') or 'unknown'}")
        print(f"      Q's deadline : {hit.get('questions_deadline') or 'unknown'}")
        print(f"      License type : {hit['license_types'] or 'unknown'}")
        print(f"      Snippet      : {hit['snippet'][:120]}")
        app_dl = hit.get("application_deadline", "") or hit.get("deadline", "")
        full_hit = {
            "municipality":        muni,
            "county":              seed["county"],
            "monitor_url":         url,
            "rfp_title":           hit.get("rfp_title", ""),
            "deadline":            app_dl,  # legacy field — mirrors application_deadline
            "application_deadline": app_dl,
            "questions_deadline":   hit.get("questions_deadline", ""),
            "license_types":        hit.get("license_types", ""),
            "confidence":           hit.get("confidence", ""),
            "snippet":              hit.get("snippet", ""),
            "first_seen":           datetime.now(timezone.utc).isoformat(),
        }
        save_hit(con, full_hit)
        hits_this_run.append(full_hit)
        send_hit_alert(full_hit)
        return True

    if verbose:
        print(f"  no cannabis RFP signals found")
    return False


def _flush_hits_csv(new_hits: list[dict]):
    """Append new hit rows to rfp_hits.csv immediately."""
    if not new_hits:
        return
    HITS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["municipality","county","monitor_url","rfp_title","deadline","application_deadline","questions_deadline","license_types","confidence","snippet","first_seen"]
    write_header = not HITS_FILE.exists()
    with open(HITS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerows(new_hits)


def _flush_first_run_csv(new_rows: list[dict]):
    """Append new first-run summary rows to first_run_summary.csv immediately."""
    if not new_rows:
        return
    FIRST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_header = not FIRST_RUN_FILE.exists()
    with open(FIRST_RUN_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["town", "date", "summary"])
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)


def run_monitor(seeds, con, verbose=False, first_run=False) -> list[dict]:
    HITS_FILE.parent.mkdir(parents=True, exist_ok=True)

    all_hits: list[dict] = []
    # town -> best {date, summary} seen across all its URLs (accumulated this run)
    first_run_rows: dict[str, dict] = {}
    # towns already written to first_run CSV this run (avoid duplicates on resume)
    written_first_run: set[str] = set()

    total_batches = (len(seeds) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num, batch_start in enumerate(range(0, len(seeds), BATCH_SIZE), 1):
        batch = seeds[batch_start : batch_start + BATCH_SIZE]
        urls  = [s["monitor_url"] for s in batch]

        print(f"\n=== Batch {batch_num}/{total_batches} — {len(batch)} URLs ===")

        try:
            results = firecrawl_batch_scrape(urls)
        except Exception as e:
            print(f"  BATCH ERROR: {e}")
            continue

        batch_hits: list[dict] = []
        current_town = ""
        for seed in batch:
            muni = seed["municipality"]
            url  = seed["monitor_url"]

            if muni != current_town:
                current_town = muni
                print(f"\n[ {muni} — {seed['county']} ]")

            text = results.get(url, "")
            _process_result(seed, text, con, batch_hits, verbose)

            # First-run: run broad summarizer on every page with any text
            if first_run and text and len(text) >= 50:
                summary = llm_summarize(text, muni) or keyword_summarize(text)
                if summary and summary.get("summary"):
                    existing = first_run_rows.get(muni)
                    # Keep the row with the best date (non-empty preferred)
                    if not existing or (not existing["date"] and summary["date"]):
                        first_run_rows[muni] = {
                            "town":    muni,
                            "date":    summary["date"],
                            "summary": summary["summary"],
                        }

        # Flush hits and first-run rows to CSV after every batch
        if batch_hits:
            _flush_hits_csv(batch_hits)
            all_hits.extend(batch_hits)

        if first_run:
            new_rows = [v for k, v in first_run_rows.items() if k not in written_first_run]
            if new_rows:
                _flush_first_run_csv(new_rows)
                written_first_run.update(r["town"] for r in new_rows)

    if first_run:
        total_written = len(written_first_run)
        print(f"\nFirst-run summary: {total_written} towns with cannabis content -> {FIRST_RUN_FILE}")

    return all_hits


# ---------------------------------------------------------------------------
# Deep-dive mode  (--deep <town>)
# ---------------------------------------------------------------------------

def _save_workspace(town: str, workspace: dict) -> Path:
    """Write the current workspace dict to hits/deep_dives/<slug>.json."""
    DEEP_DIVE_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", town.lower()).strip("_")
    path = DEEP_DIVE_DIR / f"{slug}.json"
    path.write_text(json.dumps(workspace, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def run_deep_dive(town: str, con: sqlite3.Connection, refresh_ordinance: bool = False) -> None:
    """Comprehensive single-town research pipeline (--deep mode).

    Fills a workspace dict step by step and saves a JSON report after every
    completed sub-task.  When Notion is wired up (Phase 2), each step will
    also write into the town's Notion workspace page.

    Sub-tasks:
      [1/6] ordinance_finder    — deep_dive/ordinance.py       LIVE
      [2/6] council_vote_tagger — deep_dive/council_votes.py   LIVE
      [3/6] zoning_finder       — deep_dive/zoning.py          LIVE
      [4/6] rfp_signal_check    — deep_dive/rfp_signals.py     LIVE
      [5/6] attorney_finder     — deep_dive/attorneys.py       LIVE
      [6/6] email_drafter       — deep_dive/email_drafter.py   stub
    """
    county_map = _load_county_map()
    county = county_map.get(town.lower(), "")
    location = f"{town}, NJ" + (f" ({county} County)" if county else "")

    reset_run_state()   # clear per-process URL cache + credit counter

    print(f"\n{'='*60}")
    print(f"DEEP DIVE -- {location}")
    print(f"Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")

    workspace = {
        "municipality":  town,
        "county":        county,
        "run_date":      datetime.now(timezone.utc).isoformat(),
        "ordinance":     {},   # {url, title, ordinance_number, adopted_date, …}
        "council_votes": [],   # [{name, role, vote, friendly}]
        "zoning":        {},   # {url, description, zones_confirmed}
        "rfp_signals":   [],   # [{url, signal_type, snippet, confidence}]
        "attorneys":     [],   # [{name, firm, cases, wins, losses, win_rate}]
        "draft_emails":  [],   # [{to_role, recipient, subject, body}]
    }

    # -----------------------------------------------------------------------
    # [1/6] Ordinance finder
    # -----------------------------------------------------------------------
    print("\n[1/6] Ordinance finder...")
    ordinance = find_ordinance(town, con, refresh=refresh_ordinance)
    workspace["ordinance"] = ordinance
    _save_workspace(town, workspace)   # save after every step

    if ordinance.get("found"):
        if ordinance.get("is_prohibition"):
            print(f"  PROHIBITION — {town} has opted OUT of cannabis retail.")
            print(f"  Source : {ordinance.get('url', 'unknown')}")
            print(f"\n  Skipping remaining sub-tasks.")
            path = _save_workspace(town, workspace)
            print(f"\n{'='*60}")
            print(f"Deep dive complete for {town}.")
            print(f"Report saved : {path}")
            print(f"{'='*60}\n")
            return
        else:
            print(f"  Found  : {ordinance.get('title', 'Cannabis Ordinance')}")
            print(f"  Ord #  : {ordinance.get('ordinance_number') or 'not extracted'}")
            print(f"  Adopted: {ordinance.get('adopted_date') or 'not extracted'}")
            print(f"  Zones  : {', '.join(ordinance.get('allowed_zones', [])) or 'not extracted'}")
            print(f"  Cap    : {ordinance.get('cap') or 'not extracted'}")
            print(f"  App fee: {ordinance.get('application_fee') or 'not extracted'}")
            print(f"  URL    : {ordinance.get('url', '')}")
    else:
        print(f"  Not found — check manually. Queries tried:")
        for q in ordinance.get("queries_tried", []):
            print(f"    {q}")

    # -----------------------------------------------------------------------
    # [2/6] Council vote tagger
    # -----------------------------------------------------------------------
    print("\n[2/6] Council vote tagger...")
    council_result = find_council_votes(town, con)
    workspace["council_votes"] = council_result
    _save_workspace(town, workspace)

    members    = council_result.get("members", [])
    friendlies = [m for m in members if m.get("friendly") and m.get("still_in_office")]
    yes_votes  = [m for m in members if m.get("vote") in ("yes", "aye")]
    no_votes   = [m for m in members if m.get("vote") == "no"]

    print(f"  Members found   : {len(members)}")
    print(f"  Yes votes       : {len(yes_votes)}  |  No votes: {len(no_votes)}")
    print(f"  Still in office : {sum(1 for m in members if m.get('still_in_office'))}")
    print(f"  Friendly targets: {len(friendlies)}")
    print(f"  Vote source     : {council_result.get('vote_source_type', 'none')}")
    if council_result.get("needs_foia"):
        print(f"  *** NEEDS FOIA -- no roll-call vote found; draft FOIA to town clerk ***")
    for m in friendlies[:3]:
        contact = m.get("email") or m.get("phone") or "no contact"
        print(f"    {m['name']} ({m.get('current_title', '')}) -- {contact}")
    if not members:
        print("  No council data found -- check manually")

    # -----------------------------------------------------------------------
    # [3/6] Zoning overlay finder
    # -----------------------------------------------------------------------
    print("\n[3/6] Zoning overlay finder...")
    zoning = find_zoning(town, ordinance, con)
    workspace["zoning"] = zoning
    _save_workspace(town, workspace)

    if zoning.get("found"):
        zones = zoning.get("zones", [])
        print(f"  Zones profiled  : {len(zones)}")
        for z in zones:
            permitted = z.get("cannabis_retail_permitted")
            flag = "YES" if permitted else ("NO" if permitted is False else "?")
            print(f"    [{flag}] {z.get('name', '?')}  ({z.get('confidence', '?')} confidence)")
            if z.get("setbacks"):
                print(f"         Setbacks : {z['setbacks']}")
            if z.get("min_lot_size"):
                print(f"         Min lot  : {z['min_lot_size']}")
        ov = zoning.get("cannabis_overlay")
        if ov:
            print(f"  Overlay found   : {ov.get('overlay_name', 'Yes')} — {ov.get('url', '')}")
        if zoning.get("zoning_map_url"):
            print(f"  Map PDF         : {zoning['zoning_map_url']}")
        if zoning.get("gis_portal_url"):
            print(f"  GIS portal      : {zoning['gis_portal_url']}")
        src = zoning.get("zones_source", "")
        if src == "discovered":
            print(f"  *** Zones were DISCOVERED (not in ordinance text) — verify manually ***")
    else:
        reason = zoning.get("reason", "no_data")
        if reason == "prohibition":
            print(f"  Prohibition — no zones apply")
        elif reason == "zones_unknown":
            print(f"  *** NEEDS FOIA — {zoning.get('foia_note', '')}")
        else:
            print(f"  No zoning data found — check manually")

    # -----------------------------------------------------------------------
    # [4/6] RFP signal check
    # -----------------------------------------------------------------------
    print("\n[4/6] RFP signal check...")
    signals_result = check_rfp_signals(town, con, ordinance=ordinance)
    workspace["rfp_signals"] = signals_result
    _save_workspace(town, workspace)

    if signals_result.get("found"):
        signals = signals_result.get("signals", [])
        by_type: dict[str, int] = {}
        for s in signals:
            by_type[s["type"]] = by_type.get(s["type"], 0) + 1
        print(f"  Signals found   : {len(signals)}")
        for sig_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
            print(f"    {sig_type:<22s} x {count}")

        awarded = signals_result.get("awarded_licenses", [])
        if awarded:
            print(f"  Awarded licenses: {len(awarded)}")
            for a in awarded[:5]:
                print(f"    [{a.get('license_status', '?')}] "
                      f"{a.get('licensee', '?')} -- {a.get('address', 'no address')}")

        cap = signals_result.get("cap_status", {})
        if cap.get("cap") not in ("", None):
            sat = " (SATURATED)" if cap.get("saturated") else ""
            slots = cap.get("slots_open")
            slots_str = f"{slots} open" if slots is not None else "unknown slots"
            print(f"  Cap status      : {cap.get('awarded', 0)} / {cap.get('cap', '?')} "
                  f"-- {slots_str}{sat}")

        next_date = signals_result.get("next_action_date")
        if next_date:
            print(f"  *** NEXT ACTION DATE: {next_date} ***")

        # Highlight live RFPs
        live_rfps = [s for s in signals if s.get("type") == "LIVE_RFP"]
        for s in live_rfps[:3]:
            print(f"  LIVE RFP        : {s.get('title', '')[:60]}")
            print(f"    Deadline      : {s.get('application_deadline', 'unknown')}")
            print(f"    URL           : {s.get('url', '')}")
    else:
        print(f"  No signals found -- may need FOIA to confirm status")

    # -----------------------------------------------------------------------
    # [5/6] Attorney finder
    # -----------------------------------------------------------------------
    print("\n[5/6] Attorney finder...")
    attorneys_result = find_attorneys(town, con, ordinance=ordinance, council_votes=council_result)
    workspace["attorneys"] = attorneys_result
    _save_workspace(town, workspace)

    if attorneys_result.get("town_solicitor"):
        sol = attorneys_result["town_solicitor"]
        print(f"  Town solicitor  : {sol.get('name', '?')} / {sol.get('firm', '?')} (excluded from picks)")

    if attorneys_result.get("found"):
        attorneys = attorneys_result.get("attorneys", [])
        print(f"  Attorneys found : {len(attorneys)}")
        for a in attorneys[:5]:
            tier  = a.get("tier", "?")
            score = a.get("score", 0)
            n     = len(a.get("appearances", []))
            w     = a.get("this_town_wins", 0)
            l     = a.get("this_town_losses", 0)
            can   = " [cannabis]" if a.get("cannabis_experience") else ""
            print(f"    [{tier}:{score:02d}] {a.get('name', '?')} / {a.get('firm', '?')}  "
                  f"-- {n} appearance(s), {w}W-{l}L{can}")
        top = attorneys_result.get("top_picks", [])
        if top:
            print(f"  Top picks       : {', '.join(p['name'] for p in top)}")
    elif attorneys_result.get("needs_foia"):
        print(f"  No attorneys found -- flagged for FOIA")

    # -----------------------------------------------------------------------
    # [6/6] Email drafter
    # -----------------------------------------------------------------------
    print("\n[6/6] Email drafter...")
    draft_results = draft_emails(workspace)
    workspace["draft_emails"] = draft_results
    _save_workspace(town, workspace)

    _ROLE_LABELS = {
        "Town Clerk":     "E1 Town Clerk   ",
        "Council Member": "E2 Council Mbr  ",
        "Zoning Officer": "E3 Zoning Officer",
        "Attorney":       "E4 Attorney     ",
    }
    for email in draft_results:
        role    = email.get("to_role", "?")
        label   = _ROLE_LABELS.get(role, f"   {role:<16}")
        rname   = email.get("recipient_name") or "(unknown)"
        remail  = email.get("recipient_email") or "(no email)"
        status  = email.get("status", "Draft")
        print(f"  {label}: {rname:<22} {remail:<32} [{status}]")

    path = _save_workspace(town, workspace)
    print(f"\n{'='*60}")
    print(f"Deep dive complete for {town}.")
    print(f"Report saved : {path}")
    print(f"Firecrawl credits used (est.): ~{credits_used()}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="NJ Cannabis RFP Monitor")
    parser.add_argument("--town",     help="Monitor a single town (debug mode)")
    parser.add_argument("--limit",    type=int, help="Process at most N URLs (use 1 for quick test)")
    parser.add_argument("--priority", action="store_true", help="Only hand-curated priority towns")
    parser.add_argument("--verbose",  action="store_true", help="Show unchanged URLs too")
    parser.add_argument("--reset",    action="store_true", help="Clear snapshot DB (re-scan all)")
    parser.add_argument("--csv",      action="store_true", help="Use rfp_seed_urls.csv instead of Notion")
    parser.add_argument("--first-run", action="store_true", dest="first_run",
                        help="Also write first_run_summary.csv (Town, Date, Summary) for every town with cannabis content")
    parser.add_argument("--deep", metavar="TOWN",
                        help="Deep-dive research mode: finds ordinance, council votes, zoning, attorneys, drafts 4 emails")
    parser.add_argument("--refresh-ordinance", action="store_true", dest="refresh_ordinance",
                        help="Force re-search the ordinance even if it is already cached (use with --deep)")
    args = parser.parse_args()

    # Deep-dive mode — completely separate path from the daily monitor loop
    if args.deep:
        if not FIRECRAWL_API_KEY:
            print("ERROR: Set FIRECRAWL_API_KEY in nj_rfp_monitor/.env first.")
            return
        con = init_db(DB_FILE)
        try:
            run_deep_dive(args.deep, con, refresh_ordinance=args.refresh_ordinance)
        except BudgetExceededError as e:
            print(f"\n[BUDGET] {e}")
            print(f"[BUDGET] Partial workspace saved. Re-run with FIRECRAWL_BUDGET=1200 to raise limit.")
        con.close()
        return

    if not FIRECRAWL_API_KEY:
        print("ERROR: Set FIRECRAWL_API_KEY in nj_rfp_monitor/.env first.")
        return

    con = init_db(DB_FILE)

    if args.reset:
        con.execute("DELETE FROM page_snapshots")
        con.commit()
        print("Snapshot DB cleared — full re-scan will run.")

    if args.csv:
        if not SEED_FILE.exists():
            print(f"ERROR: Seed file missing: {SEED_FILE}")
            print(f"Run: python scripts/build_rfp_seed_urls.py  first.")
            con.close()
            return
        seeds = load_seeds_from_csv(town_filter=args.town, priority_only=args.priority)
        source = f"CSV ({SEED_FILE.name})"
    else:
        if not NOTION_TOKEN:
            print("ERROR: Set NOTION_TOKEN in nj_rfp_monitor/.env first (or use --csv).")
            con.close()
            return
        try:
            seeds = load_seeds_from_notion(town_filter=args.town, priority_only=args.priority)
        except Exception as e:
            print(f"ERROR loading from Notion: {e}")
            con.close()
            return
        source = "Notion RFPs Monitoring Database"

    if args.limit:
        seeds = seeds[:args.limit]

    print(f"NJ Cannabis RFP Monitor — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"Source            : {source}")
    print(f"Mode              : {'FIRST-RUN (writing first_run_summary.csv)' if args.first_run else 'normal'}")
    print(f"FIRECRAWL_API_KEY : {'set' if FIRECRAWL_API_KEY else 'MISSING'}")
    print(f"OPENAI_API_KEY    : {'set' if OPENAI_API_KEY else 'not set (keyword classifier only)'}")
    print(f"URLs to check     : {len(seeds)}")
    print(f"DB                : {DB_FILE}")
    print("=" * 60)

    hits = run_monitor(seeds, con, verbose=args.verbose, first_run=args.first_run)

    print("\n" + "=" * 60)
    print(f"Run complete.  Hits this run: {len(hits)}")
    if hits:
        print(f"Saved to: {HITS_FILE}")
        print("\nSUMMARY OF HITS:")
        for h in hits:
            print(f"  {h['municipality']} ({h['county']}) [{h['confidence']}]")
            print(f"    {h['monitor_url']}")
            print(f"    Deadline: {h['deadline'] or 'not found'}")
            print()

    con.close()


if __name__ == "__main__":
    main()
