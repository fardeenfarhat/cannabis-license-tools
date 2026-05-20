# PRD — Cannabis Search VA

### Overview

- **Agent name:** cannabis-search-va
- **One-liner:** Sister skill to `cannabis-search-nj` — keyword-search ~107 Virginia municipal meeting-minutes portals for cannabis mentions across AgendaCenter, Legistar, CivicWeb, civic-scraper, and CivicClerk platforms.
- **Owner:** Fardeen Farhat (Engineering)
- **Status:** Approved — LIVE

### Problem

- **What problem are we solving?** Virginia's cannabis regulatory framework is on a different timeline than New Jersey — adult-use sales are still pending but municipal discussions are active. We need the same early-warning signal in VA that we have in NJ, so when the state opens commercial licensing the team already knows which towns are receptive.
- **Who experiences it and in what context?** Business-development team — they monitor VA for the moment regulations unlock, and they want a backlog of town-level intel ready.

### Goals and non-goals

**Goals**

- Sweep ~107 VA municipal portals (independent cities + counties + regional bodies) for cannabis keyword mentions.
- Cover 5 platforms: AgendaCenter, civic-scraper (CivicPlus), Legistar, CivicWeb, CivicClerk.
- Surface matching PDFs with city/county, date, document type.
- Stay polite — VA sites tend to have stricter rate limits than NJ.

**Non-goals**

- Not an RFP detector (VA has no statewide RFP equivalent yet).
- Not for filing or outreach.
- Not for non-VA states (separate skills).
- Not for the regional PDCs other than what is already in the AgendaCenter list (Hampton Roads PDC).

### Users and use cases

- **Primary user(s):** Business development scouting Virginia for future expansion.
- **Secondary user(s):** Legal team tracking how counties versus independent cities frame cannabis.
- **Top use cases:**
    - Quarterly sweep across all platforms (`--all`).
    - Targeted lookup on a specific city (`--legistar --city "richmond"`).
    - Single-platform run when one platform has new data.
    - Reading the Norfolk/Chesapeake/Richmond hits to brief on regulatory tone.

### Success metrics

- **How we will measure success:**
    - Coverage: 107 entries across 5 platforms remain reachable.
    - Hit precision: ≥80% of flagged PDFs substantively mention cannabis (not just keyword noise).
    - Full sweep completes: ≤90 minutes.
    - Zero false alarms triggering outreach from VA hits (this skill is intel-only, not action).

### Requirements

**Functional requirements**

- Per-platform scrapers reused from the NJ pipeline.
- City/county configs live in `scrapers/va/config.py`.
- Keyword matching on extracted PDF text against the same 4 keywords as NJ.
- Save matching PDFs to `cannabis_hits/va/`.
- Independent-city vs county distinction preserved in logs (VA has both).

**Non-functional requirements**

- **Quality:** Keyword false-positive rate <20%.
- **Reliability:** Site failures isolated. Essex County (HTTP 522) and Norton (connection reset) are known intermittent — must not crash the sweep.
- **Privacy and security:** Public-record content only. Polite scraping with delays.

### Agent behavior

- **Inputs:** Platform flag (`--agendacenter`, `--civic-scraper`, `--legistar`, `--civicweb`, `--civicclerk`, or `--all`), optional `--city <name>`.
- **Outputs:** PDFs saved to `cannabis_hits/va/`; console summary by platform.
- **Tone and style:** Operational logs.
- **Allowed tools and data sources:** `requests`, `PyPDF2`, per-platform parsing logic, `scrapers/va/config.py`.
- **Boundaries (what it must not do):**
    - Read-only.
    - No outbound writes.
    - No automated outreach off of VA hits (intel only).

### Flow (happy path)

1. Parse `$ARGUMENTS` for platform + optional city filter.
2. Load entry list from `scrapers/va/config.py`.
3. For each entry: fetch agenda/minutes listing.
4. Download each PDF.
5. Extract text via PyPDF2.
6. Run keyword matcher.
7. On match: save PDF to `cannabis_hits/va/`, log hit (entity, date, document type).
8. Print summary segmented by platform.

### Edge cases and failure handling

- **Essex County HTTP 522 (Cloudflare timeout):** known intermittent — logged, retry next run.
- **Norton connection reset:** same as above.
- **Image-only PDFs:** flagged as needing OCR, not counted.
- **Independent city vs county collision (same name):** disambiguated via the config entry, not the keyword match.
- **Civic-scraper CivicPlus va-* subdomain failures:** isolated per subdomain.

### Dependencies and risks

- **Dependencies:** `requests`, `PyPDF2`, platform parsers in `scrapers/`, `scrapers/va/config.py`.
- **Risks:**
    - VA regulatory landscape is fluid — keywords may need to expand as new license classes are defined.
    - Lower hit volume than NJ → harder to know if the scraper is working or just no one is talking.
    - Independent city / county / town distinctions differ from NJ — config must stay accurate.
- **Open questions:**
    - Should we expand keywords (e.g. "marijuana commercial," "cannabis retail license") as VA's framework matures?
    - Should we wire VA hits into a separate alert channel, or roll up with NJ?
    - Do we extend to the remaining 200+ VA towns and counties not yet onboarded?

### Rollout plan

- **Milestones:**
    - LIVE today: 107 entries.
    - Next: expand keyword list once VA finalizes adult-use commercial framework.
    - Future: add VA to the daily monitor cadence once licensing opens.
- **QA / evaluation plan:**
    - Quarterly sweep + manual review of any new hits.
    - Annual review of `scrapers/va/config.py` for site changes.
- **Launch checklist:**
    - `scrapers/va/config.py` up to date.
    - All 5 platform parsers tested.
    - `cannabis_hits/va/` writable.
    - Known intermittent sites (Essex County, Norton) flagged in logs.

### Appendix

- **Links:**
    - Scrapers: [scrapers/va/](../../scrapers/va/)
    - Skill: [.claude/skills/cannabis-search-va/SKILL.md](../../.claude/skills/cannabis-search-va/SKILL.md)
    - Workflow diagram: [docs/workflows/4-cannabis-search-va.md](../workflows/4-cannabis-search-va.md)
- **Notes:** Total coverage is ~107 entries: AgendaCenter 39, civic-scraper 43, Legistar 8, CivicWeb 6, CivicClerk 11. Differs from NJ in that VA has a strong independent-city tradition alongside counties — both are represented.
