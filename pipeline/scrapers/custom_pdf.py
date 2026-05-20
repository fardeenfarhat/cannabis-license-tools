"""
custom_pdf scraper — generic PDF-link crawler.

Covers two classes of NJ municipality site:
  1. CivicPlus GovOffice/CivicEngage CMS  (detected_platform=civicplus)
     Agendas live at  /agendasminutes, /index.asp?SEC=…  and PDFs hosted on
     govoffice3.com or the same domain.
  2. Bare municipal sites  (detected_platform=custom_pdf)
     Agendas are simply linked as PDFs from /agendas, /minutes, or homepage.

Strategy:
  - Fetch the base URL plus a list of common agenda paths.
  - Collect every PDF link found, up to DEPTH=1 (follow non-PDF links once).
  - Download each PDF, keyword-check it, save hits.

Cities run in parallel (ThreadPoolExecutor).
"""

import io
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests

from .config import CityConfig, KEYWORDS, START_DATE, END_DATE
from .types import Hit, Platform
from .utils import safe_filename, keyword_in_pdf, download_pdf, make_session

_print_lock = threading.Lock()
WORKERS = 10
DEPTH   = 1   # follow non-PDF internal links this many levels deep

_DT_START = datetime.strptime(START_DATE, "%Y-%m-%d")
_DT_END   = datetime.strptime(END_DATE,   "%Y-%m-%d")

# Common agenda/minutes paths to probe on each site
AGENDA_PATHS = [
    "/",
    "/agendas",
    "/agendas-minutes",
    "/agendasminutes",
    "/minutes",
    "/government/agendas-minutes",
    "/government/meetings",
    "/meetings",
    "/council/meetings",
    "/township-committee",
    "/borough-council",
    "/city-council",
    "/board-of-commissioners",
    "/public-meetings",
    "/meeting-minutes",
    # WordPress-hosted municipal sites (e.g. Kearny)
    "/council-meeting-agendas",
    "/council-meeting-agendas/",
    "/council-meeting-videos-and-agendas",
    "/council-agenda",
    "/council-agenda/",
    # CivicEngage /cn/ sites (e.g. Sayreville)
    "/cn/Meetings/",
    "/cn/meetings/",
    "/cn/TownCouncil/",
]


def _same_domain(url: str, base: str) -> bool:
    return urlparse(url).netloc == urlparse(base).netloc


def _extract_pdf_links(html: str, page_url: str, base: str) -> list[str]:
    """Return absolute PDF URLs found in html."""
    pdfs = []
    for m in re.finditer(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I):
        href = m.group(1)
        full = urljoin(page_url, href)
        if full not in pdfs:
            pdfs.append(full)
    return pdfs


def _extract_internal_links(html: str, page_url: str, base: str) -> list[str]:
    """Return internal (same-domain) non-PDF links likely to lead to agenda pages."""
    links = []
    keywords = {"agenda", "minute", "meeting", "council", "committee", "board", "archive"}
    for m in re.finditer(r'href=["\']([^"\'#]+)["\']', html, re.I):
        href = m.group(1)
        full = urljoin(page_url, href)
        if not _same_domain(full, base):
            continue
        if full.lower().endswith(".pdf"):
            continue
        if any(k in full.lower() for k in keywords):
            links.append(full)
    return list(dict.fromkeys(links))  # deduplicate, preserve order


def _crawl(base_url: str, session: requests.Session) -> list[str]:
    """Crawl base_url and AGENDA_PATHS, returning all unique PDF URLs found."""
    visited:  set[str] = set()
    pdf_urls: list[str] = []

    def _fetch_and_collect(url: str, depth: int):
        if url in visited:
            return
        visited.add(url)
        try:
            r = session.get(url, timeout=15, allow_redirects=True)
            if r.status_code != 200:
                return
        except Exception:
            return

        html = r.text
        for pdf in _extract_pdf_links(html, url, base_url):
            if pdf not in pdf_urls:
                pdf_urls.append(pdf)

        if depth > 0:
            for link in _extract_internal_links(html, url, base_url)[:20]:
                _fetch_and_collect(link, depth - 1)
            time.sleep(0.1)

    # Also probe govoffice3 domain links found on the page
    for path in AGENDA_PATHS:
        _fetch_and_collect(base_url.rstrip("/") + path, DEPTH)
        time.sleep(0.05)

    return pdf_urls


def _date_in_range(url: str) -> bool:
    """Heuristic: extract year from PDF URL, skip if clearly out of range."""
    years = re.findall(r"20(\d{2})", url)
    if not years:
        return True
    year = int("20" + years[-1])
    return _DT_START.year <= year <= _DT_END.year


def _search_one_city(city: CityConfig, output_root: str) -> tuple[list[Hit], str]:
    buf = io.StringIO()

    def p(*args, **kwargs):
        kwargs.setdefault("file", buf)
        print(*args, **kwargs)

    session   = make_session()
    hits: list[Hit] = []
    base_url  = city.url
    city_name = city.name
    city_slug = city.slug
    folder    = os.path.join(output_root, "custom_pdf", city_slug)
    os.makedirs(folder, exist_ok=True)

    p(f"\n{'='*60}")
    p(f"  [custom_pdf] {city_name}")
    p(f"{'='*60}")

    pdf_urls = _crawl(base_url, session)
    pdf_urls = [u for u in pdf_urls if _date_in_range(u)]
    p(f"  -> {len(pdf_urls)} PDF link(s) in range")

    if not pdf_urls:
        return hits, buf.getvalue()

    for url in pdf_urls:
        fname = safe_filename(os.path.basename(urlparse(url).path) or "doc") + ".pdf"
        fpath = os.path.join(folder, fname)

        if os.path.exists(fpath):
            p(f"    -> already saved: {fname}")
            hits.append(Hit(city=city_name, platform=Platform.CUSTOM_PDF,
                            date="", doc_type="Document", label=fname,
                            url=url, file_path=fpath, confirmed=True,
                            matched_keywords=KEYWORDS[:1]))
            continue

        pdf_bytes = download_pdf(url, session)
        if not pdf_bytes:
            continue

        matched = keyword_in_pdf(pdf_bytes, KEYWORDS)
        if not matched:
            continue

        with open(fpath, "wb") as f:
            f.write(pdf_bytes)

        p(f"    -> HIT {fname}  keywords={matched}")
        hits.append(Hit(city=city_name, platform=Platform.CUSTOM_PDF,
                        date="", doc_type="Document", label=fname,
                        url=url, file_path=fpath, confirmed=True,
                        matched_keywords=matched))
        time.sleep(0.3)

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
                    import sys
                    sys.stdout.write(output)
                    sys.stdout.flush()
                all_hits.extend(city_hits)
            except Exception as exc:
                with _print_lock:
                    print(f"  [X] {city.name}: {exc}")

    return all_hits
