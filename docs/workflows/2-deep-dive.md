# Deep Dive — Workflow

**What it does:** comprehensive single-town research run. Six sub-tasks in sequence, saving after every one.

**Trigger phrases:** "deep dive Asbury Park", "research Vineland", "build the town workspace"

## Inputs and outputs

| Input | Where it comes from |
|---|---|
| Town name | CLI arg: `--deep "Town Name"` |
| County map | `nj_rfp_monitor/data/nj_opted_in_municipalities.csv` |
| Legal notice URL | `nj_rfp_monitor/data/nj_legal_notices.csv` |
| Officials contacts | `cannabis_hits/crm/cannabis_crm_enriched.csv` |

| Output | Where it lands |
|---|---|
| Workspace JSON | `nj_rfp_monitor/hits/deep_dives/<town_slug>.json` |
| Cached profiles | SQLite tables: `attorney_profiles` (30d), `town_attorneys` (7d), `ordinance_cache` (30d) |

## Flow

```mermaid
flowchart TD
    A[--deep TOWN_NAME] --> B[Load county map, init workspace]
    B --> C[1/6 Ordinance Finder]
    C --> D[2/6 Council Vote Tagger]
    D --> E[3/6 Zoning Overlay Finder]
    E --> F[4/6 RFP Signal Scanner]
    F --> G[5/6 Attorney Finder]
    G --> H[6/6 Email Drafter]
    H --> I[Save final workspace JSON]

    C -. workspace saved .-> Z[(town_slug.json)]
    D -. after each step .-> Z
    E -. so crashes leave .-> Z
    F -. usable data .-> Z
    G -.-> Z
    H -.-> Z
```

## Sub-task breakdown

```mermaid
flowchart LR
    subgraph S5["5/6 Attorney Finder"]
        direction TB
        S5a[S1: Town solicitor] --> S5b[S2: Planning Board minutes]
        S5b --> S5c[S3: ZBA minutes]
        S5c --> S5d[S4: Council minutes]
        S5d --> S5e[S5: Legal notices]
        S5e --> S5f[S6: Cannabis bonus per attorney]
        S5f --> S5g[Score, dedupe, tier A/B/C]
    end
    subgraph S6["6/6 Email Drafter"]
        direction TB
        S6a[E1: Town Clerk - when is the RFP?]
        S6b[E2: Friendliest Council - relationship intro]
        S6c[E3: Zoning Officer - confirm zones + map]
        S6d[E4: Top Attorney - representation inquiry]
    end
    S5 --> S6
```

## Run command

```bash
# Default run (3-8 min, uses caches when available)
python nj_rfp_monitor/scripts/rfp_monitor.py --deep "Asbury Park"

# Force re-search the ordinance (skip cache)
python nj_rfp_monitor/scripts/rfp_monitor.py --deep "Asbury Park" --refresh-ordinance
```

## What ends up in the workspace JSON

| Field | Source sub-task |
|---|---|
| `ordinance` | 13-field structured ordinance (number, adopted date, allowed zones, cap, fees, buffers, hours, tax) |
| `council_votes` | Roster tagged with vote (Yes/No/Abstain) + friendly score |
| `zoning` | Zoning overlay URL + confirmed retail zones |
| `rfp_signals` | RFP-imminent signals (legal notices, agenda mentions, news) |
| `attorneys.top_picks` | Top 1-3 attorneys, scored A (≥70) or B (40-69) |
| `attorneys.town_solicitor` | Town solicitor (excluded from picks - conflict of interest) |
| `draft_emails` | 4 outreach emails ready for human review |

## Key risk controls

| Control | Why it matters |
|---|---|
| No LLM-only attorney entries | Every attorney needs at least one verifiable source URL |
| Verbatim name check before cannabis claim | Attorney's name must appear in source page text or claim is dropped |
| Town solicitor always separated | Excluded from `top_picks` — would be a conflict of interest |
| Saved after every sub-task | A mid-run crash still leaves a usable artifact |
| All LLM calls have regex fallback | Pipeline runs end-to-end with no OpenAI key |
