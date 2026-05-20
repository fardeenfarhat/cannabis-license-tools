"""
Deep sweep for the 166 NJ towns where platform is still 'unknown'.

Differences from detect_platform.py:
  - 35+ URL paths probed per town (vs 11)
  - Follows one level of internal links that look like meeting pages
  - Broader fingerprint set (adds OpenGov, Granicus, NovusAgenda, BoardDocs, etc.)
  - Lowers custom_pdf PDF threshold to 2
  - Writes results back to nj_portals.csv in-place

Usage:
    c:/python312/python.exe -m scrapers.nj.deep_sweep
    c:/python312/python.exe -m scrapers.nj.deep_sweep --workers 20
"""

import argparse
import csv
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests

_HERE    = os.path.dirname(__file__)
_NJ_DATA = os.path.join(_HERE, "..", "..", "nj_cannabis", "data")
CSV_PATH = os.path.join(_NJ_DATA, "nj_portals.csv")
LOG_PATH = os.path.join(_NJ_DATA, "deep_sweep.log")

# ── Extended path list ────────────────────────────────────────────────────────
PROBE_PATHS = [
    "/",
    "/agendas",
    "/agendas-minutes",
    "/agendasminutes",
    "/minutes",
    "/meeting-minutes",
    "/meetings",
    "/public-meetings",
    "/government/agendas-minutes",
    "/government/meetings",
    "/government/agendas",
    "/government/council",
    "/government/board",
    "/government/committee",
    "/our-government/agendas-minutes",
    "/our-government/council",
    "/our-government/meetings",
    "/council/meetings",
    "/council/agendas",
    "/council-meetings",
    "/council-agenda",
    "/council-agendas",
    "/council-meeting-agendas",
    "/borough-council",
    "/township-committee",
    "/city-council",
    "/board-of-commissioners",
    "/commissioners",
    "/clerk",
    "/town-clerk",
    "/municipal-clerk",
    "/records",
    "/public-records",
    "/AgendaCenter/",
    "/AgendaCenter/Search/?term=cannabis",
    "/cn/Meetings/",
    "/cn/meetings/",
]

# ── Platform fingerprints ─────────────────────────────────────────────────────
FINGERPRINTS = [
    {
        "platform": "agendacenter",
        "html": [r"AgendaCenter", r"/AgendaCenter/", r"civicplus\.com"],
        "url_probes": ["/AgendaCenter/", "/AgendaCenter/Search/?term=test"],
    },
    {
        "platform": "civicplus",
        "html": [r"civicplus\.com/assets", r"CivicPlus", r"cp-gov\.com", r"civicengage"],
        "url_probes": [],
    },
    {
        "platform": "legistar",
        "html": [r"legistar\.com", r"Legistar"],
        "url_probes": [],
    },
    {
        "platform": "civicclerk",
        "html": [r"civicclerk\.com", r"portal\.civicclerk"],
        "url_probes": [],
    },
    {
        "platform": "civicweb",
        "html": [r"civicweb\.net", r"CivicWeb"],
        "url_probes": [],
    },
    {
        "platform": "granicus",
        "html": [r"granicus\.com", r"viewpublisher\.com", r"peakagenda\.com",
                 r"novusagenda\.com", r"NovusAgenda", r"Granicus"],
        "url_probes": [],
    },
    {
        "platform": "boarddocs",
        "html": [r"boarddocs\.com", r"BoardDocs"],
        "url_probes": [],
    },
    {
        "platform": "municode",
        "html": [r"ilegislate\.com"],          # municode.com alone = code-of-ordinances false positive
        "url_probes": [],
    },
    {
        "platform": "escribe",
        "html": [r"escribemeetings\.com"],
        "url_probes": [],
    },
    {
        "platform": "iqm2",
        "html": [r"iqm2\.com", r"IQM2"],
        "url_probes": [],
    },
    {
        "platform": "primegov",
        "html": [r"primegov\.com", r"PrimeGov"],
        "url_probes": [],
    },
    {
        "platform": "opengov",
        "html": [r"opengov\.com", r"OpenGov"],
        "url_probes": [],
    },
    {
        "platform": "laserfiche",
        "html": [r"laserfiche\.com", r"Laserfiche"],
        "url_probes": [],
    },
    {
        "platform": "onbase",
        "html": [r"onbase\.com", r"OnBase"],
        "url_probes": [],
    },
]

MEETING_KEYWORDS = {"agenda", "minute", "meeting", "council", "committee",
                    "board", "commissioner", "clerk", "calendar"}

_print_lock = threading.Lock()


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def _fetch(session, url, timeout=15):
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
        return r.status_code, r.text[:80_000]
    except requests.exceptions.Timeout:
        return -1, ""
    except Exception:
        return -2, ""


def _same_domain(url, base):
    return urlparse(url).netloc == urlparse(base).netloc


def _internal_meeting_links(html, page_url, base):
    """Return internal links that look like meeting/agenda pages."""
    links = []
    for m in re.finditer(r'href=["\']([^"\'#?]+)["\']', html, re.I):
        href = m.group(1)
        full = urljoin(page_url, href)
        if not _same_domain(full, base):
            continue
        if full.lower().endswith(('.pdf', '.doc', '.docx', '.jpg', '.png', '.css', '.js')):
            continue
        if any(k in full.lower() for k in MEETING_KEYWORDS):
            links.append(full)
    return list(dict.fromkeys(links))[:15]  # deduplicate, cap at 15


def _detect(base_url, session):
    """
    Returns (platform, evidence, probe_status).
    Probes PROBE_PATHS + fingerprint-specific paths + follows 1 level of
    internal meeting links.
    """
    base = base_url.rstrip("/")
    html_corpus = ""
    any_ok = False
    probe_status = "error"
    visited = set()

    def _collect(url):
        nonlocal html_corpus, any_ok, probe_status
        if url in visited:
            return
        visited.add(url)
        code, html = _fetch(session, url)
        if code > 0:
            any_ok = True
            probe_status = "ok"
            html_corpus += html

    # 1. Probe all standard paths
    for path in PROBE_PATHS:
        _collect(base + path)
        time.sleep(0.04)

    # 2. Probe fingerprint-specific paths
    for fp in FINGERPRINTS:
        for path in fp.get("url_probes", []):
            _collect(base + path)
            time.sleep(0.04)

    # 3. Follow internal meeting links found on homepage (1 level deep)
    if any_ok and html_corpus:
        meeting_links = _internal_meeting_links(html_corpus, base + "/", base)
        for link in meeting_links[:8]:
            _collect(link)
            time.sleep(0.05)

    if not any_ok:
        return "unknown", "", "timeout" if probe_status == "error" else probe_status

    combined = html_corpus.lower()

    # 4. Match fingerprints
    for fp in FINGERPRINTS:
        for pat in fp["html"]:
            if re.search(pat, combined, re.IGNORECASE):
                return fp["platform"], f"html:{pat}", probe_status

    # 5. PDF count — lower threshold (2)
    pdf_count = len(re.findall(r'href=["\'][^"\']*\.pdf', combined, re.IGNORECASE))
    if pdf_count >= 2:
        return "custom_pdf", f"pdf_links:{pdf_count}", probe_status

    return "unknown", "", probe_status


def main():
    parser = argparse.ArgumentParser(description="Deep sweep of unknown NJ towns")
    parser.add_argument("--workers", type=int, default=15)
    args = parser.parse_args()

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())

    # Only re-probe rows that are still 'unknown'
    to_probe = [r for r in rows
                if r.get("detected_platform", "").strip() in ("unknown", "")
                and r.get("base_url", "").strip()
                and r.get("probe_status", "") not in ("skip",)]

    print(f"\n[deep_sweep] {len(to_probe)} unknown towns to probe")
    print(f"[deep_sweep] Workers: {args.workers}\n")

    done = 0

    def _worker(row):
        s = _session()
        plat, ev, status = _detect(row["base_url"].strip(), s)
        row["detected_platform"] = plat
        row["detected_evidence"]  = ev
        row["probe_status"]       = status
        return row

    with open(LOG_PATH, "w", encoding="utf-8") as log:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_worker, r): r for r in to_probe}
            for fut in as_completed(futures):
                row = futures[fut]
                done += 1
                try:
                    updated = fut.result()
                    plat = updated["detected_platform"]
                    ev   = updated.get("detected_evidence", "")
                    ps   = updated.get("probe_status", "")
                    msg  = (f"  [{done:>3}/{len(to_probe)}]  "
                            f"{updated['municipality']:<28}  {plat:<14}  {ps}  {ev}")
                except Exception as exc:
                    plat = "error"
                    msg  = f"  [{done:>3}/{len(to_probe)}]  {row['municipality']}: {exc}"
                with _print_lock:
                    print(msg)
                    log.write(msg + "\n")
                    log.flush()

    # Write CSV back
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=fieldnames).writeheader()
        csv.DictWriter(f, fieldnames=fieldnames).writerows(rows)

    # Summary
    counts = Counter(r.get("detected_platform", "unknown") for r in to_probe)
    print(f"\n{'='*55}")
    print("  DEEP SWEEP RESULTS")
    print(f"{'='*55}")
    for p, c in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {p:<22}  {c}")
    print(f"\n  Total probed: {len(to_probe)}")
    print(f"  Log: {LOG_PATH}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
