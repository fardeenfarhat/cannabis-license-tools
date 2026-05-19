"""
NJ Municipality Portal Platform Detector
=========================================
Probes each municipality's base URL and detects which meeting-portal
platform they use, updating nj_portals.csv with:
  detected_platform  — agendacenter | civicplus | legistar | civicclerk |
                       civicweb | granicus | boarddocs | municode |
                       escribe | iqm2 | primegov | custom_pdf | unknown
  detected_evidence  — short string explaining what matched
  probe_status       — ok | timeout | error | skip

Probes the 259 'unknown' platform rows PLUS re-probes the 82 'not_found'
rows (they may have moved since the CSV was built).

Usage:
    c:/python312/python.exe -m scrapers.nj.detect_platform
    c:/python312/python.exe -m scrapers.nj.detect_platform --workers 30
    c:/python312/python.exe -m scrapers.nj.detect_platform --recheck-all
"""

import argparse
import csv
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests

# ── Paths ─────────────────────────────────────────────────────────────────────
_HERE   = os.path.dirname(__file__)
_NJ_DATA = os.path.join(_HERE, "..", "..", "nj_cannabis", "data")
CSV_IN  = os.path.join(_NJ_DATA, "nj_portals.csv")
CSV_OUT = os.path.join(_NJ_DATA, "nj_portals.csv")
LOG_OUT = os.path.join(_NJ_DATA, "detect_run.log")

# ── Detection fingerprints ─────────────────────────────────────────────────────
# Each entry: (platform_name, evidence_label, list_of_url_probes, html_patterns)
# html_patterns: list of regex that must match anywhere in page HTML/headers
# url_probes: additional paths to attempt (200 = strong signal)

FINGERPRINTS = [
    # ── AgendaCenter (CivicPlus product) ─────────────────────────────────────
    {
        "platform": "agendacenter",
        "url_probes": ["/AgendaCenter/", "/AgendaCenter/Search/?term=test"],
        "html_patterns": [r"AgendaCenter", r"civicplus\.com"],
        "header_patterns": [],
    },
    # ── CivicPlus CMS (not AgendaCenter) — some sites use CivicPlus but not AC
    {
        "platform": "civicplus",
        "url_probes": [],
        "html_patterns": [r"civicplus\.com/assets", r"CivicPlus", r"cp-gov\.com"],
        "header_patterns": [r"civicplus"],
    },
    # ── Legistar ─────────────────────────────────────────────────────────────
    {
        "platform": "legistar",
        "url_probes": [],
        "html_patterns": [r"legistar\.com", r"Legistar"],
        "header_patterns": [],
    },
    # ── CivicClerk ───────────────────────────────────────────────────────────
    {
        "platform": "civicclerk",
        "url_probes": [],
        "html_patterns": [r"civicclerk\.com", r"portal\.civicclerk"],
        "header_patterns": [],
    },
    # ── CivicWeb ─────────────────────────────────────────────────────────────
    {
        "platform": "civicweb",
        "url_probes": [],
        "html_patterns": [r"civicweb\.net", r"CivicWeb"],
        "header_patterns": [],
    },
    # ── Granicus / Peak Agenda / SilverCast ──────────────────────────────────
    {
        "platform": "granicus",
        "url_probes": [],
        "html_patterns": [r"granicus\.com", r"viewpublisher\.com", r"Granicus",
                          r"peakagenda\.com", r"novusagenda\.com"],
        "header_patterns": [],
    },
    # ── BoardDocs ─────────────────────────────────────────────────────────────
    {
        "platform": "boarddocs",
        "url_probes": [],
        "html_patterns": [r"boarddocs\.com", r"BoardDocs"],
        "header_patterns": [],
    },
    # ── Municode Meetings (formerly iLegislate) ───────────────────────────────
    {
        "platform": "municode",
        "url_probes": [],
        "html_patterns": [r"municode\.com", r"Municode", r"ilegislate\.com"],
        "header_patterns": [],
    },
    # ── eScribe ───────────────────────────────────────────────────────────────
    {
        "platform": "escribe",
        "url_probes": [],
        "html_patterns": [r"escribemeetings\.com"],   # "eScribe" alone false-positives on aria-describedby
        "header_patterns": [],
    },
    # ── IQM2 / InSite ─────────────────────────────────────────────────────────
    {
        "platform": "iqm2",
        "url_probes": [],
        "html_patterns": [r"iqm2\.com", r"api\.iqm2", r"IQM2"],
        "header_patterns": [],
    },
    # ── PrimeGov ──────────────────────────────────────────────────────────────
    {
        "platform": "primegov",
        "url_probes": [],
        "html_patterns": [r"primegov\.com", r"PrimeGov"],
        "header_patterns": [],
    },
    # ── Swagit / Cablecast video archives (video only, low value for docs) ───
    {
        "platform": "swagit",
        "url_probes": [],
        "html_patterns": [r"swagit\.com", r"Swagit"],
        "header_patterns": [],
    },
]

# Pages/paths to probe on each municipality base URL
EXTRA_PATHS = [
    "/",
    "/government/agendas-minutes",
    "/government/meetings",
    "/meetings",
    "/agendas",
    "/minutes",
    "/city-council/meetings",
    "/council/meetings",
    "/borough-council",
    "/township-committee",
    "/AgendaCenter/",
]


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    s.max_redirects = 5
    return s


def _fetch(session: requests.Session, url: str, timeout: int = 12) -> tuple[int, str, dict]:
    """Return (status_code, html_text, headers). Never raises."""
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
        return r.status_code, r.text[:80_000], dict(r.headers)
    except requests.exceptions.Timeout:
        return -1, "", {}
    except Exception as e:
        return -2, str(e)[:200], {}


def _detect(base_url: str, session: requests.Session) -> tuple[str, str, str]:
    """
    Returns (detected_platform, evidence, probe_status).
    Probes base URL + EXTRA_PATHS, matches against FINGERPRINTS.
    """
    base = base_url.rstrip("/")
    collected_html = ""
    collected_headers = {}
    probe_status = "error"
    any_ok = False

    # 1. Probe extra paths and collect HTML
    for path in EXTRA_PATHS:
        url = base + path
        code, html, hdrs = _fetch(session, url)
        if code > 0:
            any_ok = True
            probe_status = "ok"
            collected_html += html
            collected_headers.update(hdrs)
        elif code == -1:
            probe_status = "timeout"
        time.sleep(0.05)

    # 2. Also probe fingerprint-specific paths
    for fp in FINGERPRINTS:
        for probe_path in fp.get("url_probes", []):
            url = base + probe_path
            code, html, hdrs = _fetch(session, url)
            if code == 200 and html:
                collected_html += html
                collected_headers.update(hdrs)
                any_ok = True
            time.sleep(0.05)

    if not any_ok and probe_status != "timeout":
        probe_status = "error"

    if not collected_html:
        return "unknown", "", probe_status

    combined = collected_html.lower()
    header_combined = " ".join(str(v) for v in collected_headers.values()).lower()

    # 3. Match fingerprints in order
    for fp in FINGERPRINTS:
        for pat in fp["html_patterns"]:
            if re.search(pat, combined, re.IGNORECASE):
                return fp["platform"], f"html:{pat}", probe_status
        for pat in fp["header_patterns"]:
            if re.search(pat, header_combined, re.IGNORECASE):
                return fp["platform"], f"header:{pat}", probe_status

    # 4. Check for PDF-heavy sites (bare gov sites with links to PDFs)
    pdf_count = len(re.findall(r'href=["\'][^"\']*\.pdf', combined, re.IGNORECASE))
    if pdf_count >= 3:
        return "custom_pdf", f"pdf_links:{pdf_count}", probe_status

    return "unknown", "", probe_status


def _probe_row(row: dict, session: requests.Session) -> dict:
    """Probe one row and return updated row dict."""
    base_url = row.get("base_url", "").strip()
    if not base_url:
        row["detected_platform"] = "skip"
        row["detected_evidence"] = "no_url"
        row["probe_status"] = "skip"
        return row

    platform, evidence, status = _detect(base_url, session)
    row["detected_platform"] = platform
    row["detected_evidence"] = evidence
    row["probe_status"] = status
    return row


_print_lock = threading.Lock()


def _log(msg: str, log_fh):
    with _print_lock:
        print(msg)
        log_fh.write(msg + "\n")
        log_fh.flush()


def main():
    parser = argparse.ArgumentParser(description="Detect NJ portal platforms")
    parser.add_argument("--workers",      type=int, default=20, help="Parallel workers (default 20)")
    parser.add_argument("--recheck-all",  action="store_true",  help="Re-probe even already-classified rows")
    args = parser.parse_args()

    # Load CSV
    with open(CSV_IN, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    fieldnames = list(rows[0].keys())
    for extra in ["detected_platform", "detected_evidence", "probe_status"]:
        if extra not in fieldnames:
            fieldnames.append(extra)

    # Decide which rows to probe
    to_probe = []
    skip_rows = []
    for row in rows:
        plat   = row.get("platform", "")
        status = row.get("status", "")
        url    = row.get("base_url", "").strip()

        # Always skip no-URL rows (user decision)
        if not url or status == "no_url":
            row.setdefault("detected_platform", "skip")
            row.setdefault("detected_evidence", "no_url")
            row.setdefault("probe_status", "skip")
            skip_rows.append(row)
            continue

        # Skip already-known platforms unless --recheck-all
        if not args.recheck_all and plat in ("agendacenter", "civicplus", "legistar",
                                              "civicclerk", "civicweb"):
            row.setdefault("detected_platform", plat)
            row.setdefault("detected_evidence", "already_known")
            row.setdefault("probe_status", "skip")
            skip_rows.append(row)
            continue

        to_probe.append(row)

    print(f"\n[detect] {len(to_probe)} rows to probe  |  {len(skip_rows)} skipped")
    print(f"[detect] Workers: {args.workers}  |  Output: {CSV_OUT}\n")

    results: dict[int, dict] = {}  # index -> updated row
    done_count = 0

    with open(LOG_OUT, "w", encoding="utf-8") as log_fh:
        _log(f"=== NJ Portal Platform Detection  ({len(to_probe)} targets) ===\n", log_fh)

        def _worker(item: tuple[int, dict]) -> tuple[int, dict]:
            idx, row = item
            session = _make_session()
            updated = _probe_row(row, session)
            return idx, updated

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(_worker, (i, row)): i
                for i, row in enumerate(to_probe)
            }
            for fut in as_completed(futures):
                orig_idx = futures[fut]
                try:
                    idx, updated = fut.result()
                    results[idx] = updated
                    done_count += 1
                    name = updated.get("municipality", "?")
                    plat = updated.get("detected_platform", "?")
                    ev   = updated.get("detected_evidence", "")
                    ps   = updated.get("probe_status", "?")
                    msg  = f"  [{done_count:>3}/{len(to_probe)}]  {name:<30s}  {plat:<14s}  {ps}  {ev}"
                    _log(msg, log_fh)
                except Exception as exc:
                    row = to_probe[orig_idx]
                    name = row.get("municipality", "?")
                    _log(f"  [ERR]  {name}: {exc}", log_fh)
                    row["detected_platform"] = "error"
                    row["detected_evidence"] = str(exc)[:100]
                    row["probe_status"] = "error"
                    results[orig_idx] = row

        # ── Write updated CSV ────────────────────────────────────────────────
        ordered_results = [results[i] for i in range(len(to_probe))]
        all_rows = skip_rows + ordered_results

        # Re-sort by original order (skip_rows first ruins order) — rebuild by name
        # Simpler: keep original row objects mutated in-place
        with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)  # rows objects were mutated in-place

        _log(f"\n[detect] CSV written: {CSV_OUT}", log_fh)

        # ── Summary ──────────────────────────────────────────────────────────
        from collections import Counter
        plat_counts = Counter(r.get("detected_platform", "unknown") for r in to_probe)

        _log("\n" + "="*60, log_fh)
        _log("  PLATFORM DETECTION SUMMARY", log_fh)
        _log("="*60, log_fh)
        for plat, count in sorted(plat_counts.items(), key=lambda x: -x[1]):
            _log(f"  {plat:<20s}  {count}", log_fh)
        _log(f"\n  Total probed: {len(to_probe)}", log_fh)
        _log(f"  Log:          {LOG_OUT}", log_fh)
        _log("="*60 + "\n", log_fh)

    # Also print summary to stdout
    print("\n" + "="*60)
    print("  PLATFORM DETECTION SUMMARY")
    print("="*60)
    plat_counts = Counter(r.get("detected_platform", "unknown") for r in to_probe)
    for plat, count in sorted(plat_counts.items(), key=lambda x: -x[1]):
        print(f"  {plat:<20s}  {count}")
    print(f"\n  Log: {LOG_OUT}")
    print("="*60)


if __name__ == "__main__":
    main()
