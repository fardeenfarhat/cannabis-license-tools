# NJ Cannabis License Acquisition System
### Automated Intelligence Pipeline for Class 5 Retail Licensing

---

## Slide 1 — What This Is

New Jersey opened adult-use cannabis retail (Class 5) to municipalities in 2021.
Each town that opted in sets its own rules: application windows, caps on licenses,
zoning restrictions, and fees. **The opportunity is finding the right town at the
right moment — before the RFP drops publicly.**

This system monitors every active NJ municipality and researches them automatically,
surfacing the towns most likely to open a licensing window in the next 30–90 days.

### The Problem We Solve

| Manual Approach | This System |
|---|---|
| Read 500+ town websites weekly | Automated daily scan |
| Research ordinances by hand | Structured extraction in minutes |
| Cold-call clerks and zoning officers | Pre-drafted, context-aware outreach emails |
| Guess which attorney to hire | Ranked picks based on actual board appearances |
| Miss the RFP window | Signals detected before public announcement |

---

## Slide 2 — How the Pipeline Works

Every town goes through two tiers:

### Tier 1 — Daily RFP Monitor
Runs every day across all monitored NJ towns. Checks legal notice pages, council
agenda portals, and municipal websites for any of these signal types:

- `LIVE_RFP` — application window is open right now
- `ANTICIPATED_WINDOW` — stated future date confirmed
- `RECENT_AWARDS` — licenses already issued (tells us if the cap is hit)
- `ORDINANCE_AMENDMENT` — rules changing soon (major early signal)
- `MORATORIUM` — town paused applications (skip for now)

### Tier 2 — Deep Dive (triggered on high-signal towns)
Six sequential research modules, each building on the last:

```
[1] Ordinance Finder      — Extracts the exact ordinance: number, adoption date,
                            cap, allowed zones, fees, hours, local tax rate

[2] Council Vote Tagger   — Who voted Yes/No on adoption. Scores each member
                            for "friendliness" to target for outreach.

[3] Zoning Finder         — Which zones allow a dispensary. Pulls from municipal
                            code + GIS maps. Flags if FOIA needed.

[4] RFP Signal Checker    — Cross-references NJ CRC license database, town RFP
                            pages, council agendas, and news. Computes cap math:
                            (cap - awarded = open slots).

[5] Attorney Finder       — Scrapes planning board, ZBA, and council minutes to
                            find attorneys with local track records. Scores and
                            tiers them A/B/C. Flags town solicitor as conflict.

[6] Email Drafter         — Writes 4 ready-to-send outreach emails:
                            Town Clerk · Friendliest Council Member ·
                            Zoning Officer · Top-Tier Attorney
```

All results saved to a structured workspace JSON and synced to Notion.

---

## Slide 3 — Key Numbers & What Makes This Different

### Current Coverage
- **Active NJ towns monitored:** All municipalities that adopted a cannabis ordinance
- **Credits per fresh town deep dive:** ~70–120 (Firecrawl API calls)
- **Time to full town profile:** 3–8 minutes end-to-end
- **Emails drafted per town:** 4 (Clerk, Council, Zoning, Attorney)
- **Data stored:** SQLite + Notion, with 7–30 day cache to avoid redundant work

### What No One Else Is Doing

**Cap math.** Most applicants wait for the RFP. We cross-reference the NJ Cannabis
Regulatory Commission's live license database against each town's cap. If a town
has a cap of 3 and 2 licenses are already awarded, we know there's 1 slot before
anyone else files. Towns with **no cap** (like Vineland) are permanently open and
often overlooked.

**Attorney intelligence.** We don't just Google "cannabis attorney NJ." We scrape
actual board meeting minutes and legal notice pages to find attorneys who have won
variances and site plan approvals *in that specific town*. Local track record in
front of local boards is worth far more than statewide cannabis experience alone.

**Amendment signals.** An ordinance amendment (like Vineland's Ord. 2026-17 from
April 2026) is one of the strongest pre-RFP signals. Towns amend their cannabis
chapter when they're about to open or restructure an application window. We catch
these weeks before the press release.

### Live Example — Vineland, NJ (Cumberland County)
| Field | Data |
|---|---|
| Ordinance | 2021-42, adopted July 13 2021 |
| Cap | None — unlimited licenses |
| Awarded so far | 2 (Columbia Care, RE000010) |
| Open slots | Unlimited — perpetually open |
| 2026 Amendment | Ord. 2026-17 (April 2026) — licensing rules updated |
| Council contacts | 5 members, all emails on file |
| Town Solicitor | Michael Malinsky (flagged — conflict of interest) |
| Outreach emails | 4 drafted, ready to personalize |

---

*Built by Deployboys — internal use only*
