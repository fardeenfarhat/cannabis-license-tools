---
name: rfp-monitor
description: Run the NJ cannabis retail RFP monitor — scans NJ municipalities for newly posted Class-5 retail license RFPs using Firecrawl + GPT classifier. URLs are read live from the Notion RFPs Monitoring Database. Scraping uses Firecrawl batch mode (concurrent browsers). Use when the user asks to "check RFPs", "run the monitor", "scan towns", "see what's new", "first run", or mentions the NJ cannabis RFP scraper.
argument-hint: "[--priority] [--town <name>] [--limit N] [--reset] [--verbose] [--first-run] [--csv]"
---

# NJ Cannabis RFP Monitor

Watches NJ municipal RFP/bid/legal-notice pages for new Class-5 (cannabis
retail) license RFPs. Runs via Firecrawl batch scraping — submits URLs in
batches of 20, Firecrawl processes them across all concurrent browser slots
simultaneously (2 on free plan, 5 on paid). Classifies with GPT-4o-mini or
keyword rules, deduplicates via SHA-256 snapshot hashes, saves hits to SQLite + CSV.

**URL source**: Notion RFPs Monitoring Database (344 towns, up to 6 URLs each).
Each town's "Monitoring URL" field holds all its municipal government legal-notice
links — school boards, libraries, and utilities are excluded.

Project location: [nj_rfp_monitor/](../../../nj_rfp_monitor/)

## Running the monitor

Parse `$ARGUMENTS` for flags. Default loads all towns from Notion and runs a
full sweep in batch mode.

| Flag | Meaning |
|------|---------|
| `--limit 1` | **Quick test** — 1 URL only, minimal Firecrawl credit usage |
| `--town "Name"` | Single town — e.g. `--town "Edison"` |
| `--priority` | ~20 hand-curated towns (Vineland, Morristown, Newark, etc.) |
| `--limit N` | First N URLs from Notion |
| `--first-run` | Also write `first_run_summary.csv` — Town, Date, Summary for every town with any cannabis content (moratoriums, ordinances, windows, active RFPs) |
| `--verbose` | Show unchanged URLs too |
| `--reset` | Clear snapshot DB — forces full re-scan |
| `--csv` | Use `rfp_seed_urls.csv` instead of Notion (legacy fallback) |
| (none) | Full sweep — all 344 towns from Notion |

**Invocation:**
```bash
c:/python312/python.exe nj_rfp_monitor/scripts/rfp_monitor.py $ARGUMENTS
```

Use `run_in_background: true` for anything beyond `--limit 5`.
Full sweep timing (batch mode with concurrent browsers):
- 2 browsers (free plan): ~45 min for all 344 towns
- 5 browsers (paid plan): ~18 min for all 344 towns

Env vars auto-load from [nj_rfp_monitor/.env](../../../nj_rfp_monitor/.env).
Required: `FIRECRAWL_API_KEY`, `NOTION_TOKEN`. Optional: `OPENAI_API_KEY`, `NOTION_RFP_HITS_DB_ID`.

## How batch scraping works

URLs are grouped into batches of 20. Each batch is submitted to Firecrawl's
`/v1/batch/scrape` endpoint as a single job. Firecrawl processes the batch
across all concurrent browser slots in parallel, then the monitor polls every
8 seconds until the job completes. No per-URL delay needed. The `BATCH_SIZE`
constant (top of script) can be tuned if needed.

## Output files to check after a run

- **[nj_rfp_monitor/hits/rfp_hits.csv](../../../nj_rfp_monitor/hits/rfp_hits.csv)** — confirmed RFP hits (appended each run)
- **[nj_rfp_monitor/data/first_run_summary.csv](../../../nj_rfp_monitor/data/first_run_summary.csv)** — Town, Date, Summary from `--first-run` (joinable by Town)
- **nj_rfp_monitor/data/rfp_monitor.db** — SQLite: `rfp_hits` + `page_snapshots` tables
- **Console tail** — hit summary printed at the end

## Interpreting results

- **HIGH confidence hit** = live cannabis RFP almost certainly. Alert the user immediately with town, deadline, URL.
- **MEDIUM hit** = likely RFP-related; verify by opening the URL.
- **LOW hit** = weak signal; may be a general cannabis ordinance page, not an RFP.
- **"no cannabis RFP signals found"** on a changed page = page updated but not about cannabis.
- **FETCH ERROR** = site blocks scrapers or bad URL. Flag for manual follow-up.
- **first_run_summary.csv** = broader than hits — includes moratoriums, ordinances, any cannabis date. Join to other town data on the `town` column.

## Updating monitoring URLs

URLs come directly from Notion. To add/change a town's monitoring URLs, update
the "Monitoring URL" field on that town's page in the Notion RFPs Monitoring
Database — no code changes needed.

## Key context for the model

- **Class 5** = adult-use cannabis retailer license (the target).
- **Opted-in** town ≠ active RFP. Many opted-in towns have moratoriums or waitlists.
- **Moratorium** = town froze new applications until a given date — track the expiration as a signal.
- When an ordinance passes "Cannabis Establishment Licensing" (e.g. Vineland Ord. 2026-17), that's the legislative precursor to an RFP. Treat as an imminent-RFP signal even if no RFP has posted yet.
- Data source of truth for opt-in status: [nj_rfp_monitor/data/nj_opted_in_municipalities.csv](../../../nj_rfp_monitor/data/nj_opted_in_municipalities.csv)

## Notion DB IDs

Read all Notion database IDs from the config file before starting:

```
Read: .claude/notion_config.md
```

Use the IDs from that file for every Notion API call. Do not hardcode IDs here — the config file is the single source of truth.

## Your task

1. Parse `$ARGUMENTS` — pick the right run mode.
2. If user says "first run" or wants a summary CSV, add `--first-run` flag.
3. If no flags given and this looks like a test, suggest `--limit 5 --first-run` first.
4. **Run connection check** (see section below) before starting any scan.
5. Run the monitor. Use `run_in_background: true` unless `--limit` is small (≤5).
6. When it completes, summarize: new hits found, confidence level, deadlines, and what action the user should take.
7. If there are hits: query the SQLite DB for new hits from this run:
   ```python
   import sqlite3, json
   con = sqlite3.connect('nj_rfp_monitor/data/rfp_monitor.db')
   rows = con.execute("SELECT * FROM rfp_hits ORDER BY first_seen DESC LIMIT 50").fetchall()
   con.close()
   print(json.dumps(rows))
   ```
   Show newest entries with town, confidence, deadline, URL.
8. **Push each new hit to Notion RFP Hits DB** (see section below). Verify each write.
9. If `--first-run` was used and the file exists: read [nj_rfp_monitor/data/first_run_summary.csv](../../../nj_rfp_monitor/data/first_run_summary.csv) and show a count + sample rows.
10. If any FETCH ERRORs on sites that should work, suggest the user update that town's Monitoring URL in Notion.

## Connection check (run before every scan)

Use `mcp__notion__API-retrieve-a-database` to verify each DB is accessible and correctly wired. Run all checks in parallel.

**Check 1 — RFP Hits DB exists:**
- Call `mcp__notion__API-retrieve-a-database` with ID `34f61279-b083-8054-9aaf-ce23adfb2a94`.
- If 404 → "RFP Hits DB not accessible — check integration permissions."
- If OK → confirm title is "RFP Hits" and note it's accessible.

**Check 2 — Sub-DBs have Town relation pointing to RFP Hits DB (not Monitoring DB):**
- Call `mcp__notion__API-retrieve-a-database` for each sub-DB using its hardcoded ID above (run in parallel).
- For each, find the `Town` property and check `relation.database_id`.
- It should match `34f61279-b083-8054-9aaf-ce23adfb2a94`. If it still shows `34c61279-b083-8097-9d84-fed2a9c31570` (the Monitoring DB), flag it: "⚠️ [DB name] Town relation still points to Monitoring DB — Zain needs to re-point it."

**Report format:**
```
Notion connection check:
  ✅ RFP Hits DB         — accessible ("RFP Hits" — 0 rows)
  ✅ Draft Emails        — Town → RFP Hits DB ✓
  ✅ Officials           — Town → RFP Hits DB ✓
  ✅ Attorneys           — Town → RFP Hits DB ✓
  ✅ FOIA Requests       — Town → RFP Hits DB ✓
```
If any check fails, stop and report. Do not proceed with the scan until all connections are green.

## Pushing hits to Notion RFP Hits DB

Do this for every new hit. Only skip if the connection check failed.

**Step 1 — Dedup check:** search for an existing row by town name using `mcp__notion__API-post-search`:
- Query: `"<municipality>"`, filter: `{ "property": "object", "value": "page" }`.
- If a page exists in the RFP Hits DB for this town → patch it with `mcp__notion__API-patch-page`.
- If not found → create with `mcp__notion__API-post-page`.

**Step 2 — Create/patch the row:**

RFP Hits DB ID: `34f61279-b083-8054-9aaf-ce23adfb2a94`

> **Schema notes (must match exactly):**
> - Title field is `TOWN NAME` (not "Name")
> - `Status` is type `status` — use `{ "status": { "name": "..." } }` not `select`
> - `Monitor URL` and `Ordinance URL` are `files` type — use the external file format below
> - `Confidence` select options are lowercase: `"high"`, `"medium"`, `"low"`

```json
{
  "parent": { "database_id": "34f61279-b083-8054-9aaf-ce23adfb2a94" },
  "properties": {
    "TOWN NAME":     { "title": [{ "text": { "content": "<municipality>" } }] },
    "Status":        { "status": { "name": "RFP Anticipated" } },
    "Confidence":    { "select": { "name": "<high|medium|low>" } },
    "County":        { "rich_text": [{ "text": { "content": "<county>" } }] },
    "Monitor URL":   { "files": [{ "type": "external", "name": "<municipality>", "external": { "url": "<monitor_url>" } }] },
    "RFP Title":     { "rich_text": [{ "text": { "content": "<rfp_title>" } }] },
    "License Types": { "rich_text": [{ "text": { "content": "<license_types>" } }] },
    "Snippet":       { "rich_text": [{ "text": { "content": "<snippet, max 2000 chars>" } }] },
    "First Seen":    { "date": { "start": "<first_seen as YYYY-MM-DD>" } }
  }
}
```

For `Application Deadline` and `Questions Deadline`: only add if parseable as a real date — convert to `YYYY-MM-DD`. If not parseable, skip the date property (a malformed date crashes the API).

**Step 3 — Verify the write:** after creating/patching, call `mcp__notion__API-retrieve-a-page` on the returned page ID. Confirm the `Name` and `Status` fields came back correctly.

**Step 4 — Confirm to user:** "✅ Logged to Notion: [Town Name] ([confidence] confidence)" for each hit, or "❌ Notion write failed: [error]" if it didn't.
