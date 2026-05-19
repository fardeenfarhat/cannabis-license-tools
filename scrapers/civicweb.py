"""Agent 2 — CivicWeb scraper (Playwright + Webshare proxy).

CivicWeb portals block non-US IPs. Webshare rotating proxy (p.webshare.io:9999)
provides US exit IPs via IP authentication (no credentials needed if this
machine's IP is whitelisted in the Webshare dashboard).

Document download URL: /document/{id}/download  (returns PDF directly)
Search results are JS-rendered, so Playwright is required.

Date filtering: VirtualLibrary has no date form fields, so dates are extracted
from rendered result rows via JS and compared to START_DATE / END_DATE.
Documents whose date cannot be determined are always included (conservative).
"""

import os
import re
import time
from datetime import datetime

import requests

from .config import CityConfig, KEYWORDS, START_DATE, END_DATE
from .types import Hit, Platform
from .utils import safe_filename, keyword_in_pdf, download_pdf

_DT_START = datetime.strptime(START_DATE, "%Y-%m-%d")
_DT_END   = datetime.strptime(END_DATE,   "%Y-%m-%d")


def _parse_doc_date(date_str: str) -> datetime | None:
    """Parse a date string in common CivicWeb display formats."""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y",
                "%B %d %Y",  "%b %d %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _in_date_range(doc: dict) -> bool:
    """Return True if doc date is within [START_DATE, END_DATE], or unknown."""
    raw = doc.get("date", "")
    if not raw:
        return True  # unknown date — include conservatively
    dt = _parse_doc_date(raw)
    if dt is None:
        return True
    return _DT_START <= dt <= _DT_END

PROXY = "http://p.webshare.io:9999"
USE_PROXY = False  # Toggle True only if CivicWeb blocks your IP (non-US connection)


def _extract_doc_links(page) -> list[dict]:
    """Pull all /document/{id} and /filepro/documents/{id} links from current page.

    Also tries to read a date from the nearest table row / list item so we can
    filter by date range before downloading PDFs.
    """
    return page.evaluate("""
        () => {
            const seen = new Set();
            const results = [];
            // Date patterns: MM/DD/YYYY  |  YYYY-MM-DD  |  Month DD, YYYY  |  Month DD YYYY
            const DATE_RE = /\\b(\\d{1,2}\\/\\d{1,2}\\/\\d{4}|\\d{4}-\\d{2}-\\d{2}|[A-Za-z]+ \\d{1,2},?\\s+\\d{4})\\b/;
            document.querySelectorAll('a[href]').forEach(a => {
                const m = a.href.match(/\\/document\\/(\\d+)/) ||
                          a.href.match(/\\/filepro\\/documents\\/(\\d+)/);
                if (m && !seen.has(m[1])) {
                    seen.add(m[1]);
                    // Walk up the DOM to find the nearest row-like container
                    let date = '';
                    let el = a;
                    for (let i = 0; i < 6; i++) {
                        el = el.parentElement;
                        if (!el) break;
                        const tag = el.tagName;
                        if (tag === 'TR' || tag === 'LI' ||
                            (el.className && /result|item|row/i.test(el.className))) {
                            const dm = el.innerText.match(DATE_RE);
                            if (dm) { date = dm[1]; break; }
                        }
                    }
                    results.push({
                        id:    m[1],
                        title: a.innerText.trim() || a.href,
                        href:  a.href,
                        date:  date,
                    });
                }
            });
            return results;
        }
    """)


def _search_civicweb(page, base_url: str, keyword: str) -> list[dict]:
    """Search CivicWeb VirtualLibrary and return list of {id, title, href} dicts."""
    from playwright.sync_api import TimeoutError as PWTimeout

    lib_url = f"{base_url}/Portal/VirtualLibrary.aspx"
    print(f"  -> Loading VirtualLibrary ...")
    try:
        # "load" fires once the DOM + resources are ready; avoids hanging on
        # persistent analytics/long-poll requests that block "networkidle"
        page.goto(lib_url, timeout=45000, wait_until="load")
        page.wait_for_timeout(1000)
    except PWTimeout:
        print(f"  [X] Timeout loading {lib_url}")
        return []

    # Scroll to and fill the Key Words search box, set sort order, then submit
    try:
        page.locator("#ctl00_MainContent_SearchTextBox").scroll_into_view_if_needed()
        page.fill("#ctl00_MainContent_SearchTextBox", keyword)
        # Sort by Date Created, descending (newest first)
        page.select_option("#ctl00_MainContent_OrderByDropDown", label="Date Created")
        page.select_option("#ctl00_MainContent_OrderTypeDropDown", label="Z to A - Descending")
        page.click("#SearchButton")
        page.wait_for_timeout(3000)
    except Exception as e:
        print(f"  [X] Search form error: {e}")
        return []

    # Collect results across all pages
    all_results: list[dict] = []
    page_num = 1
    while True:
        links = _extract_doc_links(page)
        all_results.extend(links)
        print(f"  -> Page {page_num}: {len(links)} link(s)")

        # Check for a "Next" pagination link
        try:
            next_btn = page.locator("a:has-text('Next'), a:has-text('>'), a.next-page").first
            if next_btn.is_visible(timeout=1000):
                next_btn.click()
                page.wait_for_timeout(2000)
                page_num += 1
            else:
                break
        except Exception:
            break

    # Deduplicate by id
    seen: set[str] = set()
    unique = []
    for r in all_results:
        if r["id"] not in seen:
            seen.add(r["id"])
            unique.append(r)

    # Apply date-range filter (documents with unknown dates pass through)
    in_range = [r for r in unique if _in_date_range(r)]
    skipped  = len(unique) - len(in_range)
    if skipped:
        print(f"  -> {skipped} doc(s) outside date range "
              f"({START_DATE} – {END_DATE}) skipped")
    return in_range


def search(cities: list[CityConfig], session: requests.Session, output_root: str,
           headless: bool = True) -> list[Hit]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "-q"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        from playwright.sync_api import sync_playwright

    # Proxy session for PDF downloads (only if USE_PROXY enabled)
    proxy_session = requests.Session()
    proxy_session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    if USE_PROXY:
        proxy_session.proxies = {"http": PROXY, "https": PROXY}

    hits: list[Hit] = []

    launch_kwargs: dict = {"headless": headless}
    if USE_PROXY:
        launch_kwargs["proxy"] = {"server": PROXY}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(**launch_kwargs)
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()

            for city in cities:
                base_url  = city.url.rstrip("/")
                city_name = city.name
                city_slug = city.slug
                folder    = os.path.join(output_root, "civicweb", city_slug)
                os.makedirs(folder, exist_ok=True)

                print(f"\n{'='*60}")
                print(f"  [CivicWeb] {city_name}  ({base_url})")
                print(f"{'='*60}")

                doc_results = _search_civicweb(page, base_url, "cannabis")
                print(f"  -> {len(doc_results)} document link(s) in search results")

                for doc in doc_results:
                    doc_id  = doc["id"]
                    title   = doc["title"][:60]
                    dl_url  = f"{base_url}/document/{doc_id}/download"

                    fname = safe_filename(f"doc{doc_id}_{title}") + ".pdf"
                    fpath = os.path.join(folder, fname)

                    if os.path.exists(fpath):
                        print(f"    [skip] {fname}")
                        continue

                    print(f"    Downloading doc {doc_id}: {title[:50]} ...", end="", flush=True)
                    pdf_bytes = download_pdf(dl_url, proxy_session)
                    if not pdf_bytes:
                        print(f" SKIP (not a valid PDF)")
                        continue

                    matched = keyword_in_pdf(pdf_bytes, KEYWORDS)
                    confirmed = bool(matched)
                    print(f" {len(pdf_bytes)//1024}KB  confirmed={confirmed}  {matched}")

                    with open(fpath, "wb") as f:
                        f.write(pdf_bytes)
                    print(f"    SAVED: {fname}")

                    hits.append(Hit(
                        city=city_name, platform=Platform.CIVICWEB,
                        date="unknown", doc_type="Document", label=title,
                        url=dl_url, file_path=fpath, confirmed=confirmed,
                        matched_keywords=matched,
                    ))
                    time.sleep(0.5)
        finally:
            browser.close()

    return hits
