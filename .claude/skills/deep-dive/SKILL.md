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
- **Notion sync** runs automatically after the deep dive completes — see "Pushing to Notion" section below.

## Notion DB IDs

Read all Notion database IDs from the config file before starting:

```
Read: .claude/notion_config.md
```

Use the IDs from that file for every Notion API call. Do not hardcode IDs here — the config file is the single source of truth.

## Your task

1. Parse `$ARGUMENTS` — the first positional arg is the town name. If multi-word, ensure it is quoted.
2. If user passed `--refresh-ordinance` or said "force refresh the ordinance", pass that flag through.
3. **Run connection check** (see section below) before starting.
4. Run the deep dive with `run_in_background: true`. Tell the user the run will take 3–8 minutes.
5. When it completes:
   - Read [nj_rfp_monitor/hits/deep_dives/<slug>.json](../../../nj_rfp_monitor/hits/deep_dives/) for the town.
   - Summarize each sub-task's findings in one or two lines: ordinance found, friendly council count, zoning confirmed, RFP signal count, top attorney picks, email draft statuses.
   - Highlight anything that needs human attention: missing contact emails, FETCH ERRORs, attorneys with no verifiable URL, ordinance not found.
6. If any draft has status `Draft -- needs contact`, list which roles are missing emails.
7. If `attorneys.needs_foia` is true, mention it.
8. Do not re-run sub-tasks individually unless the user asks.
9. **Push findings to Notion** (see section below). Verify each write.

## Connection check (run before every deep dive)

Use `mcp__notion__API-retrieve-a-database` on all DBs in parallel.

**Check 1 — RFP Hits DB:**
- Call `mcp__notion__API-retrieve-a-database` with ID `34f61279-b083-8054-9aaf-ce23adfb2a94`.
- If 404 → "RFP Hits DB not accessible — check integration permissions."
- If OK → confirm title is "RFP Hits".

**Check 2 — Sub-DB relations point to RFP Hits DB:**
- Retrieve Draft Emails, Officials, Attorneys, FOIA Requests in parallel (hardcoded IDs in table above).
- For each, check the `Town` property → `relation.database_id` should be `34f61279-b083-8054-9aaf-ce23adfb2a94`.
- If any still show `34c61279-b083-8097-9d84-fed2a9c31570` (Monitoring DB) → flag: "⚠️ [DB name] Town relation not yet re-pointed — Zain needs to update it."

**Report format:**
```
Notion connection check:
  ✅ RFP Hits DB         — accessible
  ✅ Draft Emails        — Town → RFP Hits DB ✓
  ✅ Officials           — Town → RFP Hits DB ✓
  ✅ Attorneys           — Town → RFP Hits DB ✓
  ✅ FOIA Requests       — Town → RFP Hits DB ✓
```
Proceed even if sub-DB relations aren't re-pointed yet — just skip those write steps and warn the user.

## Pushing to Notion after deep dive

Run these steps in order. Verify each write before moving to the next.

### Stage 1 — RFP Hits DB row (find or create)

Search for an existing row: `mcp__notion__API-post-search` with query `"<municipality>"`, filter `{ "property": "object", "value": "page" }`.
- If found in RFP Hits DB → patch with `mcp__notion__API-patch-page`.
- If not found → create with `mcp__notion__API-post-page`.

RFP Hits DB ID: `34f61279-b083-8054-9aaf-ce23adfb2a94`

> **Schema notes (must match exactly):**
> - Title field is `TOWN NAME` (not "Name")
> - `Status` is type `status` — use `{ "status": { "name": "..." } }` not `select`
> - `Ordinance URL` is `files` type — use the external file format below (not a plain URL field)

Properties to set:
```json
{
  "parent": { "database_id": "34f61279-b083-8054-9aaf-ce23adfb2a94" },
  "properties": {
    "TOWN NAME":        { "title": [{ "text": { "content": "<municipality>" } }] },
    "Status":           { "status": { "name": "<'Monitoring' if prohibition, else 'RFP Anticipated'>" } },
    "County":           { "rich_text": [{ "text": { "content": "<county>" } }] },
    "Ordinance URL":    { "files": [{ "type": "external", "name": "Ordinance", "external": { "url": "<ordinance.url>" } }] },
    "Ordinance Adopted":{ "date": { "start": "<ordinance.adopted_date as YYYY-MM-DD — only if cleanly parseable>" } }
  }
}
```
Only include `Ordinance URL` if `workspace.ordinance.found == true`.

**Verify:** retrieve the page by ID and confirm Name + Status are correct. Report: "✅ Stage 1 — RFP Hits row created/updated for [Town]" or "❌ Stage 1 failed: [error]".

### Stage 2 — Draft Email rows

Skip if the Draft Emails Town relation still points to the Monitoring DB (from connection check).

For each item in `workspace.draft_emails`, create a row in Draft Emails DB (`36061279-b083-80e0-af19-f5c5176da724`):
```json
{
  "parent": { "database_id": "36061279-b083-80e0-af19-f5c5176da724" },
  "properties": {
    "Title":           { "title": [{ "text": { "content": "<subject>" } }] },
    "Town":            { "relation": [{ "id": "<RFP Hits row page ID from Stage 1>" }] },
    "Recipient Name":  { "rich_text": [{ "text": { "content": "<recipient_name>" } }] },
    "Recipient Role":  { "select": { "name": "<to_role: Clerk|Council Member|Zoning Officer|Attorney>" } },
    "Recipient Email": { "email": "<recipient_email — omit property if empty>" },
    "Subject":         { "rich_text": [{ "text": { "content": "<subject>" } }] },
    "Body":            { "rich_text": [{ "text": { "content": "<body, max 2000 chars>" } }] },
    "Status":          { "select": { "name": "Draft" } },
    "Drafted By":      { "select": { "name": "SHOW_ME_THE_RFP" } }
  }
}
```

**Verify:** after creating all 4 drafts, query Draft Emails DB for rows where Town = [RFP Hits row ID] and confirm count = 4. Report: "✅ Stage 2 — 4 draft emails created" or "❌ Stage 2 — only N/4 created: [errors]".

### Stage 3 — Officials rows

Skip if the Officials Town relation still points to the Monitoring DB.

For each member in `workspace.council_votes.members`, create a row in Officials DB (`36061279-b083-80e4-9059-e280e79b57c6`):
```json
{
  "parent": { "database_id": "36061279-b083-80e4-9059-e280e79b57c6" },
  "properties": {
    "Name":                      { "title": [{ "text": { "content": "<member.name>" } }] },
    "Town":                      { "relation": [{ "id": "<RFP Hits row page ID>" }] },
    "Role":                      { "select": { "name": "<member.current_title — map to: Mayor|Deputy Mayor|Council Member|Clerk|Zoning Officer>" } },
    "Vote on Cannabis Ordinance":{ "select": { "name": "<member.vote — map to: Yes|No|Abstain|Absent|Not Voted>" } },
    "Friendly":                  { "checkbox": "<true if member.friendly else false>" },
    "Email":                     { "email": "<member.email — omit if empty>" },
    "Notes":                     { "rich_text": [{ "text": { "content": "<member.source_url or ''>" } }] }
  }
}
```

**Verify:** query Officials DB for rows where Town = [RFP Hits row ID], confirm count matches `workspace.council_votes.members` length. Report: "✅ Stage 3 — N officials logged" or "❌ Stage 3 failed."

### Stage 4 — Attorney rows

Skip if the Attorneys Town relation still points to the Monitoring DB.

For each attorney in `workspace.attorneys.attorneys` (top 5 only — tier A+B):
```json
{
  "parent": { "database_id": "36061279-b083-800a-88d0-f8c61eb17494" },
  "properties": {
    "Name":               { "title": [{ "text": { "content": "<attorney.name>" } }] },
    "Towns Active In":    { "relation": [{ "id": "<RFP Hits row page ID>" }] },
    "Firm":               { "rich_text": [{ "text": { "content": "<attorney.firm>" } }] },
    "Email":              { "email": "<attorney.email — omit if empty>" },
    "Total Cases Tracked":{ "number": <attorney.appearances length> },
    "Wins":               { "number": <attorney.this_town_wins> },
    "Losses":             { "number": <attorney.this_town_losses> },
    "Practice Areas":     { "multi_select": [{ "name": "Cannabis" }, { "name": "Land Use" }] },
    "Source URLs":        { "rich_text": [{ "text": { "content": "<first appearance URL if available>" } }] }
  }
}
```

**Verify:** query Attorneys DB for rows linked to the RFP Hits row. Report: "✅ Stage 4 — N attorneys logged" or "❌ Stage 4 failed."

### Final summary to user

```
Notion sync complete for [Town Name]:
  ✅ Stage 1 — RFP Hits row: created/updated (Status: RFP Anticipated)
  ✅ Stage 2 — 4 draft emails created in Draft Emails DB
  ✅ Stage 3 — N officials logged (M friendly contacts)
  ✅ Stage 4 — N attorneys logged (top pick: [name])
```

If any stage failed, tell the user exactly what failed and what they need to do (e.g. "Zain needs to re-point the Officials Town relation to the RFP Hits DB").

## When NOT to use this skill

- For a daily scan across all NJ towns → use `rfp-monitor` instead.
- For just the ordinance on a town → still use deep-dive (sub-tasks are cheap on cache hit) unless the user explicitly says "ordinance only".
- For building the CRM contact list → use `cannabis-crm`.
