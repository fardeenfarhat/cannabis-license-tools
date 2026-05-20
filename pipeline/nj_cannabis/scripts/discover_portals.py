"""
For each NJ municipality in the "not_yet_awarded" bucket, discover which
meeting-minutes platform they use by probing their official website.

URL source: nj_cannabis/data/nj_gov_urls.csv  (scraped from nj.gov directory)

Platform probes (checked in order):
  agendacenter  /AgendaCenter/
  legistar      /legistar
  civicweb      /civicweb
  civicplus     /CivicAlerts.aspx

Output: nj_cannabis/data/nj_portals.csv
"""

import csv
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

STATUS_FILE  = Path(__file__).parent.parent / "output" / "nj_cannabis_status.csv"
URLS_FILE    = Path(__file__).parent.parent / "data"   / "nj_gov_urls.csv"
OUTPUT_FILE  = Path(__file__).parent.parent / "data"   / "nj_portals.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 12
WORKERS = 20

PLATFORM_PROBES = [
    ("agendacenter", "/AgendaCenter/"),
    ("legistar",     "/legistar"),
    ("civicweb",     "/civicweb"),
    ("civicplus",    "/CivicAlerts.aspx"),
]


def normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.lower().strip())


def detect_platform(base_url: str, session: requests.Session) -> str | None:
    for platform, path in PLATFORM_PROBES:
        try:
            r = session.get(base_url.rstrip("/") + path, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code < 400 and len(r.text) > 200:
                return platform
        except Exception:
            continue
    return None


def probe_one(row: dict, url_lookup: dict[str, str]) -> dict:
    name  = row["municipality"]
    key   = normalize(name)
    base  = url_lookup.get(key, "")

    result = {
        "municipality": name,
        "type":         row["type"],
        "county":       row["county"],
        "base_url":     base,
        "platform":     "",
        "status":       "no_url" if not base else "found",
    }

    if not base:
        return result

    session = requests.Session()
    session.headers.update(HEADERS)

    platform = detect_platform(base, session)
    result["platform"] = platform or "unknown"

    # If base URL is completely unreachable, mark as not_found
    try:
        r = session.get(base, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code >= 400:
            result["status"] = "not_found"
    except Exception:
        result["status"] = "not_found"

    return result


def load_targets(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["status"] == "not_yet_awarded"]


def load_url_lookup(path: Path) -> dict[str, str]:
    lookup = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = normalize(row["municipality"])
            # Don't overwrite — keep first match (more specific entries first)
            if key not in lookup:
                lookup[key] = row["url"].rstrip("/")
    return lookup


def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    targets    = load_targets(STATUS_FILE)
    url_lookup = load_url_lookup(URLS_FILE)

    matched = sum(1 for t in targets if normalize(t["municipality"]) in url_lookup)
    print(f"Targets: {len(targets)}  |  URL matches from directory: {matched}")
    print("Probing platforms ...")

    results = []
    found = 0
    with_platform = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(probe_one, t, url_lookup): t for t in targets}
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            results.append(r)
            if r["status"] == "found":
                found += 1
                if r["platform"] not in ("", "unknown"):
                    with_platform += 1
            if i % 50 == 0:
                print(f"  {i}/{len(targets)} — {found} live, {with_platform} with platform")

    results.sort(key=lambda x: x["municipality"])

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "municipality", "type", "county", "base_url", "platform", "status"
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"\nResults:")
    print(f"  Live websites      : {found}/{len(targets)}")
    print(f"  Known platform     : {with_platform}")
    print(f"  No URL in directory: {len(targets) - matched}")
    print(f"  Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
