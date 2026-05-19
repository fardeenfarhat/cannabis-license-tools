"""
Parse NJ municipalities from the LaTeX source file into a clean CSV.
Output: nj_cannabis/data/nj_municipalities.csv
"""

import re
import csv
from pathlib import Path

TEX_FILE = Path(__file__).parent.parent.parent / "Misc" / "new_jersey_municipalities.tex"
OUTPUT_FILE = Path(__file__).parent.parent / "data" / "nj_municipalities.csv"

COUNTY_PATTERN = re.compile(r"\\section\*\{(.+?) County\}")
ROW_PATTERN = re.compile(r"^([A-Za-z].*?)\s*&\s*(Borough|Township|City|Town|Village|Municipality)\s*\\\\", re.MULTILINE)


def parse(tex_path: Path) -> list[dict]:
    text = tex_path.read_text(encoding="utf-8")
    records = []
    current_county = None

    for line in text.splitlines():
        county_match = COUNTY_PATTERN.search(line)
        if county_match:
            current_county = county_match.group(1).strip()
            continue

        row_match = ROW_PATTERN.match(line.strip())
        if row_match and current_county:
            name = row_match.group(1).strip()
            mtype = row_match.group(2).strip()
            records.append({
                "municipality": name,
                "type": mtype,
                "county": current_county,
            })

    return records


def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    records = parse(TEX_FILE)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["municipality", "type", "county"])
        writer.writeheader()
        writer.writerows(records)

    print(f"Saved {len(records)} municipalities to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
