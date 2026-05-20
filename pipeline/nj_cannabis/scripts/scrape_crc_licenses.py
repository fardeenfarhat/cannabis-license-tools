"""
Scrape the NJ CRC permitted businesses page and extract all towns that
have at least one active cannabis license.

Source: https://www.nj.gov/cannabis/businesses/permitted/
Output: nj_cannabis/data/crc_licensed_towns.csv
"""

import csv
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CRC_URL = "https://www.nj.gov/cannabis/businesses/permitted/"
OUTPUT_FILE = Path(__file__).parent.parent / "data" / "crc_licensed_towns.csv"
RAW_HTML_FILE = Path(__file__).parent.parent / "data" / "crc_raw.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch_page(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_businesses(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records = []

    # The page has two tables: medicinal and personal-use
    tables = soup.find_all("table")
    sections = ["Medicinal", "Personal-Use"]

    for i, table in enumerate(tables):
        category = sections[i] if i < len(sections) else f"Table {i+1}"
        rows = table.find_all("tr")[1:]  # skip header

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            business_name = cols[0].get_text(strip=True)
            license_types = cols[1].get_text(strip=True)
            locations_raw = cols[2].get_text(strip=True)

            # Skip inactive entries
            if "INACTIVE" in business_name.upper() or "INACTIVE" in locations_raw.upper():
                continue

            # Locations cell may contain multiple towns separated by commas
            towns = [t.strip() for t in locations_raw.split(",") if t.strip()]
            # Strip expiration year suffix like "(2026)" from town names
            towns = [re.sub(r"\s*\(\d{4}\)\s*$", "", t).strip() for t in towns]

            for town in towns:
                if town:
                    records.append({
                        "business_name": business_name,
                        "license_types": license_types,
                        "town": town,
                        "category": category,
                    })

    return records


def extract_licensed_towns(records: list[dict]) -> list[dict]:
    seen = {}
    for r in records:
        town = r["town"]
        if town not in seen:
            seen[town] = {"town": town, "license_count": 0, "categories": set()}
        seen[town]["license_count"] += 1
        seen[town]["categories"].add(r["category"])

    result = []
    for town, data in sorted(seen.items()):
        result.append({
            "town": town,
            "license_count": data["license_count"],
            "categories": ", ".join(sorted(data["categories"])),
        })
    return result


def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print(f"Fetching {CRC_URL} ...")
    html = fetch_page(CRC_URL)

    # Save raw HTML for debugging
    RAW_HTML_FILE.write_text(html, encoding="utf-8")
    print(f"Saved raw HTML to {RAW_HTML_FILE}")

    records = parse_businesses(html)
    print(f"Parsed {len(records)} business-location records")

    licensed_towns = extract_licensed_towns(records)
    print(f"Found {len(licensed_towns)} unique towns with active licenses")

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["town", "license_count", "categories"])
        writer.writeheader()
        writer.writerows(licensed_towns)

    print(f"Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
