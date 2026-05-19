# cannabis-license-tools

A set of four Claude Code skills and their underlying Python pipelines for
researching and pursuing US cannabis retail licenses. NJ-focused with a
parallel VA municipal-minutes scanner.

## The four skills

| Skill | What it does |
|---|---|
| [`rfp-monitor`](.claude/skills/rfp-monitor/SKILL.md) | Daily sweep of ~344 NJ municipal RFP / legal-notice pages for newly posted Class-5 (cannabis retail) license RFPs. Firecrawl batch scraping + GPT-4o-mini classifier with keyword fallback. URL list loads live from a Notion database. |
| [`deep-dive`](.claude/skills/deep-dive/SKILL.md) | Comprehensive single-town research run. Six sub-tasks: ordinance finder, council vote tagger, zoning overlay finder, RFP signal scanner, attorney shortlist with win/loss records, and 4 drafted outreach emails (Town Clerk, Council Member, Zoning Officer, Top Attorney). |
| [`cannabis-search-nj`](.claude/skills/cannabis-search-nj/SKILL.md) | Search NJ municipal meeting minutes for cannabis keywords across AgendaCenter, CivicClerk, Legistar, and custom-PDF platforms. ~210 unique municipalities covered. |
| [`cannabis-search-va`](.claude/skills/cannabis-search-va/SKILL.md) | Same idea for Virginia: AgendaCenter, Legistar, CivicWeb, civic-scraper, and CivicClerk. ~107 entries across all platforms. |

## Project layout

```
.claude/skills/        Claude Code skill definitions (4 skills)
scrapers/              NJ + VA municipal minutes scrapers (cannabis-search-{nj,va})
  nj/                  NJ platform-specific scrapers + portal detection
  va/                  VA platform-specific scrapers
nj_cannabis/           NJ portal CSV + helper scripts for the search skills
  data/                nj_portals.csv (city list), nj_municipalities.csv, etc.
  scripts/             discover_portals.py, parse_municipalities.py, etc.
nj_rfp_monitor/        RFP monitor + deep-dive pipeline (the rfp-monitor + deep-dive skills)
  scripts/
    rfp_monitor.py     Orchestrator (daily scan + --deep mode)
    deep_dive/         Six sub-task modules: ordinance, council_votes, zoning,
                       rfp_signals, attorneys, email_drafter
cannabis_hits/crm/     Cached CRM contacts (council members, officials per town)
```

## Setup

1. Python 3.12+ (project tested on 3.12)
2. `pip install requests openai firecrawl-py python-dotenv` (no requirements.txt yet, install ad-hoc)
3. Copy `.env.example` → `nj_rfp_monitor/.env` and fill in:
   - `FIRECRAWL_API_KEY` (required)
   - `NOTION_TOKEN` (required for `rfp-monitor`)
   - `OPENAI_API_KEY` (optional but strongly recommended — without it everything runs on regex/keyword fallbacks)

## Quick commands

```bash
# Daily RFP sweep (full)
python nj_rfp_monitor/scripts/rfp_monitor.py

# Deep-dive a single town (6 sub-tasks, 3-8 min)
python nj_rfp_monitor/scripts/rfp_monitor.py --deep "Asbury Park"

# Search NJ municipal minutes (all platforms)
python -m scrapers.nj --all

# Search VA municipal minutes (all platforms)
python -m scrapers.va --all
```

## Design principles

- **Every LLM call has a keyword/regex fallback.** Pipelines run with no API key, just at lower quality.
- **Firecrawl batch mode** for scraping — concurrent browsers, polling for completion.
- **SQLite caching everywhere.** Second runs are cheap. Ordinance cache TTL 30d, attorney profiles 30d cross-town, per-town rankings 7d.
- **No invented facts.** Every attorney appearance carries a `source_url`. Cannabis-experience claims verify the attorney's name appears verbatim in the source.
- **Town solicitor always excluded** from attorney recommendations (conflict of interest).
- **Workspace JSON is saved after every sub-task**, so a mid-run crash still produces a usable artifact.

## Skill format

Each skill is a single `SKILL.md` with YAML frontmatter (name, description,
argument-hint). Claude Code auto-loads these when the working directory
contains `.claude/skills/<name>/SKILL.md`. The descriptions are written so
the model picks the right skill from natural-language prompts like "deep dive
Asbury Park" or "scan the priority towns".

## Output locations

Most outputs are gitignored (regenerable, large, or contain run state):
- `nj_rfp_monitor/hits/` — RFP hits, CSV + workspace JSONs
- `nj_cannabis/hits/` — raw PDFs from NJ minutes scrapers
- `cannabis_hits/nj/`, `cannabis_hits/va/` — cannabis-keyword PDF hits
- `*.db` — SQLite state files (snapshots, caches)

Only the canonical CSVs (portal lists, opted-in towns, legal notices, the
enriched CRM) are checked in.
