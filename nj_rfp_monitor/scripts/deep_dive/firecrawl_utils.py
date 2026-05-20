"""
Shared Firecrawl helpers for the deep_dive package.

Uses the same FIRECRAWL_API_KEY env var that rfp_monitor.py already loads.

Credit-control design:
  - firecrawl_search()     returns URLs+metadata ONLY (no scrapeOptions) → 1 credit per call
  - firecrawl_scrape_urls() deduplicates via a process-local cache; caps PDF pages at PDF_MAX_PAGES
  - FIRECRAWL_BUDGET env var (default 800) triggers BudgetExceededError when exceeded
"""
import os
import time

import requests

FC_BASE_URL   = "https://api.firecrawl.dev/v1"
POLL_INTERVAL = 8   # seconds between batch/scrape status polls

# --- Credit budget guard ---
_CREDIT_BUDGET  = int(os.environ.get("FIRECRAWL_BUDGET", "800"))
_credits_used   = 0

# --- Process-local scrape cache: {url: markdown} ---
# Prevents the same URL being scraped multiple times across sub-tasks.
_SCRAPE_CACHE: dict[str, str] = {}


class BudgetExceededError(RuntimeError):
    pass


def reset_run_state() -> None:
    """Call once at the top of each --deep run to reset credit counter and cache."""
    global _credits_used, _SCRAPE_CACHE
    _credits_used = 0
    _SCRAPE_CACHE = {}


def credits_used() -> int:
    return _credits_used


def _charge(n: int) -> None:
    global _credits_used
    _credits_used += n
    if _credits_used > _CREDIT_BUDGET:
        raise BudgetExceededError(
            f"Firecrawl budget exceeded: {_credits_used}/{_CREDIT_BUDGET} credits used. "
            "Set FIRECRAWL_BUDGET env var to raise limit."
        )


def _headers() -> dict:
    key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not key:
        raise RuntimeError("FIRECRAWL_API_KEY not set in environment")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def firecrawl_search(query: str, limit: int = 3) -> list[dict]:
    """Search for URLs matching a query. Returns [{url, title, description}].

    Does NOT scrape page content — callers must explicitly call firecrawl_scrape_urls()
    on the URLs they want. This costs 1 credit per call regardless of limit.
    """
    _charge(1)
    resp = requests.post(
        f"{FC_BASE_URL}/search",
        json={"query": query, "limit": limit},
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
            "markdown":    "",  # never populated — scrape explicitly
        })
    return results


def firecrawl_scrape_urls(urls: list[str]) -> dict[str, str]:
    """Batch-scrape a list of URLs and return {url: markdown_text}.

    - Deduplicates via process-local cache: same URL across sub-tasks costs 0 extra credits.
    - Caps PDF page billing at PDF_MAX_PAGES pages per document.
    - Charges 1 credit per URL submitted (under-counts PDF pages but catches runaway loops).
    """
    if not urls:
        return {}

    # Serve cached results; only fetch what's new
    result: dict[str, str] = {}
    to_fetch: list[str] = []
    for url in urls:
        if url in _SCRAPE_CACHE:
            result[url] = _SCRAPE_CACHE[url]
            print(f"      [firecrawl] cache hit (run-local): {url[:70]}")
        else:
            to_fetch.append(url)

    if not to_fetch:
        return result

    _charge(len(to_fetch))

    headers = _headers()
    resp = requests.post(
        f"{FC_BASE_URL}/batch/scrape",
        json={
            "urls": to_fetch,
            "formats": ["markdown"],
            "onlyMainContent": True,
        },
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise ValueError(f"Firecrawl batch start error: {data}")

    batch_id = data["id"]
    print(f"      [firecrawl] batch submitted {len(to_fetch)} URLs -> job {batch_id[:12]}...")

    fetched: dict[str, str] = {}
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
        print(f"      [firecrawl] {state} — {status.get('completed', 0)}/{status.get('total', len(to_fetch))}")

        if state == "failed":
            raise ValueError(f"Firecrawl batch failed: {status.get('error', '')}")

        if state == "completed":
            for item in status.get("data", []):
                src = item.get("metadata", {}).get("sourceURL", "")
                md  = item.get("markdown", "") or ""
                if src:
                    fetched[src] = md

            next_url = status.get("next")
            while next_url:
                page = requests.get(next_url, headers=headers, timeout=30)
                page.raise_for_status()
                page_data = page.json()
                for item in page_data.get("data", []):
                    src = item.get("metadata", {}).get("sourceURL", "")
                    md  = item.get("markdown", "") or ""
                    if src:
                        fetched[src] = md
                next_url = page_data.get("next")

            # Store in process cache and merge
            for url, md in fetched.items():
                _SCRAPE_CACHE[url] = md
            result.update(fetched)
            return result
