"""Agent 5 — CivicClerk REST API scraper.

CivicClerk exposes an OData v4 API at https://[tenant].api.civicclerk.com/v1/
Key insight: requests MUST include Origin + Referer headers matching the portal
domain, or the API returns 404. No authentication or proxy needed.

Flow:
  1. GET /v1/Events  (paginated, filtered by date)
  2. Each event has publishedFiles[] with fileId
  3. Download via GET /v1/Meetings/GetAttachmentFile(fileId=X)
  4. Keyword-check the PDF

Cities are searched in parallel (ThreadPoolExecutor).
Output is buffered per city and printed atomically.
"""

import io
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .config import CityConfig, KEYWORDS, START_DATE, END_DATE
from .types import Hit, Platform
from .utils import safe_filename, keyword_in_pdf

_print_lock = threading.Lock()
WORKERS = 6

FILE_TYPE_PRIORITY = ["Minutes", "Agenda Packet", "Agenda"]  # prefer minutes


def _make_api_session(portal_url: str) -> requests.Session:
    """Session with CivicClerk CORS headers for this tenant."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin":     portal_url.rstrip("/"),
        "Referer":    portal_url.rstrip("/") + "/",
        "Accept":     "application/json",
    })
    return s


def _get_events(api_base: str, session: requests.Session) -> list[dict]:
    """Fetch all events in date range with their publishedFiles."""
    url = (
        f"{api_base}/Events"
        f"?$orderby=EventDate desc"
        f"&$filter=EventDate ge {START_DATE}T00:00:00Z and EventDate le {END_DATE}T23:59:59Z"
        f"&$top=200"
    )
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        return r.json().get("value", [])
    except Exception as e:
        return []


def _choose_files(published_files: list[dict]) -> list[dict]:
    """Pick the best files to download: minutes first, then packet, then agenda."""
    for priority_type in FILE_TYPE_PRIORITY:
        matches = [f for f in published_files if f.get("type", "").lower() == priority_type.lower()]
        if matches:
            return matches
    return published_files


def _search_one_city(city: CityConfig, output_root: str) -> tuple[list[Hit], str]:
    """Search one CivicClerk city. Returns (hits, buffered_log_text)."""
    buf = io.StringIO()

    def p(*args, **kwargs):
        kwargs.setdefault("file", buf)
        print(*args, **kwargs)

    hits: list[Hit] = []

    portal_url = city.url.rstrip("/")
    city_name  = city.name
    city_slug  = city.slug

    tenant   = portal_url.split("//")[1].split(".")[0]
    api_base = f"https://{tenant}.api.civicclerk.com/v1"

    folder = os.path.join(output_root, "civicclerk", city_slug)
    os.makedirs(folder, exist_ok=True)

    p(f"\n{'='*60}")
    p(f"  [CivicClerk] {city_name}  (tenant: {tenant})")
    p(f"{'='*60}")

    api_session = _make_api_session(portal_url)
    events      = _get_events(api_base, api_session)
    p(f"  -> {len(events)} event(s) in date range")

    for ev in events:
        published = ev.get("publishedFiles") or []
        if not published:
            continue

        ev_id   = ev.get("id")
        ev_name = ev.get("eventName", "Unknown")[:60]
        ev_date = (ev.get("eventDate") or "")[:10]

        files_to_check = _choose_files(published)
        p(f"\n  [{ev_date}] {ev_name}  ({len(files_to_check)} file(s) to check)")

        for f in files_to_check:
            fid         = f.get("fileId")
            ftype       = f.get("type", "Document")
            fname_label = f.get("name", f"file{fid}")

            fname = safe_filename(f"{ev_date}_{ev_id}_{ftype}_{fname_label}") + ".pdf"
            fpath = os.path.join(folder, fname)

            if os.path.exists(fpath):
                p(f"    [skip] {fname}")
                continue

            dl_url = f"{api_base}/Meetings/GetAttachmentFile(fileId={fid})"
            try:
                api_session.headers["Accept"] = "application/pdf, */*"
                r = api_session.get(dl_url, timeout=60)
                api_session.headers["Accept"] = "application/json"
            except Exception as e:
                p(f"    [!] Download error: {e}")
                continue

            if not r.ok or r.content[:4] != b"%PDF" or len(r.content) < 500:
                p(f"    SKIP (not a valid PDF, {len(r.content)}b, status={r.status_code})")
                continue

            matched = keyword_in_pdf(r.content, KEYWORDS)
            if matched:
                with open(fpath, "wb") as fp:
                    fp.write(r.content)
                p(f"    SAVED [{', '.join(matched)}] {len(r.content)//1024}KB -> {fname}")
                hits.append(Hit(
                    city=city_name, platform=Platform.CIVICCLERK,
                    date=ev_date, doc_type=ftype, label=ev_name,
                    url=dl_url, file_path=fpath, confirmed=True,
                    matched_keywords=matched,
                ))
            else:
                p(f"    no keywords  [{ftype}] {len(r.content)//1024}KB  {fname_label[:40]}")

            time.sleep(0.3)

    return hits, buf.getvalue()


def search(cities: list[CityConfig], session: requests.Session, output_root: str,
           headless: bool = True) -> list[Hit]:
    # headless param kept for API compatibility with orchestrator, unused here
    all_hits: list[Hit] = []

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_search_one_city, city, output_root): city for city in cities}
        for fut in as_completed(futures):
            city = futures[fut]
            try:
                city_hits, output = fut.result()
                with _print_lock:
                    sys.stdout.write(output)
                    sys.stdout.flush()
                all_hits.extend(city_hits)
            except Exception as exc:
                with _print_lock:
                    print(f"  [X] {city.name}: {exc}")

    return all_hits
