"""
Playwright-based browser scrape fallback for JS-heavy portals.

Called by attorneys.py (and optionally council_votes.py) only after all
Firecrawl strategies return no useful content. Results are cached in the
shared SQLite DB (30-day TTL) so repeat runs are free.

Requires: playwright package + chromium browser installed.
  pip install playwright
  playwright install chromium

If playwright is not installed the function returns "" gracefully so the
pipeline degrades without crashing.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone, timedelta

BROWSER_TTL_DAYS = 30

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS browser_scrapes (
    url      TEXT PRIMARY KEY,
    text     TEXT,
    found_at TEXT
)
"""


def _ensure_table(con: sqlite3.Connection) -> None:
    con.execute(_CREATE_TABLE)
    con.commit()


def _get_cached(con: sqlite3.Connection, url: str) -> str | None:
    _ensure_table(con)
    row = con.execute(
        "SELECT text, found_at FROM browser_scrapes WHERE url = ?", (url,)
    ).fetchone()
    if not row:
        return None
    try:
        cached_at = datetime.fromisoformat(row[1])
    except (TypeError, ValueError):
        return None
    if datetime.now(timezone.utc) - cached_at > timedelta(days=BROWSER_TTL_DAYS):
        return None
    return row[0]


def _cache_result(con: sqlite3.Connection, url: str, text: str) -> None:
    _ensure_table(con)
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        """
        INSERT INTO browser_scrapes (url, text, found_at)
        VALUES (?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            text     = excluded.text,
            found_at = excluded.found_at
        """,
        (url, text, now),
    )
    con.commit()


async def _async_render(url: str) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return ""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            text = await page.evaluate("document.body.innerText")
            return text or ""
        except Exception as e:
            print(f"      [browser] playwright error for {url[:60]}: {e}")
            return ""
        finally:
            await browser.close()


def playwright_scrape(url: str, con: sqlite3.Connection) -> str:
    """Render a URL with a real browser and return its visible text content.

    Cached 30 days in the browser_scrapes SQLite table. Returns "" if
    playwright is not installed or if the page errors.
    """
    cached = _get_cached(con, url)
    if cached is not None:
        print(f"      [browser] cache hit: {url[:60]}")
        return cached

    print(f"      [browser] rendering with Playwright: {url[:60]}")
    try:
        text = asyncio.run(_async_render(url))
    except RuntimeError:
        # asyncio.run() fails if an event loop is already running (e.g. Jupyter)
        import nest_asyncio  # type: ignore
        nest_asyncio.apply()
        text = asyncio.get_event_loop().run_until_complete(_async_render(url))
    except Exception as e:
        print(f"      [browser] asyncio error: {e}")
        text = ""

    if text:
        _cache_result(con, url, text)
    return text
