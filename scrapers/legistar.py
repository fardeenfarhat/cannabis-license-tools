"""Agent 3 — Legistar REST API scraper.

Queries webapi.legistar.com for events, downloads minutes PDFs,
falls back to matter attachments when the minutes PDF has no keywords.

Cities are searched in parallel (ThreadPoolExecutor); each worker gets its
own requests.Session.  Output is buffered per city and printed atomically.
Attachment scanning is always enabled.
"""

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .config import CityConfig, KEYWORDS, START_DATE, END_DATE
from .types import Hit, Platform
from .utils import safe_filename, keyword_in_pdf, download_pdf, make_session

MINUTES_READY_STATUS_IDS = {2, 3, 5, 6, 7, 8, 9}

_print_lock = threading.Lock()
WORKERS = 4


def _api_get(client: str, path: str, session: requests.Session) -> list:
    url = f"https://webapi.legistar.com/v1/{client}/{path}"
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return []


def _fetch_matter_attachments(event_id: int, client: str, session: requests.Session,
                               log) -> list[dict]:
    """Return PDF attachments from all matters linked to this event."""
    items     = _api_get(client, f"events/{event_id}/eventitems", session)
    matter_ids = list({i["EventItemMatterId"] for i in items if i.get("EventItemMatterId")})
    log(f"    [dbg] {len(items)} items, {len(matter_ids)} matters -> scanning attachments")

    attachments: list[dict] = []
    for mid in matter_ids:
        for att in _api_get(client, f"matters/{mid}/attachments", session):
            url = att.get("MatterAttachmentHyperlink") or ""
            if url.lower().endswith(".pdf"):
                attachments.append({
                    "url":       url,
                    "name":      att.get("MatterAttachmentName", ""),
                    "matter_id": mid,
                })
    log(f"    [dbg] {len(attachments)} PDF attachment(s) found")
    return attachments


def _search_one_city(city: CityConfig, output_root: str,
                     skip_attachments: bool) -> tuple[list[Hit], str]:
    """Search one Legistar city. Prints progress live (lock-protected)."""

    def p(*args, **kwargs):
        with _print_lock:
            print(*args, **kwargs)
            sys.stdout.flush()

    session   = make_session()
    hits: list[Hit] = []
    client    = city.legistar_client
    city_name = city.name
    folder    = os.path.join(output_root, "legistar", city_name.replace(" ", "_"))
    os.makedirs(folder, exist_ok=True)

    start_year   = START_DATE[:4]
    end_year     = END_DATE[:4]
    target_years = {str(y) for y in range(int(start_year), int(end_year) + 1)}

    p(f"\n{'='*60}")
    p(f"  [Legistar] {city_name}  (client: {client})")
    p(f"{'='*60}")

    events_raw = _api_get(client, "events?$orderby=EventDate desc&$top=1000", session)
    events = []
    for ev in events_raw:
        raw_date = ev.get("EventDate", "") or ""
        if raw_date[:4] not in target_years:
            continue
        ev_id   = ev.get("EventId")
        ev_guid = ev.get("EventGuid", "")
        min_file = ev.get("EventMinutesFile")
        min_sid  = ev.get("EventMinutesStatusId", 0)

        if min_file:
            pdf_url = min_file
        else:
            # View.ashx?M=M returns an HTML viewer page, not a PDF — skip it
            continue

        events.append({"id": ev_id, "date": raw_date[:10],
                        "body": ev.get("EventBodyName", "Unknown"), "url": pdf_url})

    p(f"  -> {len(events)} meeting(s) with direct minutes PDF in {sorted(target_years)}")

    for ev in events:
        body_safe = safe_filename(ev["body"])
        fname     = f"{ev['date']}_{body_safe}_{ev['id']}.pdf"
        fpath     = os.path.join(folder, fname)

        if os.path.exists(fpath):
            p(f"    [skip] {fname}")
            hits.append(Hit(city=city_name, platform=Platform.LEGISTAR,
                            date=ev["date"], doc_type="Minutes", label=ev["body"],
                            url=ev["url"], file_path=fpath, confirmed=True,
                            matched_keywords=KEYWORDS[:1]))
            continue

        pdf_bytes = download_pdf(ev["url"], session)
        size_kb   = f"{len(pdf_bytes)//1024}KB" if pdf_bytes else "no PDF"

        matched: list[str] = []
        if pdf_bytes:
            matched = keyword_in_pdf(pdf_bytes, KEYWORDS)

        p(f"    [{city_name}] v {ev['date']} - {ev['body']}  {size_kb}  keywords={matched if matched else 'none'}")

        if matched and pdf_bytes:
            with open(fpath, "wb") as f:
                f.write(pdf_bytes)
            p(f"    -> SAVED: {fname}")
            hits.append(Hit(city=city_name, platform=Platform.LEGISTAR,
                            date=ev["date"], doc_type="Minutes", label=ev["body"],
                            url=ev["url"], file_path=fpath, confirmed=True,
                            matched_keywords=matched))
            time.sleep(0.4)
            continue

        # Only scan attachments if we got a PDF but it had no keywords.
        # If the download failed entirely, skip — no point scanning attachments
        # for a meeting whose minutes aren't available.
        if skip_attachments or not pdf_bytes:
            continue

        p(f"\n    [dbg] no keywords in minutes -> scanning matter attachments...")
        attachments = _fetch_matter_attachments(ev["id"], client, session, p)

        for idx, att in enumerate(attachments):
            att_name  = safe_filename(att["name"])
            att_fname = f"{ev['date']}_{body_safe}_{ev['id']}_att{idx}_{att_name}.pdf"
            att_fpath = os.path.join(folder, att_fname)

            if os.path.exists(att_fpath):
                p(f"    [skip-att] {att_fname}")
                continue

            att_bytes = download_pdf(att["url"], session)
            if not att_bytes:
                continue

            att_matched = keyword_in_pdf(att_bytes, KEYWORDS)
            if att_matched:
                with open(att_fpath, "wb") as f:
                    f.write(att_bytes)
                p(f"    -> SAVED (attachment) [{', '.join(att_matched)}] -> {att_fname}")
                hits.append(Hit(city=city_name, platform=Platform.LEGISTAR,
                                date=ev["date"], doc_type="Attachment", label=att["name"],
                                url=att["url"], file_path=att_fpath, confirmed=True,
                                matched_keywords=att_matched))
            time.sleep(0.4)

    return hits


def search(cities: list[CityConfig], session: requests.Session, output_root: str,
           skip_attachments: bool = False) -> list[Hit]:
    all_hits: list[Hit] = []

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {
            pool.submit(_search_one_city, city, output_root, skip_attachments): city
            for city in cities
        }
        for fut in as_completed(futures):
            city = futures[fut]
            try:
                all_hits.extend(fut.result())
            except Exception as exc:
                with _print_lock:
                    print(f"  [X] {city.name}: {exc}")

    return all_hits
