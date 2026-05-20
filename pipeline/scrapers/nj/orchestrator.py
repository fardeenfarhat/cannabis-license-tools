"""
NJ Cannabis Meeting-Minutes Orchestrator
=========================================
Dispatches to platform-specific scraper agents for NJ municipalities.
City list is loaded dynamically from nj_cannabis/data/nj_portals.csv.

Usage:
    python -m scrapers.nj --all
    python -m scrapers.nj --agendacenter
    python -m scrapers.nj --agendacenter --city "toms river"
    python -m scrapers.nj --civicclerk
    python -m scrapers.nj --legistar
    python -m scrapers.nj --custom-pdf
"""

import argparse
import io
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from .config import cities_for_platform, KEYWORDS, START_DATE, END_DATE
from ..types import Platform, Hit
from ..utils import make_session

OUTPUT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "cannabis_hits", "nj")


def _filter(platform: Platform, city_filter: str | None):
    cities = cities_for_platform(platform)
    if city_filter:
        q = city_filter.lower()
        cities = [c for c in cities if q in c.name.lower() or q in c.slug.lower()]
    return cities


def _print_summary(hits: list[Hit]) -> None:
    if not hits:
        print("\n  No cannabis documents found.")
        return

    print(f"\n{'='*60}")
    print(f"  NJ SUMMARY — {len(hits)} cannabis document(s) found")
    print(f"{'='*60}")

    by_city: dict[str, list[Hit]] = {}
    for h in hits:
        by_city.setdefault(h.city, []).append(h)

    for city, city_hits in sorted(by_city.items()):
        print(f"\n  {city} ({len(city_hits)} doc(s)):")
        for h in city_hits:
            tag = "[OK]" if h.confirmed else "[?] "
            kws = ", ".join(h.matched_keywords) if h.matched_keywords else "-"
            print(f"    {tag}  {h.date}  [{h.doc_type}]  {h.label[:50]}  ({kws})")

    print(f"\n  Files saved to: {os.path.abspath(OUTPUT_ROOT)}")
    print(f"  Date range:     {START_DATE} – {END_DATE}")


def main():
    parser = argparse.ArgumentParser(description="NJ cannabis meeting-minutes scraper")
    parser.add_argument("--agendacenter", action="store_true")
    parser.add_argument("--civicclerk",   action="store_true")
    parser.add_argument("--legistar",     action="store_true")
    parser.add_argument("--civicweb",     action="store_true")
    parser.add_argument("--custom-pdf",   action="store_true", dest="custom_pdf",
                        help="Crawl CivicPlus GovOffice + bare PDF sites (42 municipalities)")
    parser.add_argument("--all",          action="store_true")
    parser.add_argument("--city",         type=str, default=None)
    parser.add_argument("--show-browser", action="store_true", dest="show_browser")
    args = parser.parse_args()

    run_all = args.all or not any([args.agendacenter, args.civicclerk,
                                   args.legistar, args.civicweb, args.custom_pdf])

    os.makedirs(OUTPUT_ROOT, exist_ok=True)

    tasks: list[tuple[str, list]] = []

    if run_all or args.agendacenter:
        cities = _filter(Platform.AGENDACENTER, args.city)
        if cities:
            tasks.append(("agendacenter", cities))

    if run_all or args.civicclerk:
        cities = _filter(Platform.CIVICCLERK, args.city)
        if cities:
            tasks.append(("civicclerk", cities))

    if run_all or args.legistar:
        cities = _filter(Platform.LEGISTAR, args.city)
        if cities:
            tasks.append(("legistar", cities))

    if run_all or args.civicweb:
        cities = _filter(Platform.CIVICWEB, args.city)
        if cities:
            tasks.append(("civicweb", cities))

    if run_all or args.custom_pdf:
        cities = _filter(Platform.CUSTOM_PDF, args.city)
        if cities:
            tasks.append(("custom_pdf", cities))

    headless = not args.show_browser

    def _run_platform(task: tuple[str, list]) -> list[Hit]:
        name, cities = task
        session = make_session()

        if name == "agendacenter":
            from .. import agendacenter
            return agendacenter.search(cities, session, OUTPUT_ROOT)
        if name == "civicclerk":
            from .. import civicclerk
            return civicclerk.search(cities, session, OUTPUT_ROOT, headless=headless)
        if name == "legistar":
            from .. import legistar
            return legistar.search(cities, session, OUTPUT_ROOT)
        if name == "civicweb":
            from .. import civicweb
            return civicweb.search(cities, session, OUTPUT_ROOT, headless=headless)
        if name == "custom_pdf":
            from .. import custom_pdf
            return custom_pdf.search(cities, session, OUTPUT_ROOT)
        return []

    all_hits: list[Hit] = []

    with ThreadPoolExecutor(max_workers=len(tasks) or 1) as pool:
        futures = {pool.submit(_run_platform, task): task[0] for task in tasks}
        for fut in as_completed(futures):
            platform_name = futures[fut]
            try:
                all_hits.extend(fut.result())
            except Exception as exc:
                print(f"  [X] Platform '{platform_name}' error: {exc}")

    _print_summary(all_hits)


if __name__ == "__main__":
    main()
