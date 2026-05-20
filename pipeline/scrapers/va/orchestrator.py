"""
Virginia Cannabis Meeting-Minutes Orchestrator
===============================================
Dispatches to platform-specific scraper agents based on CLI flags.
All enabled platforms run concurrently; within each platform, cities
also run in parallel.

Usage:
    python -m scrapers.va --all
    python -m scrapers.va --agendacenter
    python -m scrapers.va --legistar --city richmond
    python -m scrapers.va --civic-scraper
    python -m scrapers.va --civicweb
    python -m scrapers.va --civicclerk
"""

import argparse
import io
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from .config import CITIES, cities_for_platform
from ..types import Platform, Hit
from ..utils import make_session

OUTPUT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "cannabis_hits", "va")


def _filter_cities(platform: Platform, city_filter: str | None):
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
    print(f"  SUMMARY — {len(hits)} cannabis document(s) found")
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


def main():
    parser = argparse.ArgumentParser(description="Virginia cannabis meeting-minutes scraper")
    parser.add_argument("--agendacenter",  action="store_true")
    parser.add_argument("--civicweb",      action="store_true")
    parser.add_argument("--legistar",      action="store_true")
    parser.add_argument("--civic-scraper", action="store_true", dest="civic_scraper")
    parser.add_argument("--civicclerk",    action="store_true")
    parser.add_argument("--all",           action="store_true")
    parser.add_argument("--city",          type=str, default=None)
    parser.add_argument("--show-browser",  action="store_true", dest="show_browser")
    parser.add_argument("--attachments",   action="store_true", dest="attachments")
    args = parser.parse_args()

    run_all = args.all or not any([args.agendacenter, args.civicweb, args.legistar,
                                   args.civic_scraper, args.civicclerk])

    os.makedirs(OUTPUT_ROOT, exist_ok=True)

    tasks: list[tuple[str, list]] = []

    if run_all or args.agendacenter:
        cities = _filter_cities(Platform.AGENDACENTER, args.city)
        if cities:
            tasks.append(("agendacenter", cities))

    if run_all or args.legistar:
        cities = _filter_cities(Platform.LEGISTAR, args.city)
        if cities:
            tasks.append(("legistar", cities))

    if run_all or args.civic_scraper:
        cities = _filter_cities(Platform.CIVIC_SCRAPER, args.city)
        if cities:
            tasks.append(("civic_scraper", cities))

    if run_all or args.civicweb:
        cities = _filter_cities(Platform.CIVICWEB, args.city)
        if cities:
            tasks.append(("civicweb", cities))

    if run_all or args.civicclerk:
        cities = _filter_cities(Platform.CIVICCLERK, args.city)
        if cities:
            tasks.append(("civicclerk", cities))

    headless    = not args.show_browser
    attachments = args.attachments

    def _run_platform(task: tuple[str, list]) -> list[Hit]:
        name, cities = task
        session = make_session()

        if name == "agendacenter":
            from .. import agendacenter
            return agendacenter.search(cities, session, OUTPUT_ROOT)
        if name == "legistar":
            from .. import legistar
            return legistar.search(cities, session, OUTPUT_ROOT, skip_attachments=not attachments)
        if name == "civic_scraper":
            from .. import civic_scraper_agent
            return civic_scraper_agent.search(cities, session, OUTPUT_ROOT)
        if name == "civicweb":
            from .. import civicweb
            return civicweb.search(cities, session, OUTPUT_ROOT, headless=headless)
        if name == "civicclerk":
            from .. import civicclerk
            return civicclerk.search(cities, session, OUTPUT_ROOT, headless=headless)
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
