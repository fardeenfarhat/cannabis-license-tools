"""
Build the seed URL list for the RFP monitor.

For every Class-5-allowed municipality we:
  1. Look up the official website from nj_gov_urls.csv
  2. Append the most common RFP/Bid/Legal-Notice path suffixes
  3. Also add any hand-curated known URLs

Output: nj_rfp_monitor/data/rfp_seed_urls.csv
  columns: municipality, county, base_url, monitor_url, url_type, notes
"""

import csv
from pathlib import Path

ROOT     = Path(__file__).parent.parent
OPT_IN   = ROOT / "data" / "nj_opted_in_municipalities.csv"
GOV_URLS = ROOT / "data" / "nj_gov_urls.csv"
OUTPUT   = ROOT / "data" / "rfp_seed_urls.csv"

# Suffixes to try for each town website.  Order matters — more specific first.
SUFFIXES = [
    ("/rfp",                    "rfp_page"),
    ("/rfps",                   "rfp_page"),
    ("/bids",                   "bids_page"),
    ("/bids-rfps",              "bids_rfp_page"),
    ("/bids-and-rfps",          "bids_rfp_page"),
    ("/purchasing",             "purchasing"),
    ("/government/purchasing",  "purchasing"),
    ("/business/bids",          "bids_page"),
    ("/legal-notices",          "legal_notices"),
    ("/cannabis",               "cannabis_page"),
    ("/cannabis-licensing",     "cannabis_page"),
    ("",                        "home"),          # fallback — scrape homepage
]

# Hand-curated overrides / extras (highest-priority towns)
# (municipality, url_type, monitor_url, notes)
KNOWN_URLS = [
    ("Vineland",          "bids_page",    "https://bidinfo.vinelandcity.org/",                          "Vineland bid portal — confirmed working"),
    ("Morristown",        "bids_page",    "https://www.townofmorristown.org/bids",                      "confirmed cannabis RFP Dec 2024"),
    ("East Windsor",      "rfp_page",     "https://www.east-windsor.nj.us/bids",                        "confirmed Class 5 RFP issued"),
    ("Jersey City",       "rfp_page",     "https://www.jerseycitynj.gov/business/bids-rfps",            "3 licenses advancing Jan 2026"),
    ("Newark",            "rfp_page",     "https://www.newarknj.gov/departments/purchasing/bids",       "large market"),
    ("Paterson",          "rfp_page",     "https://www.patersonnjusa.com/index.php/purchasing",         "large market"),
    ("Trenton",           "bids_page",    "https://www.trentonnj.org/161/Bids-RFPs",                    "state capital"),
    ("Camden City",       "rfp_page",     "https://www.ci.camden.nj.us/bids",                          "large market"),
    ("Ewing Township",    "rfp_page",     "https://www.ewingnj.org/business/bids-rfps",                 "moratorium thru Dec 2026"),
    ("Atlantic City",     "bids_page",    "https://www.acnj.gov/index.aspx?NID=252",                    "Atlantic City bids page"),
    ("Edison",            "rfp_page",     "https://www.edisonnj.org/government/purchasing/bids.asp",    "large suburb"),
    ("Fort Lee",          "rfp_page",     "https://www.fortleenj.org/bids",                             "Bergen County"),
    ("Lodi",              "rfp_page",     "https://www.lodi.gov/bids",                                  "retail only"),
    ("Cliffside Park",    "rfp_page",     "https://www.cliffsideparknj.gov/bids",                       "retail only"),
    ("Secaucus",          "rfp_page",     "https://www.secaucus.net/bids",                              "Hudson County"),
    ("Bayonne",           "rfp_page",     "https://bayonnenj.org/bids",                                 "Hudson County"),
    ("Red Bank",          "rfp_page",     "https://www.redbanknj.org/bids",                             "Monmouth County"),
]


def load_gov_urls() -> dict[str, str]:
    """municipality (lower) -> base URL"""
    out = {}
    with open(GOV_URLS, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["municipality"].strip().lower()] = row["url"].strip().rstrip("/")
    return out


def load_opt_in() -> list[dict]:
    with open(OPT_IN, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["allows_retail_class5"].strip().lower() == "yes"]


def build_rows() -> list[dict]:
    gov   = load_gov_urls()
    towns = load_opt_in()

    known_index: dict[str, list[tuple]] = {}
    for muni, url_type, url, notes in KNOWN_URLS:
        known_index.setdefault(muni.lower(), []).append((url_type, url, notes))

    rows = []
    seen_urls: set[str] = set()

    def add(muni, county, base, monitor_url, url_type, notes):
        key = monitor_url.lower().rstrip("/")
        if key in seen_urls:
            return
        seen_urls.add(key)
        rows.append({
            "municipality": muni,
            "county":       county,
            "base_url":     base,
            "monitor_url":  monitor_url,
            "url_type":     url_type,
            "notes":        notes,
        })

    for town in towns:
        muni    = town["municipality"].strip()
        county  = town["county"].strip()
        muni_lc = muni.lower()
        base    = gov.get(muni_lc, "")

        for url_type, url, notes in known_index.get(muni_lc, []):
            add(muni, county, base, url, url_type, notes)

        if base:
            for suffix, url_type in SUFFIXES:
                add(muni, county, base, base + suffix, url_type, "auto-generated")

    return rows


def main():
    rows = build_rows()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["municipality","county","base_url","monitor_url","url_type","notes"])
        writer.writeheader()
        writer.writerows(rows)

    towns = {r["municipality"] for r in rows}
    print(f"Towns covered : {len(towns)}")
    print(f"Total URLs    : {len(rows)}")
    by_type = {}
    for r in rows:
        by_type[r["url_type"]] = by_type.get(r["url_type"], 0) + 1
    for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t:<25}: {c}")
    print(f"\nSaved to {OUTPUT}")


if __name__ == "__main__":
    main()
