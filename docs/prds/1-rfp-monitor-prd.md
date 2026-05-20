# PRD — RFP Monitor

### Overview

- **Agent name:** rfp-monitor
- **One-liner:** Daily watcher across ~344 NJ municipal RFP and legal-notice pages that surfaces newly posted Class-5 cannabis retail RFPs within 24 hours.
- **Owner:** Fardeen Farhat (Engineering)
- **Status:** Approved — LIVE

### Problem

- **What problem are we solving?** Cannabis retail RFPs in NJ get posted on individual town websites with no central listing. Missing the launch by even a few days can mean missing the application window. Manually checking 344 towns daily is not viable.
- **Who experiences it and in what context?** The operations team (Abbas, Fardeen) needs early visibility into every new RFP so the deep-dive and outreach pipeline can fire before the questions deadline.

### Goals and non-goals

**Goals**

- Detect every new NJ Class-5 cannabis retail RFP within 24 hours of posting.
- Capture both deadlines: `application_deadline` and `questions_deadline`.
- Keep false-positive rate on HIGH-confidence hits below 10%.
- Run unattended on a daily schedule.

**Non-goals**

- Not a deep research tool (that is the `deep-dive` skill).
- Not filing applications or sending outreach.
- Not monitoring states outside New Jersey.

### Users and use cases

- **Primary user(s):** Operations team — they trigger the daily sweep and review hits.
- **Secondary user(s):** Application team — they pick up hits to route into deep-dive.
- **Top use cases:**
    - Daily unattended sweep across all 344 towns.
    - Quick test on a single town (`--town "Vineland"`).
    - First-run summary CSV across every town with any cannabis content (`--first-run`).
    - Priority-only run (~20 hand-curated towns) when credits are tight.

### Success metrics

- **How we will measure success:**
    - Time-to-detection from town posting to alert: ≤24 hours.
    - False-positive rate on HIGH-confidence hits: <10%.
    - Full sweep completes: ≤45 min on free plan, ≤18 min on paid plan.
    - Firecrawl credit spend per sweep stays within plan limits.
    - Zero missed RFPs caught manually by team.

### Requirements

**Functional requirements**

- Read town monitoring URLs live from the Notion RFPs Monitoring Database.
- Submit URLs to Firecrawl `/v1/batch/scrape` in groups of 20.
- Diff scraped content against previous snapshot via SHA-256 hash.
- Classify changed pages with GPT-4o-mini; fall back to keyword regex.
- Persist hits to SQLite + append to `rfp_hits.csv`.
- Send email alert on new hits if SMTP is configured.

**Non-functional requirements**

- **Quality:** HIGH-confidence precision ≥90%; both deadlines extracted when present on page.
- **Reliability:** Pipeline must complete even when OpenAI is unavailable (keyword fallback path).
- **Privacy and security:** API keys live in `.env`, never committed. No PII in scraped content. No outbound writes to town sites.

### Agent behavior

- **Inputs:** CLI flags (`--town`, `--limit`, `--priority`, `--reset`, `--first-run`, `--csv`); Notion DB URLs; env vars.
- **Outputs:** `rfp_hits.csv`, optional `first_run_summary.csv`, SQLite snapshots, console summary, optional email alert.
- **Tone and style:** Operational logs — concise, factual. Email alerts include town, deadline, URL, confidence.
- **Allowed tools and data sources:** Firecrawl API, OpenAI API, Notion API, SMTP. No live writes to municipal sites.
- **Boundaries (what it must not do):**
    - Never submits anything to a town site.
    - Never sends email outside the team.
    - Never modifies Notion records (read-only).
    - Never escalates a LOW-confidence hit to an alert.

### Flow (happy path)

1. Daily cron / on-demand trigger fires.
2. Load 344 town URLs from Notion.
3. Group URLs into batches of 20.
4. Submit each batch to Firecrawl, poll every 8 seconds until complete.
5. For each scraped page: compute SHA-256, compare against previous snapshot.
6. For changed pages: run GPT-4o-mini classifier (or keyword fallback).
7. For HIGH/MEDIUM hits: save to SQLite, append to CSV, send email alert.
8. Print summary, exit.

### Edge cases and failure handling

- **Town site down or 5xx:** log FETCH ERROR, retry on next daily run, flag if persistent.
- **Firecrawl rate limit:** batch retries with backoff.
- **OpenAI API unavailable:** fall through to keyword regex; mark confidence "low" until reprocessed.
- **Page changed but content unrelated to cannabis:** classify as no-hit, snapshot updated.
- **URL changed by the town:** detected as a fetch error; team updates Notion manually.
- **Multiple RFPs on one page:** classifier returns the most prominent one; rest surfaced in `snippet`.

### Dependencies and risks

- **Dependencies:** Firecrawl, OpenAI (optional), Notion API, SMTP (optional). `nj_rfp_monitor/data/*.csv` for fallback URL lists.
- **Risks:**
    - Town websites change layout silently — scrapers can degrade without throwing errors.
    - LLM false positives on cannabis news mentions (not actual RFPs).
    - Notion DB sync issues if Zain restructures.
- **Open questions:**
    - Should a HIGH hit trigger an immediate same-day re-scan of that town?
    - Should we add Slack alerts alongside email?
    - At what credit-spend threshold do we move from free to paid Firecrawl?

### Rollout plan

- **Milestones:**
    - Phase 1 (DONE): two-deadline extraction shipped.
    - Phase 1.1 (NEXT): wire daily cron in production.
    - Phase 1.2: Slack alert channel.
    - Phase 1.3: weekly trend report.
- **QA / evaluation plan:** Weekly manual spot-check of 10 random HIGH hits — confirm RFP exists and deadlines are correct.
- **Launch checklist:**
    - `.env` populated with FIRECRAWL_API_KEY, NOTION_TOKEN, OPENAI_API_KEY.
    - Notion DB has at least 1 Monitoring URL per priority town.
    - Daily cron scheduled.
    - SMTP credentials tested with a dry-run alert.

### Appendix

- **Links:**
    - Code: [nj_rfp_monitor/scripts/rfp_monitor.py](../../nj_rfp_monitor/scripts/rfp_monitor.py)
    - Skill: [.claude/skills/rfp-monitor/SKILL.md](../../.claude/skills/rfp-monitor/SKILL.md)
    - Workflow diagram: [docs/workflows/1-rfp-monitor.md](../workflows/1-rfp-monitor.md)
- **Notes:** Class 5 = adult-use cannabis retailer license. Opt-in towns are not the same as active RFPs — many have moratoriums or waitlists.
