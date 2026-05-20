# PRD — Cannabis Search NJ

### Overview

- **Agent name:** cannabis-search-nj
- **One-liner:** Wide-net early-warning sweep of ~210 NJ municipal meeting-minutes portals for cannabis keyword mentions, across AgendaCenter, CivicClerk, Legistar, and custom-PDF platforms.
- **Owner:** Fardeen Farhat (Engineering)
- **Status:** Approved — LIVE

### Problem

- **What problem are we solving?** Many NJ towns discuss cannabis in council and planning-board meetings long before any ordinance lands or any RFP posts. The `rfp-monitor` only catches the final stage. We need a wider sweep that catches conversations earlier — moratorium expirations, draft ordinance discussions, public hearings, zoning amendments.
- **Who experiences it and in what context?** Business-development team — they hunt for "talkers but not yet doers" towns to engage early.

### Goals and non-goals

**Goals**

- Sweep ~210 unique NJ municipalities for cannabis-keyword mentions in meeting minutes.
- Cover 5 portal platforms (AgendaCenter, custom-PDF, CivicClerk, Legistar, civic-scraper).
- Surface matching PDFs with town, date, and label.
- Run weekly or on-demand at low cost.
- Make adding new municipalities a CSV edit, not a code change.

**Non-goals**

- Not an RFP detector — that signal is captured by `rfp-monitor`.
- Not for outreach, filing, or follow-up.
- Not for Virginia (sister skill).
- Not for image-only PDFs (no OCR — yet).

### Users and use cases

- **Primary user(s):** Business development / lead-gen.
- **Secondary user(s):** Operations team using hits to seed the priority watch list.
- **Top use cases:**
    - Weekly broad sweep across all platforms (`--all`).
    - Targeted lookup on a single town (`--agendacenter --city "toms river"`).
    - Single-platform run when a new portal type is added.
    - Platform detection sweep for unknown towns (`detect_platform.py`).

### Success metrics

- **How we will measure success:**
    - Coverage: 222/375 NJ municipalities reachable by a scraper.
    - Hit precision: ≥80% of flagged PDFs actually substantively discuss cannabis (not just a keyword false-positive).
    - Weekly run completes: ≤2 hours.
    - New municipalities onboarded via CSV with zero code changes.

### Requirements

**Functional requirements**

- Per-platform scrapers for AgendaCenter, CivicClerk, Legistar, civic-scraper, custom-PDF.
- Town list loaded dynamically from `nj_cannabis/data/nj_portals.csv`.
- Keyword matching on extracted PDF text against 4 keywords (`cannabis`, `cannabis retail`, `dispensary`, `marijuana license`).
- Date filter: last 2 years rolling.
- Save matching PDFs to `cannabis_hits/nj/` with a deterministic filename.
- Platform detection utility (`detect_platform.py`) for unknown towns.

**Non-functional requirements**

- **Quality:** Keyword false-positive rate <20%. Date filter strictly applied.
- **Reliability:** Site failures isolated — one town's 5xx must not crash the sweep.
- **Privacy and security:** Public-record content only. Polite scraping (delays, real user-agent). Respect `robots.txt` where the site declares it.

### Agent behavior

- **Inputs:** Platform flag (`--agendacenter`, `--custom-pdf`, etc., or `--all`), optional `--city <name>`.
- **Outputs:** PDFs saved to `cannabis_hits/nj/`; console summary by platform.
- **Tone and style:** Operational logs — concise, per-town status lines.
- **Allowed tools and data sources:** `requests`, `PyPDF2`, per-platform parsing logic, `nj_portals.csv`.
- **Boundaries (what it must not do):**
    - Read-only — no form submission, no account creation.
    - No scraping of restricted or gated content.
    - No outbound writes to the town site.

### Flow (happy path)

1. Parse `$ARGUMENTS` to select platform(s) and optional city filter.
2. Load town list for that platform from `nj_portals.csv`.
3. For each town: fetch meeting-minutes listing.
4. Filter to last 2 years.
5. Download each PDF.
6. Extract text via PyPDF2.
7. Run keyword matcher.
8. On match: save PDF to `cannabis_hits/nj/`, log hit (town, date, label, document type).
9. Print per-platform summary at end.

### Edge cases and failure handling

- **SG Captcha blocks (Kearny):** flagged in CSV, skipped, queued for future Playwright scraper.
- **PDF text-extract fails (image-only):** flagged as needing OCR, not counted as a hit.
- **Site times out:** logged, retried on next run; no run-wide failure.
- **New platform detected:** added to `nj_portals.csv` with detection status, scraper plug-in needed.
- **Keyword in unrelated context (e.g. "medical cannabis" in a health insurance line item):** accepted as a hit; manual review filters later.
- **Town with no public web presence (23 of 375):** marked "no URL" in CSV, skipped.

### Dependencies and risks

- **Dependencies:** `requests`, `PyPDF2`, platform-specific parsing logic in `scrapers/`, `nj_cannabis/data/nj_portals.csv`.
- **Risks:**
    - Site layout changes break scrapers silently (returns 0 PDFs instead of an error).
    - Keyword false positives in unrelated discussions.
    - Date drift if a town's minutes page reflects a different timezone.
    - Cloudflare / WAF blocks if scraping frequency increases.
- **Open questions:**
    - Should we add OCR (Tesseract / AWS Textract) for image-only PDFs?
    - Should we expand to neighboring states (PA, NY) once NJ is solid?
    - Should we run the sweep daily instead of weekly?

### Rollout plan

- **Milestones:**
    - LIVE today: 222 rows across 5 platforms.
    - Next: cover the 126 "unknown" towns by running `deep_sweep.py`.
    - Next: add Playwright-based scraper for SG Captcha sites (Kearny).
    - Future: OCR layer for image-only PDFs.
- **QA / evaluation plan:**
    - After every sweep, manual spot-check of 5 random hits — verify keyword is in substantive discussion (not just a footer/header).
    - Quarterly review of "unknown" CSV — re-run platform detection.
- **Launch checklist:**
    - `nj_portals.csv` up to date.
    - All 5 platform scrapers tested on a known-good town.
    - `cannabis_hits/nj/` writable.
    - Disk space check (PDFs add up).

### Appendix

- **Links:**
    - Scrapers: [scrapers/nj/](../../scrapers/nj/)
    - Skill: [.claude/skills/cannabis-search-nj/SKILL.md](../../.claude/skills/cannabis-search-nj/SKILL.md)
    - Workflow diagram: [docs/workflows/3-cannabis-search-nj.md](../workflows/3-cannabis-search-nj.md)
- **Notes:** Known hits include Stockton Borough (active RFP/RFA), Haddon Township (21 docs), Florence Township (5 docs). Adding a new town only requires updating `nj_portals.csv` with a supported `detected_platform` value.
