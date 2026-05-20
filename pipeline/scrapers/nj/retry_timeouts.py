"""
Retry probe for rows that timed out or errored in the first sweep.
Uses lower concurrency and longer timeouts.
"""
import csv, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

_HERE   = os.path.dirname(__file__)
CSV_PATH = os.path.join(_HERE, "..", "..", "nj_cannabis", "data", "nj_portals.csv")

FINGERPRINTS = [
    {"platform": "agendacenter", "html_patterns": [r"AgendaCenter", r"civicplus\.com"]},
    {"platform": "civicplus",    "html_patterns": [r"civicplus\.com/assets", r"CivicPlus", r"cp-gov\.com"]},
    {"platform": "legistar",     "html_patterns": [r"legistar\.com"]},
    {"platform": "civicclerk",   "html_patterns": [r"civicclerk\.com"]},
    {"platform": "civicweb",     "html_patterns": [r"civicweb\.net"]},
    {"platform": "granicus",     "html_patterns": [r"granicus\.com", r"viewpublisher\.com", r"novusagenda\.com"]},
    {"platform": "boarddocs",    "html_patterns": [r"boarddocs\.com"]},
    {"platform": "municode",     "html_patterns": [r"municode\.com"]},
    {"platform": "escribe",      "html_patterns": [r"escribemeetings\.com"]},
    {"platform": "iqm2",         "html_patterns": [r"iqm2\.com"]},
    {"platform": "primegov",     "html_patterns": [r"primegov\.com"]},
]

EXTRA_PATHS = ["/", "/AgendaCenter/", "/government/meetings", "/meetings", "/agendas"]

def _make_session():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    return s

def _detect(base_url, session):
    base = base_url.rstrip("/")
    combined = ""
    any_ok = False
    for path in EXTRA_PATHS:
        try:
            r = session.get(base + path, timeout=20, allow_redirects=True)
            if r.status_code > 0:
                combined += r.text[:40_000]
                any_ok = True
        except requests.exceptions.Timeout:
            pass
        except Exception:
            pass
        time.sleep(0.1)
    if not combined:
        return "unknown", "", "timeout" if not any_ok else "error"
    for fp in FINGERPRINTS:
        for pat in fp["html_patterns"]:
            if re.search(pat, combined, re.IGNORECASE):
                return fp["platform"], f"html:{pat}", "ok"
    pdf_count = len(re.findall(r'href=["\'][^"\']*\.pdf', combined, re.IGNORECASE))
    if pdf_count >= 3:
        return "custom_pdf", f"pdf_links:{pdf_count}", "ok"
    return "unknown", "", "ok"

_lock = threading.Lock()

def main():
    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8")))
    fieldnames = list(rows[0].keys())

    to_retry = [(i, r) for i, r in enumerate(rows)
                if r.get("probe_status") in ("timeout", "error")
                and r.get("base_url", "").strip()]

    print(f"[retry] {len(to_retry)} rows to retry (timeout/error) — 8 workers, 20s timeout\n")
    done = 0

    def _worker(item):
        i, row = item
        session = _make_session()
        plat, ev, status = _detect(row["base_url"], session)
        return i, plat, ev, status

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_worker, item): item for item in to_retry}
        for fut in as_completed(futs):
            i, row = futs[fut]
            try:
                idx, plat, ev, status = fut.result()
                rows[idx]["detected_platform"] = plat
                rows[idx]["detected_evidence"]  = ev
                rows[idx]["probe_status"]        = status
                done += 1
                with _lock:
                    name = rows[idx]["municipality"]
                    print(f"  [{done:>3}/{len(to_retry)}]  {name:<30s}  {plat:<14s}  {status}  {ev}")
            except Exception as e:
                with _lock:
                    print(f"  [ERR] {row['municipality']}: {e}")

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore").writeheader()
        csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore").writerows(rows)

    from collections import Counter
    newly_found = [rows[i] for i, _ in to_retry]
    counts = Counter(r["detected_platform"] for r in newly_found)
    print("\n=== RETRY RESULTS ===")
    for p, c in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {p:<20s}  {c}")
    print(f"\nCSV updated: {CSV_PATH}")

if __name__ == "__main__":
    main()
