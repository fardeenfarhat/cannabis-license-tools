"""
Cross-reference NJ municipalities with CRC licensed towns to produce
a master status CSV with three buckets:
  - awarded: town appears in CRC license data
  - not_yet_awarded: no licenses issued yet

Matching strategy (applied in order):
  1. Exact match (case-insensitive)
  2. Suffix-stripped match — remove Borough/Township/City/Town/Village from either side
  3. Punctuation-normalised match — strip apostrophes, hyphens
  4. Known unincorporated community → parent municipality map

Output: nj_cannabis/output/nj_cannabis_status.csv

Run after:
  1. parse_municipalities.py
  2. scrape_crc_licenses.py
"""

import csv
import re
from pathlib import Path

MUNICIPALITIES_FILE = Path(__file__).parent.parent / "data" / "nj_municipalities.csv"
LICENSED_TOWNS_FILE = Path(__file__).parent.parent / "data" / "crc_licensed_towns.csv"
OUTPUT_FILE = Path(__file__).parent.parent / "output" / "nj_cannabis_status.csv"

SUFFIXES = re.compile(
    r"\b(borough|township|city|town|village|municipality)\b", re.IGNORECASE
)

# Unincorporated communities and alternate names → official NJ municipality name
COMMUNITY_MAP = {
    "atco":               "Waterford",
    "avenel":             "Woodbridge",
    "bass river township":"Bass River",
    "blackwood":          "Gloucester",
    "browns mills":       "Pemberton",
    "budd lake":          "Mount Olive",
    "cape maycourt house":   "Middle",   # CRC typo; Cape May Court House is unincorporated community in Middle Township
    "cape may court house":  "Middle",
    "carney's point":     "Carneys Point",
    "franklin borough":   "Franklin",
    "franklin park":      "Franklin",
    "franklin township":  "Franklin",
    "gloucester township":"Gloucester",
    "hewitt":             "West Milford",
    "kingston":           "South Brunswick",
    "lake hopatcong":     "Hopatcong",
    "marlton":            "Evesham",
    "mays landing":       "Hamilton",
    "newfoundland":       "West Milford",
    "oak ridge":          "Jefferson",
    "pequannock township":"Pequannock",
    "rockaway borough":   "Rockaway",
    "sicklerville":       "Winslow",
    "somerset":           "Franklin",
    "south orange":       "South Orange Village",
    "south tom's river":  "South Toms River",
    "turnersville":       "Washington",
    "waretown":           "Ocean",
    "williamstown":       "Monroe",
    "winslow township":   "Winslow",
    "augusta":            "Frankford",
}


def clean(name: str) -> str:
    return name.lower().strip()


def strip_suffix(name: str) -> str:
    return SUFFIXES.sub("", name).strip()


def strip_punct(name: str) -> str:
    return re.sub(r"['\-]", "", name).strip()


def build_lookup(municipalities: list[dict]) -> dict[str, dict]:
    """Build multiple index keys per municipality for flexible matching."""
    lookup: dict[str, dict] = {}
    for m in municipalities:
        base = clean(m["municipality"])
        stripped = strip_suffix(base).strip()
        no_punct = strip_punct(base)
        stripped_no_punct = strip_punct(stripped)

        for key in {base, stripped, no_punct, stripped_no_punct}:
            if key:
                lookup.setdefault(key, m)
    return lookup


def match(crc_town: str, lookup: dict[str, dict]) -> dict | None:
    raw = clean(crc_town)

    # 1. Exact
    if raw in lookup:
        return lookup[raw]

    # 2. Strip suffixes from CRC name
    stripped = strip_suffix(raw).strip()
    if stripped in lookup:
        return lookup[stripped]

    # 3. Strip punctuation
    no_punct = strip_punct(raw)
    if no_punct in lookup:
        return lookup[no_punct]

    stripped_no_punct = strip_punct(stripped)
    if stripped_no_punct in lookup:
        return lookup[stripped_no_punct]

    # 4. Community map
    if raw in COMMUNITY_MAP:
        parent = clean(COMMUNITY_MAP[raw])
        return lookup.get(parent)

    return None


def load_municipalities(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_licensed(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    municipalities = load_municipalities(MUNICIPALITIES_FILE)
    licensed_rows = load_licensed(LICENSED_TOWNS_FILE)
    lookup = build_lookup(municipalities)

    # Aggregate licenses per matched municipality
    awarded: dict[str, dict] = {}
    unresolved = []

    for row in licensed_rows:
        m = match(row["town"], lookup)
        if m:
            key = m["municipality"]
            if key not in awarded:
                awarded[key] = {"license_count": 0, "categories": set()}
            awarded[key]["license_count"] += int(row["license_count"])
            awarded[key]["categories"].update(row["categories"].split(", "))
        else:
            unresolved.append(row["town"])

    if unresolved:
        print(f"Still unresolved ({len(unresolved)}):")
        for t in sorted(unresolved):
            print(f"  {t}")

    results = []
    awarded_count = 0
    not_awarded_count = 0

    for m in municipalities:
        name = m["municipality"]
        if name in awarded:
            status = "awarded"
            license_count = awarded[name]["license_count"]
            categories = ", ".join(sorted(awarded[name]["categories"]))
            awarded_count += 1
        else:
            status = "not_yet_awarded"
            license_count = 0
            categories = ""
            not_awarded_count += 1

        results.append({
            "municipality": name,
            "type": m["type"],
            "county": m["county"],
            "status": status,
            "license_count": license_count,
            "license_categories": categories,
        })

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "municipality", "type", "county",
            "status", "license_count", "license_categories"
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"Total municipalities : {len(results)}")
    print(f"Already awarded      : {awarded_count}")
    print(f"Not yet awarded      : {not_awarded_count}")
    print(f"Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
