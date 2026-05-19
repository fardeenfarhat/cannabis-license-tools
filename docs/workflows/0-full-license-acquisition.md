# License Acquisition Pipeline — Full Workflow

End-to-end view of how a cannabis retail license gets identified, researched, applied for, and won. Spans the daily NJ scanner through application submission, with every agent and data store called out.

## The big picture

```mermaid
flowchart TD
    subgraph DISCOVERY["1 - DISCOVERY"]
        A1[Daily RFP Monitor<br/>344 NJ towns]
        A2[Cannabis Search NJ/VA<br/>minutes keyword sweep]
        A3[Notion RFPs Monitoring DB<br/>URL source of truth]
        A1 --> A4{New hit?}
        A2 --> A4
        A4 -->|Yes| A5[Town flagged for deep-dive]
    end

    subgraph RESEARCH["2 - DEEP RESEARCH"]
        B1[Deep-Dive Pipeline]
        B1 --> B2[Ordinance Finder]
        B1 --> B3[Council Vote Tagger]
        B1 --> B4[Zoning Overlay Finder]
        B1 --> B5[RFP Signal Scanner]
        B1 --> B6[Attorney Finder]
        B1 --> B7[Email Drafter - 4 outreach]
        B8[Sandbox Skill<br/>on-demand research<br/>via Comet browser]
    end

    subgraph WORKSPACE["3 - TOWN WORKSPACE - Notion"]
        C1[Live checklist]
        C2[Sandbox]
        C3[Officials + Attorneys CRM]
        C4[Draft Emails DB]
        C5[FOIA threads]
        C6[Notes]
    end

    subgraph OUTREACH["4 - OUTREACH + CORRESPONDENCE"]
        D1[Correspondence.AI<br/>voice-match to CEO corpus]
        D2[Email reviewer<br/>human-in-the-loop]
        D3[FOIA/OPRA Helper<br/>files + tracks records requests]
    end

    subgraph APPLICATION["5 - APPLICATION"]
        E1[RFP captured by clerk reply<br/>or auto-monitor]
        E2[APP_WRITER<br/>section-by-section draft]
        E3[PersonalDisclosure.AI<br/>applicant intake form]
        E4[Community Deck Builder<br/>edit + add town photos]
    end

    subgraph SPECIALISTS["6 - SPECIALIST AGENTS"]
        F1[Real Estate]
        F2[LOI]
        F3[Lobbying]
        F4[Fundraising]
        F5[Entitlement]
        F6[Partnerships]
        F7[Township Correspondence]
    end

    subgraph ORCHESTRATION["7 - ORCHESTRATION"]
        G1[License Acquisition Orchestrator<br/>routes work between agents]
    end

    A5 --> B1
    B7 --> C4
    B2 --> C1
    B3 --> C3
    B6 --> C3
    B8 --> C2
    C4 --> D1
    D1 --> D2
    D2 -->|sent| C5
    D3 --> C5
    C1 -->|RFP captured ticked| E1
    E1 --> E2
    E2 --> E3
    E2 --> E4
    G1 -.-> RESEARCH
    G1 -.-> OUTREACH
    G1 -.-> APPLICATION
    G1 -.-> SPECIALISTS
```

## What is built today vs what is coming

| Phase | Component | Status |
|---|---|---|
| 1 | Two-deadline RFP scanner (`application_deadline` + `questions_deadline`) | DONE |
| 2 | Town Workspace in Notion | BLOCKED on Notion DB setup (Zain) |
| 3 | Deep-Dive — Ordinance Finder | LIVE |
| 3 | Deep-Dive — Council Vote Tagger | LIVE |
| 3 | Deep-Dive — Zoning Finder | LIVE |
| 3 | Deep-Dive — RFP Signal Scanner | LIVE |
| 3 | Deep-Dive — Attorney Finder | LIVE |
| 3 | Deep-Dive — Email Drafter | LIVE |
| 3 | Sandbox skill (Comet-powered research inside workspace) | PLANNED |
| 3 | Auto-FOIA on deep-dive completion | PLANNED |
| 4 | FOIA/OPRA Helper | NOT STARTED |
| 5 | Correspondence.AI (CEO voice match) | BLOCKED on email corpus |
| 6 | APP_WRITER | NOT STARTED |
| 7 | PersonalDisclosure.AI database + applicant form | NOT STARTED |
| 7 | Community Deck Builder | NOT STARTED |
| 8 | Specialist agent stubs (7 agents) | NOT STARTED |
| 9 | License Acquisition Orchestrator | NOT STARTED |

## End-to-end journey of a single license

```mermaid
sequenceDiagram
    participant Scanner as Daily Scanner
    participant Notion as Notion Workspace
    participant DeepDive as Deep-Dive Pipeline
    participant CRM as CRM + Attorneys
    participant Email as Email Drafter
    participant Corresp as Correspondence.AI
    participant Human as Human Reviewer
    participant Town as Town Officials
    participant FOIA as FOIA Helper
    participant AppWriter as APP_WRITER
    participant Disclosure as PersonalDisclosure.AI

    Scanner->>Notion: New RFP signal hit on Town X
    Notion->>DeepDive: Trigger --deep "Town X"
    DeepDive->>DeepDive: Ordinance, council votes, zoning, signals, attorneys
    DeepDive->>CRM: Populate officials + attorneys CRM
    DeepDive->>Email: Generate 4 outreach drafts
    Email->>Notion: Drafts land in Draft Emails DB
    Notion->>Corresp: Voice-match against CEO corpus
    Corresp->>Human: Reviewed draft surfaced
    Human->>Town: Send email - clerk, council, zoning, attorney
    Town-->>Human: Reply with RFP timeline or zoning map
    DeepDive->>FOIA: Auto-draft FOIA for board appearance records
    FOIA->>Town: Submit FOIA / OPRA request
    Town-->>FOIA: Records released
    Town->>Notion: RFP officially posted
    Notion->>AppWriter: RFP captured checkbox ticked
    AppWriter->>Disclosure: Pull applicant info
    AppWriter->>AppWriter: Draft each application section
    Human->>Town: Submit completed application
```

## The data flow

```mermaid
flowchart LR
    subgraph SOURCES["External sources"]
        S1[NJ municipal sites]
        S2[NJ Notion DBs]
        S3[Firecrawl API]
        S4[OpenAI API]
        S5[Comet Browser MCP]
    end

    subgraph CODE["Pipeline code"]
        P1[rfp_monitor.py]
        P2[scrapers/]
        P3[deep_dive/]
    end

    subgraph STORE["Local stores"]
        L1[(SQLite caches<br/>page snapshots<br/>attorney profiles<br/>ordinance cache)]
        L2[CSV: portals, towns,<br/>opted-in, legal notices]
        L3[Workspace JSON<br/>per town]
        L4[CRM CSV]
    end

    subgraph NOTION["Notion - source of truth"]
        N1[RFPs Monitoring DB]
        N2[Town Workspace pages]
        N3[Draft Emails DB]
        N4[FOIA Threads DB]
    end

    S1 --> S3
    S3 --> P1
    S3 --> P3
    S5 -.-> P3
    S4 --> P1
    S4 --> P3
    N1 --> P1
    P2 --> L2
    P1 --> L1
    P3 --> L1
    P3 --> L3
    P3 --> L4
    P3 --> N2
    P3 --> N3
    L3 -.-> N2
```

## The agent layer (who does what)

| Agent / Skill | Role | When it fires | Status |
|---|---|---|---|
| **rfp-monitor** | Daily watcher across 344 NJ towns | Scheduled / on demand | LIVE |
| **cannabis-search-nj** | Keyword sweep of NJ municipal minutes | On demand or weekly | LIVE |
| **cannabis-search-va** | Same for Virginia | On demand | LIVE |
| **deep-dive** | Full single-town research (6 sub-tasks) | When a town hits or is manually flagged | LIVE |
| **Sandbox skill** | Ad-hoc research via Comet inside a workspace | Human asks a follow-up question in the town's sandbox | PLANNED |
| **Correspondence.AI** | Rewrites every outbound email in CEO's voice | Before any email is reviewed/sent | BLOCKED on corpus |
| **FOIA/OPRA Helper** | Drafts + submits records requests, tracks batches | Auto at deep-dive end, or on demand | NOT STARTED |
| **APP_WRITER** | Section-by-section application drafter | When RFP captured checkbox is ticked | NOT STARTED |
| **PersonalDisclosure.AI** | Applicant intake form + disclosure DB | Applicant clicks the login link | NOT STARTED |
| **Community Deck Builder** | Editable pitch deck per town | When prepping for council presentation | NOT STARTED |
| **Real Estate / LOI / Lobbying / Fundraising / Entitlement / Partnerships / Township Correspondence** | Domain specialists | Routed by orchestrator | NOT STARTED |
| **License Acquisition Orchestrator** | Routes work between agents based on workspace state | Always running | NOT STARTED |

## Cross-cutting concerns

```mermaid
flowchart TD
    subgraph CROSS["Cross-cutting layers"]
        X1[Correspondence.AI<br/>every outbound email passes through]
        X2[FOIA/OPRA Helper<br/>called whenever records are needed]
        X3[Orchestrator<br/>routes work, tracks state]
    end

    subgraph AGENTS["Agent calls"]
        Y1[Deep-Dive]
        Y2[APP_WRITER]
        Y3[Specialists]
    end

    Y1 -->|writes email drafts| X1
    Y2 -->|sends applicant follow-ups| X1
    Y3 -->|sends partner outreach| X1
    Y1 -->|missing records| X2
    Y2 -->|needs background docs| X2
    X3 -.->|decides next step| AGENTS
```

## Risk controls baked into the pipeline

| Control | Where it applies | Why |
|---|---|---|
| Every LLM call has a regex / keyword fallback | All extraction steps | Pipeline runs end-to-end with no API key (degraded quality, but no hard dependency) |
| Every attorney needs at least one verifiable URL | Attorney finder | Prevents LLM hallucination of legal credentials |
| Verbatim name check before cannabis claim | Attorney finder | Attorney name must appear in source text |
| Town solicitor always excluded from recommendations | Attorney finder | Conflict of interest with town we are applying to |
| Workspace JSON saved after every sub-task | Deep-dive | A crash mid-run still leaves a usable artifact |
| All Notion writes are idempotent | Notion sync layer (when built) | Re-runs do not duplicate rows |
| FOIA letters are dry-run by default | FOIA helper (when built) | Human reviews before real submission |
| No automatic email sending | Correspondence.AI (when built) | Human-in-the-loop on every outbound message |

## Phase dependency graph

```mermaid
flowchart TD
    P1[Phase 1<br/>Two-deadline scanner<br/>DONE] --> P2[Phase 2<br/>Town Workspace<br/>BLOCKED on Zain]
    P2 --> P3[Phase 3<br/>Deep-Dive<br/>LIVE]
    P3 --> P4[Phase 4<br/>FOIA Helper]
    P3 --> P5[Phase 5<br/>Correspondence.AI<br/>BLOCKED on corpus]
    P3 --> P6[Phase 6<br/>APP_WRITER]
    P6 --> P7[Phase 7<br/>PersonalDisclosure.AI]
    P3 --> P8[Phase 8<br/>Specialist stubs]
    P3 --> P9[Phase 9<br/>Orchestrator]
    P4 --> P9
    P6 --> P9
    P7 --> P9
    P8 --> P9

    style P1 fill:#90ee90
    style P3 fill:#90ee90
    style P2 fill:#fff3b0
    style P5 fill:#fff3b0
    style P4 fill:#f4cccc
    style P6 fill:#f4cccc
    style P7 fill:#f4cccc
    style P8 fill:#f4cccc
    style P9 fill:#f4cccc
```

## Glossary

| Term | Meaning |
|---|---|
| **Class 5** | Adult-use cannabis retailer license (the target) |
| **Opt-in town** | Municipality that has passed an ordinance allowing cannabis retail. Not the same as having an active RFP. |
| **Moratorium** | Town has frozen new applications until a date. Tracked as a signal. |
| **RFP** | Request for Proposals — the formal application window. |
| **OPRA** | Open Public Records Act (NJ's FOIA equivalent) |
| **Friendly score** | Per-council-member metric: how receptive they are to cannabis retail. Drives Email Drafter's E2 recipient pick. |
| **Tier A/B/C** (attorneys) | A ≥70, B 40-69, C <40 on 0-90 scale. Only A+B reach `top_picks`. |
| **Verbatim check** | Attorney name must appear in source page text before any cannabis claim is accepted. |
| **Workspace** | Notion page per town with checklist, sandbox, CRM, emails, FOIA threads, notes. |

## What success looks like

1. Daily scanner spots a new RFP signal in **Town X**.
2. Town X gets a Notion workspace page auto-created.
3. Deep-dive runs in 3-8 minutes, fills out ordinance, council, zoning, attorneys, and queues 4 outreach emails.
4. Correspondence.AI voice-matches every email; human reviewer approves; emails go out.
5. FOIA Helper auto-files OPRA requests for board appearance records and zoning maps.
6. Town Clerk replies with RFP timeline. RFP captured checkbox ticked.
7. APP_WRITER drafts every section of the application using past examples.
8. Applicant fills PersonalDisclosure.AI form via a simple login link.
9. Community deck gets built with photos from a town visit, edited by the team.
10. Application submitted. Orchestrator advances workspace to "Submitted" state.
11. Subsequent town correspondence + lobbying + entitlement work routes through specialist agents.
