---
name: deep-dive
description: Run the NJ cannabis deep-dive research pipeline on a single town — finds the cannabis ordinance, tags council voters by friendliness, locates the zoning overlay, scans for RFP signals, builds an attorney shortlist with win/loss records, and drafts 4 outreach emails (Town Clerk, Council Member, Zoning Officer, Top Attorney). Use when the user asks to "deep dive <town>", "research <town>", "build the town workspace", "show me everything on <town>", or "run the full pipeline on <town>".
argument-hint: "<TownName> [--refresh-ordinance]"
---

# NJ Cannabis Deep-Dive Pipeline

Comprehensive single-town research run. Produces a complete town workspace
JSON ready for human review (and Notion sync once Phase 2 lands). Runs six
sub-tasks in sequence, saving after every one so partial failures still leave
a usable artifact.

Project location: [nj_rfp_monitor/scripts/](../../../nj_rfp_monitor/scripts/)
Pipeline orchestrator: [rfp_monitor.py:963](../../../nj_rfp_monitor/scripts/rfp_monitor.py#L963) (`run_deep_dive`)
Sub-task modules: [nj_rfp_monitor/scripts/deep_dive/](../../../nj_rfp_monitor/scripts/deep_dive/)

## Running the deep dive

```bash
c:/python312/python.exe nj_rfp_monitor/scripts/rfp_monitor.py --deep "$ARGUMENTS"
```

| Flag | Meaning |
|------|---------|
| `--deep "Town Name"` | Required. Town to research. Quote multi-word names. |
| `--refresh-ordinance` | Force re-search the ordinance even if cached. Use when the ordinance was recently amended. |

Always use `run_in_background: true` — a full deep dive takes 3–8 minutes
depending on Firecrawl response times and how many sub-tasks hit cache.

Env vars auto-load from [nj_rfp_monitor/.env](../../../nj_rfp_monitor/.env).
Required: `FIRECRAWL_API_KEY`. Optional but strongly recommended: `OPENAI_API_KEY`
(every LLM call has a regex/keyword fallback, so the pipeline runs without it,
quality just drops).

## The six sub-tasks

| # | File | What it produces |
|---|------|------------------|
| 1 | [ordinance.py](../../../nj_rfp_monitor/scripts/deep_dive/ordinance.py) | 13-field structured ordinance: number, adopted date, allowed zones, cap, fees, buffers, hours, tax rate |
| 2 | [council_votes.py](../../../nj_rfp_monitor/scripts/deep_dive/council_votes.py) | Council roster tagged with vote (Yes/No/Abstain) on the adoption ordinance + friendly score |
| 3 | [zoning.py](../../../nj_rfp_monitor/scripts/deep_dive/zoning.py) | Zoning overlay URL + confirmed retail zones |
| 4 | [rfp_signals.py](../../../nj_rfp_monitor/scripts/deep_dive/rfp_signals.py) | Any RFP-imminent signals (legal notices, council agendas mentioning upcoming votes, news) |
| 5 | [attorneys.py](../../../nj_rfp_monitor/scripts/deep_dive/attorneys.py) | Top 1–3 attorneys with appearances at planning board, ZBA, council — scored A/B/C, win/loss tracked |
| 6 | [email_drafter.py](../../../nj_rfp_monitor/scripts/deep_dive/email_drafter.py) | 4 outreach drafts: Town Clerk, friendliest Council Member, Zoning Officer, Top Attorney |

## How the layering works

Every sub-task runs in cascades: cheapest fastest source first, falls through
to the next if it returns nothing. Every LLM call has a keyword/regex fallback
so the pipeline runs end-to-end with no API key (lower quality, but it runs).

Firecrawl handles most scraping. Comet (real browser MCP) is the planned fallback
layer for JS-heavy portals like GIS maps, contact pages that block scrapers,
and form-based searches. Everything caches in SQLite — second runs hit cache,
no Firecrawl credits burned. Cache TTLs:
- Ordinance: 30 days
- Attorney profiles: 30 days (cross-town reusable)
- Per-town attorney rankings: 7 days

## Output: the workspace JSON

Saved to [nj_rfp_monitor/hits/deep_dives/](../../../nj_rfp_monitor/hits/deep_dives/)
as `<town_slug>.json`. Written after every sub-task, so even a mid-run crash
leaves usable data.

Top-level keys:
```
{
  "municipality":   "Asbury Park",
  "county":         "Monmouth",
  "run_date":       "...",
  "ordinance":      { ordinance_number, adopted_date, allowed_zones, cap, ... },
  "council_votes":  [{ name, role, vote, friendly, source_url }],
  "zoning":         { url, description, zones_confirmed },
  "rfp_signals":    [{ url, signal_type, snippet, confidence }],
  "attorneys":      {
    "found": true,
    "attorneys": [...],
    "top_picks": [{ name, firm, email, score, tier, why }],
    "town_solicitor": { name, firm, conflict_note }   // excluded from picks
  },
  "draft_emails":   [
    { to_role, recipient_name, recipient_email, subject, body, status, context_used }
    × 4
  ]
}
```

## CLI output to expect

```
DEEP DIVE -- Asbury Park, NJ (Monmouth County)
[1/6] Ordinance finder...      found Ord. 2022-15 (adopted 2022-04-13)
[2/6] Council vote tagger...   5 members, 4 Yes / 1 Abstain, 2 friendly
[3/6] Zoning finder...         overlay confirmed: B-1, B-2
[4/6] RFP signals...           1 medium signal: cap math says 1 slot open
[5/6] Attorney finder...
  Town solicitor  : Joe Decotiis / Decotiis Fitzpatrick (excluded from picks)
  Attorneys found : 7
    [A:74] John Smith / Cooper Levenson  -- 8 appearance(s), 6W-1L [cannabis]
    [B:52] Jane Roe / Roe LLP            -- 4 appearance(s), 2W-1L
  Top picks       : John Smith, Jane Roe
[6/6] Email drafter...
  E1 Town Clerk   : Mary Smith         mary.smith@town.nj.gov         [Draft]
  E2 Council Mbr  : John Doe           jdoe@town.nj.gov               [Draft]
  E3 Zoning Officer: (no email on file) (no email)                    [Draft -- needs contact]
  E4 Attorney     : John Smith         jsmith@cooperlevenson.com      [Draft]
```

## Key concepts the model should know

- **Friendly score** on a council member: derived from their vote on the cannabis ordinance + tone in meeting minutes. Higher = more receptive to outreach. The drafter uses the highest-friendly member for E2.
- **Attorney tier**: A ≥70, B 40–69, C <40 (0–90 scale). Only A+B make it to `top_picks`. C-tier attorneys are kept in `attorneys` for visibility but not surfaced for outreach.
- **Town solicitor** is always excluded from `top_picks` — there is a conflict of interest, since they work for the town we are applying to. Surfaced separately in `town_solicitor` with a conflict note.
- **Cannabis experience** on an attorney is a bonus signal (+15 pts capped), not a filter. Town-wide track record matters more than cannabis-specific reps.
- **Verbatim name check** runs before any cannabis-rep claim is accepted — the attorney's name must appear in the source page text, or the claim is dropped. This blocks LLM hallucination on legal credentials.
- **Status values on email drafts**: `Draft` (ready for review) | `Draft -- needs contact` (no email on file, human must fill in) | `Draft -- error` (drafter crashed, fallback template returned).
- **Phase 2 (Notion) is blocked** on Zain's setup — for now the workspace lives only as JSON. When Notion lands, the same workspace dict will sync to the town's Notion page.

## Your task

1. Parse `$ARGUMENTS` — the first positional arg is the town name. If multi-word, ensure it is quoted.
2. If user passed `--refresh-ordinance` or said "force refresh the ordinance", pass that flag through.
3. Run the deep dive with `run_in_background: true`. Tell the user the run will take 3–8 minutes.
4. When it completes:
   - Read [nj_rfp_monitor/hits/deep_dives/<slug>.json](../../../nj_rfp_monitor/hits/deep_dives/) for the town.
   - Summarize each sub-task's findings in one or two lines: ordinance found, friendly council count, zoning confirmed, RFP signal count, top attorney picks, email draft statuses.
   - Highlight anything that needs human attention: missing contact emails, FETCH ERRORs, attorneys with no verifiable URL, ordinance not found.
5. If any draft has status `Draft -- needs contact`, list which roles are missing emails so the user knows what to fill in.
6. If `attorneys.needs_foia` is true, mention it — that signals the attorney search returned nothing and we should file a FOIA for board appearance records.
7. Do not re-run sub-tasks individually unless the user asks. The cache means second `--deep` runs are cheap, so a full re-run is usually fine.

## When NOT to use this skill

- For a daily scan across all NJ towns → use `rfp-monitor` instead.
- For just the ordinance on a town → still use deep-dive (sub-tasks are cheap on cache hit) unless the user explicitly says "ordinance only".
- For building the CRM contact list → use `cannabis-crm`.
