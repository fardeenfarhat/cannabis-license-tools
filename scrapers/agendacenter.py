"""Agent 1 — AgendaCenter (CivicPlus) scraper.

Uses the site's own /AgendaCenter/Search/?term= API.
Much faster than downloading every PDF.
Cities are searched in parallel (ThreadPoolExecutor); each worker gets its
own requests.Session.  Output is buffered per city and printed atomically.
"""

import io
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from .config import CityConfig, KEYWORDS, START_DATE, END_DATE
from .types import Hit, Platform
from .utils import safe_filename, extract_date_from_viewfile_path, keyword_in_pdf, download_pdf, make_session

_DT_START = datetime.strptime(START_DATE, "%Y-%m-%d")
_DT_END   = datetime.strptime(END_DATE,   "%Y-%m-%d")

_print_lock = threading.Lock()
WORKERS = 8


def _parse_search_results(base_url: str, html: str) -> list[dict]:
    """Parse AgendaCenter search results HTML -> list of doc dicts."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "ViewFile" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)

        if "/Minutes/" in href:
            doc_type = "Minutes"
        elif "/Agenda/" in href:
            if "html=true" in href or "packet=true" in href:
                continue
            doc_type = "Agenda"
        else:
            continue

        date_str = extract_date_from_viewfile_path(href)

        label = ""
        row = a
        for _ in range(8):
            row = row.parent
            if not row:
                break
            heading = row.find(["h2", "h3", "h4"])
            if heading:
                label = heading.get_text(strip=True)
                break
            for link in row.find_all("a", href=True):
                if "ViewFile" not in link["href"] and len(link.get_text(strip=True)) > 10:
                    label = link.get_text(strip=True)
                    break
            if label:
                break
        if not label:
            row_text = (row.get_text(" ", strip=True) if row else "") or a.get_text(strip=True)
            for noise in ["HTML PDF Packet Previous Versions", "Download", "Agenda Minutes", "HTML", "PDF", "Packet"]:
                row_text = row_text.replace(noise, "").strip()
            label = row_text[:100]

        full_url = base_url.rstrip("/") + href if href.startswith("/") else href
        results.append({"date": date_str, "type": doc_type, "path": href, "label": label, "url": full_url})

    return results


def _search_one_city(city: CityConfig, output_root: str) -> tuple[list[Hit], str]:
    """Search one city. Returns (hits, buffered_log_text)."""
    buf = io.StringIO()

    def p(*args, **kwargs):
        kwargs.setdefault("file", buf)
        print(*args, **kwargs)

    session = make_session()
    hits: list[Hit] = []

    base_url  = city.url
    city_name = city.name
    city_slug = city.slug
    folder    = os.path.join(output_root, "agendacenter", city_slug)
    os.makedirs(folder, exist_ok=True)

    p(f"\n{'='*60}")
    p(f"  [AgendaCenter] {city_name}")
    p(f"{'='*60}")

    ac_start   = _DT_START.strftime("%m/%d/%Y")
    ac_end     = _DT_END.strftime("%m/%d/%Y")
    search_url = (
        f"{base_url.rstrip('/')}/AgendaCenter/Search/"
        f"?term=cannabis&CIDs=all&startDate={ac_start}&endDate={ac_end}"
        f"&dateRange=custom&dateSelector="
    )

    try:
        r = session.get(search_url, timeout=30)
        r.raise_for_status()
    except Exception as e:
        p(f"  [X] Search failed: {e}")
        return hits, buf.getvalue()

    docs = _parse_search_results(base_url, r.text)

    def _in_range(doc: dict) -> bool:
        raw = doc.get("date", "")
        if not raw:
            return True
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
            return _DT_START <= dt <= _DT_END
        except ValueError:
            return True

    total = len(docs)
    docs  = [d for d in docs if _in_range(d)]
    skipped = total - len(docs)
    if skipped:
        p(f"  -> {skipped} doc(s) outside date range ({START_DATE} – {END_DATE}) skipped")
    p(f"  -> {len(docs)} document link(s) in search results")

    if not docs:
        return hits, buf.getvalue()

    for doc in docs:
        p(f"\n  [{doc['type']}] {doc['date']}  {doc['label'][:60]}")

        fname = safe_filename(f"{doc['date']}_{doc['type']}_{city_slug}") + ".pdf"
        fpath = os.path.join(folder, fname)

        if os.path.exists(fpath):
            p(f"    -> already saved")
            hits.append(Hit(city=city_name, platform=Platform.AGENDACENTER,
                            date=doc["date"], doc_type=doc["type"], label=doc["label"],
                            url=doc["url"], file_path=fpath, confirmed=True,
                            matched_keywords=KEYWORDS[:1]))
            continue

        pdf_bytes = download_pdf(doc["url"], session)
        if not pdf_bytes:
            p(f"    -> SKIP (not a valid PDF)")
            continue

        matched = keyword_in_pdf(pdf_bytes, KEYWORDS)

        if not matched and doc["type"] == "Agenda":
            packet_bytes = download_pdf(doc["url"] + "?packet=true", session)
            if packet_bytes and len(packet_bytes) > len(pdf_bytes):
                packet_matched = keyword_in_pdf(packet_bytes, KEYWORDS)
                if packet_matched:
                    pdf_bytes = packet_bytes
                    matched   = packet_matched
                    fname     = fname.replace("_Agenda_", "_Packet_")
                    fpath     = os.path.join(folder, fname)
                    p(f"    -> Packet {len(pdf_bytes)//1024}KB confirmed: {matched}")

        confirmed = bool(matched)
        p(f"    -> {len(pdf_bytes)//1024}KB  confirmed={confirmed}  keywords={matched}")

        with open(fpath, "wb") as f:
            f.write(pdf_bytes)
        p(f"    -> SAVED: {fname}")

        hits.append(Hit(city=city_name, platform=Platform.AGENDACENTER,
                        date=doc["date"], doc_type=doc["type"], label=doc["label"],
                        url=doc["url"], file_path=fpath, confirmed=confirmed,
                        matched_keywords=matched))
        time.sleep(0.5)

    return hits, buf.getvalue()


def search(cities: list[CityConfig], session: requests.Session, output_root: str) -> list[Hit]:
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
