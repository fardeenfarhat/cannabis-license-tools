"""
Shared Firecrawl helpers for the deep_dive package.

Uses the same FIRECRAWL_API_KEY env var that rfp_monitor.py already loads.
"""
import os
import time

import requests

FC_BASE_URL   = "https://api.firecrawl.dev/v1"
POLL_INTERVAL = 8   # seconds between batch/scrape status polls


def _headers() -> dict:
    key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not key:
        raise RuntimeError("FIRECRAWL_API_KEY not set in environment")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def firecrawl_search(query: str, limit: int = 5) -> list[dict]:
    """Search and scrape in one call.

    Returns a list of dicts: [{url, title, description, markdown}].
    markdown will be non-empty when Firecrawl supports inline scrapeOptions;
    fall back to firecrawl_scrape_urls() if it comes back empty.
    """
    resp = requests.post(
        f"{FC_BASE_URL}/search",
        json={
            "query": query,
            "limit": limit,
            "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True},
        },
        headers=_headers(),
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise ValueError(f"Firecrawl search error: {data}")

    results = []
    for item in data.get("data", []):
        meta = item.get("metadata") or {}
        results.append({
            "url":         item.get("url", ""),
            "title":       meta.get("title", "") or item.get("title", ""),
            "description": meta.get("description", "") or item.get("description", ""),
            "markdown":    item.get("markdown", ""),
        })
    return results


def firecrawl_scrape_urls(urls: list[str]) -> dict[str, str]:
    """Batch-scrape a list of URLs and return {url: markdown_text}.

    Uses the /v1/batch/scrape endpoint with polling — same pattern as the
    daily monitor loop in rfp_monitor.py.
    """
    if not urls:
        return {}

    headers = _headers()

    resp = requests.post(
        f"{FC_BASE_URL}/batch/scrape",
        json={"urls": urls, "formats": ["markdown"], "onlyMainContent": True},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise ValueError(f"Firecrawl batch start error: {data}")

    batch_id = data["id"]
    print(f"      [firecrawl] batch submitted {len(urls)} URLs -> job {batch_id[:12]}...")

    results: dict[str, str] = {}
    while True:
        time.sleep(POLL_INTERVAL)
        status_resp = requests.get(
            f"{FC_BASE_URL}/batch/scrape/{batch_id}",
            headers=headers,
            timeout=30,
        )
        status_resp.raise_for_status()
        status = status_resp.json()

        state = status.get("status", "")
        print(f"      [firecrawl] {state} — {status.get('completed', 0)}/{status.get('total', len(urls))}")

        if state == "failed":
            raise ValueError(f"Firecrawl batch failed: {status.get('error', '')}")

        if state == "completed":
            for item in status.get("data", []):
                src = item.get("metadata", {}).get("sourceURL", "")
                md  = item.get("markdown", "") or ""
                if src:
                    results[src] = md

            next_url = status.get("next")
            while next_url:
                page = requests.get(next_url, headers=headers, timeout=30)
                page.raise_for_status()
                page_data = page.json()
                for item in page_data.get("data", []):
                    src = item.get("metadata", {}).get("sourceURL", "")
                    md  = item.get("markdown", "") or ""
                    if src:
                        results[src] = md
                next_url = page_data.get("next")

            return results
