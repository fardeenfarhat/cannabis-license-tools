"""Agent 4 — civic-scraper library (CivicPlusSite).

Enumerates meeting assets for va-*.civicplus.com sites using the
civic-scraper library, then downloads and keyword-filters PDFs.

Cities are searched in parallel (ThreadPoolExecutor); each worker gets its
own requests.Session.  Output is buffered per city and printed atomically.
"""

import io
import os
import sys
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .config import CityConfig, KEYWORDS, START_DATE, END_DATE
from .types import Hit, Platform
from .utils import safe_filename, keyword_in_pdf, download_pdf, make_session

_print_lock = threading.Lock()
WORKERS = 8


def _ensure_civic_scraper():
    try:
        from civic_scraper.platforms import CivicPlusSite  # noqa: F401
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "civic-scraper", "-q"])


def _search_one_city(city: CityConfig, output_root: str) -> tuple[list[Hit], str]:
    """Search one CivicPlus site. Returns (hits, buffered_log_text)."""
    from civic_scraper.platforms import CivicPlusSite

    buf = io.StringIO()

    def p(*args, **kwargs):
        kwargs.setdefault("file", buf)
        print(*args, **kwargs)

    session   = make_session()
    hits: list[Hit] = []

    base_url  = city.url
    city_name = city.name
    city_slug = city.slug
    folder    = os.path.join(output_root, "civic-scraper", city_slug)
    os.makedirs(folder, exist_ok=True)

    p(f"\n{'='*60}")
    p(f"  [civic-scraper] {city_name}  ({base_url})")
    p(f"{'='*60}")

    try:
        site   = CivicPlusSite(base_url)
        assets = site.scrape(start_date=START_DATE, end_date=END_DATE)
    except Exception as e:
        p(f"  [X] civic-scraper error: {e}")
        return hits, buf.getvalue()

    candidates = [
        a for a in assets
        if getattr(a, "asset_type", "") in ("minutes", "Minutes")
        or "minute" in str(getattr(a, "asset_name", "")).lower()
        or "minute" in str(getattr(a, "url", "")).lower()
    ]

    if not candidates:
        candidates = [a for a in assets if getattr(a, "asset_type", "") in ("agenda_packet", "agenda packet")]
    if not candidates:
        candidates = [a for a in assets if str(getattr(a, "url", "")).lower().endswith(".pdf")]

    p(f"  -> {len(assets)} total assets, {len(candidates)} candidate(s)")

    for asset in candidates:
        pdf_url    = getattr(asset, "url", None)
        asset_name = getattr(asset, "asset_name", "") or str(pdf_url).split("/")[-1]
        meet_date  = str(getattr(asset, "meeting_date", "") or "unknown_date")

        if not pdf_url:
            continue

        fname = safe_filename(f"{meet_date}_{asset_name}")
        if not fname.lower().endswith(".pdf"):
            fname += ".pdf"
        fpath = os.path.join(folder, fname)

        if os.path.exists(fpath):
            p(f"    [skip] {fname}")
            hits.append(Hit(city=city_name, platform=Platform.CIVIC_SCRAPER,
                            date=meet_date, doc_type="Minutes", label=asset_name,
                            url=pdf_url, file_path=fpath, confirmed=True,
                            matched_keywords=KEYWORDS[:1]))
            continue

        p(f"    v {meet_date} {asset_name[:50]} ...", end="", flush=False)

        pdf_bytes = download_pdf(pdf_url, session)
        if not pdf_bytes:
            p(f" SKIP (not a valid PDF)")
            continue

        matched = keyword_in_pdf(pdf_bytes, KEYWORDS)
        if matched:
            with open(fpath, "wb") as f:
                f.write(pdf_bytes)
            p(f" KEPT [{', '.join(matched)}] -> {fname}")
            hits.append(Hit(city=city_name, platform=Platform.CIVIC_SCRAPER,
                            date=meet_date, doc_type="Minutes", label=asset_name,
                            url=pdf_url, file_path=fpath, confirmed=True,
                            matched_keywords=matched))
        else:
            p(f" no keywords")

        time.sleep(0.5)

    return hits, buf.getvalue()


def search(cities: list[CityConfig], session: requests.Session, output_root: str) -> list[Hit]:
    _ensure_civic_scraper()
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
