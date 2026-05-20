"""
Search meeting minutes of NJ target towns for cannabis keywords.
Extracts three insight fields from each hit:
  - approval_status  : e.g. "ordinance passed", "under review", "moratorium"
  - timeline         : any date/deadline mentions near cannabis text
  - license_cap      : number of licenses town plans to issue

Input:  nj_cannabis/data/nj_portals.csv  (only rows with platform=agendacenter)
Output: nj_cannabis/output/nj_cannabis_insights.csv

Extend later with Legistar / CivicWeb scrapers as needed.
"""

import csv
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Reuse PDF utilities from the existing scraper
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scrapers.utils import keyword_in_pdf, download_pdf, make_session

PORTALS_FILE  = Path(__file__).parent.parent / "data"   / "nj_portals.csv"
OUTPUT_FILE   = Path(__file__).parent.parent / "output" / "nj_cannabis_insights.csv"
HITS_DIR      = Path(__file__).parent.parent / "hits"

KEYWORDS = ["cannabis", "cannabis retail", "dispensary", "marijuana license"]
WORKERS  = 10

_today      = date.today()
START_DATE  = (_today - timedelta(days=730)).strftime("%m/%d/%Y")  # 2-year window for NJ
END_DATE    = _today.strftime("%m/%d/%Y")

# ── Insight extraction patterns ───────────────────────────────────────────────

APPROVAL_PATTERNS = [
    (re.compile(r"ordinance.{0,60}(passed|adopted|approved)", re.I),  "ordinance passed"),
    (re.compile(r"(approved|adopted).{0,60}ordinance",        re.I),  "ordinance passed"),
    (re.compile(r"moratorium",                                re.I),  "moratorium"),
    (re.compile(r"opt[- ]out",                                re.I),  "opted out"),
    (re.compile(r"opt[- ]in",                                 re.I),  "opted in"),
    (re.compile(r"under.{0,20}review|pending.{0,20}approv",  re.I),  "under review"),
    (re.compile(r"denied|rejected|prohibited",               re.I),  "denied/prohibited"),
    (re.compile(r"application.{0,40}open",                   re.I),  "applications open"),
    (re.compile(r"resolution.{0,40}(passed|adopted)",        re.I),  "resolution passed"),
]

TIMELINE_PATTERN = re.compile(
    r"(?:by|before|no later than|effective|deadline)[^\n]{0,80}"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december"
    r"|\d{1,2}/\d{1,2}/\d{2,4}|\d{4})",
    re.I,
)

LICENSE_CAP_PATTERN = re.compile(
    r"(\d+)\s*(?:cannabis|marijuana|dispensary)?\s*(?:retail)?\s*licens",
    re.I,
)


def extract_insights(text: str) -> dict:
    approval  = ""
    timeline  = ""
    cap       = ""

    for pattern, label in APPROVAL_PATTERNS:
        if pattern.search(text):
            approval = label
            break

    tm = TIMELINE_PATTERN.search(text)
    if tm:
        timeline = tm.group(0).strip()[:120]

    caps = LICENSE_CAP_PATTERN.findall(text)
    if caps:
        # Take the most common number (avoids picking up street addresses etc.)
        from collections import Counter
        cap = Counter(caps).most_common(1)[0][0]

    return {"approval_status": approval, "timeline": timeline, "license_cap": cap}


def _parse_agendacenter_results(base_url: str, html: str) -> list[dict]:
    soup  = BeautifulSoup(html, "html.parser")
    docs  = []
    seen  = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "ViewFile" not in href or href in seen:
            continue
        seen.add(href)

        if "/Minutes/" in href:
            dtype = "Minutes"
        elif "/Agenda/" in href and "html=true" not in href and "packet=true" not in href:
            dtype = "Agenda"
        else:
            continue

        full_url = base_url.rstrip("/") + href if href.startswith("/") else href
        # Extract date from path like /ViewFile/Agenda/12345-2024-11-05
        date_m = re.search(r"(\d{4}-\d{2}-\d{2})", href)
        date_str = date_m.group(1) if date_m else ""
        docs.append({"url": full_url, "type": dtype, "date": date_str})

    return docs


def scrape_agendacenter(row: dict) -> list[dict]:
    name     = row["municipality"]
    base_url = row["base_url"]
    session  = make_session()

    search_url = (
        f"{base_url.rstrip('/')}/AgendaCenter/Search/"
        f"?term=cannabis&CIDs=all&startDate={START_DATE}&endDate={END_DATE}"
        f"&dateRange=custom&dateSelector="
    )

    try:
        r = session.get(search_url, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"  [X] {name}: {e}")
        return []

    docs = _parse_agendacenter_results(base_url, r.text)
    if not docs:
        return []

    hits_dir = HITS_DIR / "agendacenter" / re.sub(r"[^a-z0-9]", "_", name.lower())
    hits_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for doc in docs:
        pdf_bytes = download_pdf(doc["url"], session)
        if not pdf_bytes:
            continue

        matched = keyword_in_pdf(pdf_bytes, KEYWORDS)
        if not matched:
            continue

        # Save PDF
        fname = f"{doc['date']}_{doc['type']}_{name.replace(' ', '_')}.pdf"
        fpath = hits_dir / fname
        fpath.write_bytes(pdf_bytes)

        # Extract text for insights (pdfplumber if available, else skip)
        insights = {"approval_status": "", "timeline": "", "license_cap": ""}
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages[:10])
            insights = extract_insights(text)
        except Exception:
            pass

        results.append({
            "municipality": name,
            "county":       row["county"],
            "platform":     "agendacenter",
            "doc_type":     doc["type"],
            "date":         doc["date"],
            "url":          doc["url"],
            "file_path":    str(fpath),
            "keywords":     ", ".join(matched),
            **insights,
        })
        time.sleep(0.3)

    return results


def load_portals(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["platform"] == "agendacenter" and r["base_url"]]


def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    HITS_DIR.mkdir(parents=True, exist_ok=True)

    portals = load_portals(PORTALS_FILE)
    print(f"Scraping {len(portals)} AgendaCenter portals for cannabis keywords ...")

    all_results = []

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(scrape_agendacenter, r): r for r in portals}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                hits = fut.result()
                all_results.extend(hits)
                if hits:
                    print(f"  [{i}/{len(portals)}] HIT: {hits[0]['municipality']} — {len(hits)} doc(s)")
            except Exception as e:
                print(f"  [{i}] Error: {e}")

    if not all_results:
        print("No cannabis hits found.")
        return

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "municipality", "county", "platform", "doc_type", "date",
            "url", "file_path", "keywords",
            "approval_status", "timeline", "license_cap",
        ])
        writer.writeheader()
        writer.writerows(all_results)

    print(f"\nTotal hits     : {len(all_results)}")
    print(f"Towns with hits: {len({r['municipality'] for r in all_results})}")
    print(f"Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
