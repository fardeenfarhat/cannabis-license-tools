# PRD — Deep Dive

### Overview

- **Agent name:** deep-dive
- **One-liner:** Single-command research pipeline that produces a complete per-town workspace — ordinance, council votes, zoning, RFP signals, attorney shortlist, and 4 outreach email drafts — in 3 to 8 minutes.
- **Owner:** Fardeen Farhat (Engineering)
- **Status:** Approved — LIVE

### Problem

- **What problem are we solving?** Once an RFP is detected, the operations team needs 5 to 7 days of manual research to understand the town's ordinance, council disposition, zoning, attorney landscape, and key contacts. That research is the gatekeeper between knowing about an RFP and being able to bid competitively. Manual research is slow, inconsistent, and does not scale across dozens of opted-in towns.
- **Who experiences it and in what context?** Operations + Application teams; outside counsel briefed via the workspace.

### Goals and non-goals

**Goals**

- Produce a complete town workspace in under 10 minutes per town.
- Capture all 6 research dimensions deterministically: ordinance, council, zoning, RFP signals, attorneys, contacts.
- Generate 4 outreach email drafts (Town Clerk, friendliest council member, Zoning Officer, top attorney) ready for review.
- Guarantee no hallucinated legal claims — every attorney entry has a verifiable URL.
- Make the run cheap on cache hits so we can re-run freely.

**Non-goals**

- Not the outreach sender (handled by Correspondence.AI and human review).
- Not the application writer (handled by APP_WRITER).
- Not the FOIA helper (separate skill, phase 4).
- Not a Notion sync layer (blocked on phase 2 setup).

### Users and use cases

- **Primary user(s):** Operations team — they trigger `--deep "Town"` after a monitor hit or manual flag.
- **Secondary user(s):** Application team — picks up the workspace once research is complete; outside counsel briefed from it.
- **Top use cases:**
    - Auto-run after `rfp-monitor` flags a town.
    - Manual research run on a town we are evaluating.
    - Re-run with `--refresh-ordinance` when an ordinance was recently amended.
    - Bulk run across all priority towns to build a portfolio view.

### Success metrics

- **How we will measure success:**
    - Time-to-workspace: ≤10 minutes per town (median).
    - Ordinance-found rate: ≥90% on towns that have adopted an ordinance.
    - Council-vote-captured rate: ≥85% when ordinance has been formally adopted.
    - Email drafts approved by human reviewer with ≤2 round-trips of edits.
    - Attorney `top_picks` correctly identify the right local counsel ≥80% of the time.
    - Zero hallucinated attorney credentials reach `top_picks`.

### Requirements

**Functional requirements**

- Six sub-tasks run in sequence: Ordinance Finder, Council Vote Tagger, Zoning Finder, RFP Signal Scanner, Attorney Finder, Email Drafter.
- Each sub-task is independent and writes to the same workspace dict.
- Workspace JSON is saved to disk after every sub-task.
- All Firecrawl calls share a batch utility (`firecrawl_utils.py`).
- All LLM calls follow the house pattern: gpt-4o-mini + `json_object` + keyword fallback.
- Two-tier SQLite cache: `attorney_profiles` (30d, cross-town) and `town_attorneys` (7d, per-town).
- Email Drafter pulls recipient contacts from `cannabis_crm_enriched.csv`.

**Non-functional requirements**

- **Quality:** No LLM-only attorney entries (verifiable URL required). Verbatim name check before cannabis claims. Town solicitor excluded from `top_picks`.
- **Reliability:** Runs end-to-end with no OpenAI key (keyword fallbacks for every LLM call).
- **Privacy and security:** No PII saved beyond what is public-record (names of officials and attorneys, public-meeting appearances).

### Agent behavior

- **Inputs:** Town name (CLI arg `--deep "Town"`), optional `--refresh-ordinance` flag.
- **Outputs:** Workspace JSON at `nj_rfp_monitor/hits/deep_dives/<slug>.json`; SQLite caches; console summary.
- **Tone and style:** Email drafts use a professional but direct tone. Phase 5 (Correspondence.AI) will voice-match to CEO corpus once that lands.
- **Allowed tools and data sources:** Firecrawl, OpenAI, SQLite cache, local CSVs (CRM, opted-in map, legal notices).
- **Boundaries (what it must not do):**
    - Never sends an email — every draft is status `Draft` and requires human review.
    - Never invents legal facts — attorney appearances must have a `source_url`.
    - Never recommends the town solicitor — surfaced separately with conflict warning.
    - Never overwrites a workspace JSON without keeping the prior version recoverable from cache.

### Flow (happy path)

1. CLI invokes `--deep "Town"`.
2. Load county from `nj_opted_in_municipalities.csv`, initialize workspace dict.
3. **[1/6] Ordinance Finder:** check 30d cache → ecode360 → Municode → broad search → LLM extracts 13 fields.
4. **[2/6] Council Vote Tagger:** search minutes around adoption date, LLM extracts roll-call, cross-ref CRM, compute friendly score.
5. **[3/6] Zoning Finder:** search zoning page + overlay map, LLM extracts confirmed zones.
6. **[4/6] RFP Signal Scanner:** legal notices + bid aggregators + targeted news, LLM classifies signals, cap math.
7. **[5/6] Attorney Finder:** S1 solicitor → S2 planning board → S3 ZBA → S4 council → S5 legal notices → S6 cannabis bonus per attorney → dedupe → score → tier A/B/C.
8. **[6/6] Email Drafter:** generate 4 drafts (Clerk, Council Member, Zoning Officer, Top Attorney).
9. Save final workspace JSON, print summary.

### Edge cases and failure handling

- **Town has not adopted ordinance:** S1 returns `is_prohibition=true`; S2 returns empty; S3-S6 still run.
- **No attorney found:** workspace flags `needs_foia=true`; E4 falls back to template with status `Draft -- needs contact`.
- **No contact email in CRM:** draft generated with `status: "Draft -- needs contact"`, human fills in recipient.
- **OpenAI unavailable:** every sub-task falls back to keyword regex; quality drops but workspace still complete.
- **Firecrawl returns empty:** sub-task logs miss, moves on; workspace JSON still saved.
- **Mid-run crash:** prior sub-task data is preserved on disk (save-after-each-step); partial workspace usable.
- **Multi-vote ordinance (introduced + adopted on different dates):** S2 picks the adoption-vote date.

### Dependencies and risks

- **Dependencies:** Firecrawl API, OpenAI API (recommended), local CSVs (CRM, opted-in map, legal notices), and the 6 sub-task modules in `nj_rfp_monitor/scripts/deep_dive/`.
- **Risks:**
    - Stale CRM data → outdated recipient emails.
    - Attorney appearances missed when minutes are image-only PDFs (no OCR yet).
    - Council votes mis-parsed when a town uses non-standard roll-call formats.
    - Cannabis-experience claims drift if a town's ordinance amends after S6 caches.
- **Open questions:**
    - Should we auto-trigger deep-dive when `rfp-monitor` finds a HIGH hit?
    - What is the CRM refresh schedule once Comet is wired? Monthly?
    - Should `top_picks` include B-tier attorneys when no A-tier exists, or always require A?

### Rollout plan

- **Milestones:**
    - Phase 3 (DONE today): all 6 sub-tasks LIVE.
    - Phase 3.1 (NEXT): wire workspace JSON sync to Notion once Zain delivers DB schema (Phase 2).
    - Phase 3.2: auto-trigger from `rfp-monitor` HIGH hits.
    - Phase 3.3: add Comet fallback for JS-heavy zoning portals.
    - Phase 3.4: auto-draft FOIA letter at end of run (per Abbas's ask).
- **QA / evaluation plan:**
    - Run on 5 known towns (Asbury Park, Vineland, Morristown, Newark, one prohibition town); manually verify all 6 sub-task outputs.
    - Spot-check 1 in 10 attorney `top_picks` for accurate firm + appearance attribution.
    - Email-draft review meeting weekly until voice consistency is solid.
- **Launch checklist:**
    - `.env` populated.
    - CRM CSV refreshed within last 30 days.
    - SQLite migration applied for the 3 cache tables.
    - 1 dry-run on a known town with manual verification.

### Appendix

- **Links:**
    - Orchestrator: [nj_rfp_monitor/scripts/rfp_monitor.py](../../nj_rfp_monitor/scripts/rfp_monitor.py) (`run_deep_dive`)
    - Sub-tasks: [nj_rfp_monitor/scripts/deep_dive/](../../nj_rfp_monitor/scripts/deep_dive/)
    - Skill: [.claude/skills/deep-dive/SKILL.md](../../.claude/skills/deep-dive/SKILL.md)
    - Workflow diagram: [docs/workflows/2-deep-dive.md](../workflows/2-deep-dive.md)
- **Notes:** Tier A ≥70, B 40-69, C <40 on a 0-90 scale. Cannabis experience is a bonus (+15 capped), not a filter. Town solicitor always excluded from picks.
