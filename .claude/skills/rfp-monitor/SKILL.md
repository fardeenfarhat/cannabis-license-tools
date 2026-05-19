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
Required: `FIRECRAWL_API_KEY`, `NOTION_TOKEN`. Optional: `OPENAI_API_KEY`.

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

## Your task

1. Parse `$ARGUMENTS` — pick the right run mode.
2. If user says "first run" or wants a summary CSV, add `--first-run` flag.
3. If no flags given and this looks like a test, suggest `--limit 5 --first-run` first.
4. Run the monitor. Use `run_in_background: true` unless `--limit` is small (≤5).
5. When it completes, summarize: new hits found, confidence level, deadlines, and what action the user should take.
6. If there are hits: read [nj_rfp_monitor/hits/rfp_hits.csv](../../../nj_rfp_monitor/hits/rfp_hits.csv) and show newest entries.
7. If `--first-run` was used and the file exists: read [nj_rfp_monitor/data/first_run_summary.csv](../../../nj_rfp_monitor/data/first_run_summary.csv) and show a count + sample rows.
8. If any FETCH ERRORs on sites that should work, suggest the user update that town's Monitoring URL in Notion.
