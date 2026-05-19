# Cannabis Search VA — Workflow

**What it does:** keyword-search ~107 Virginia municipal meeting-minutes portals for cannabis mentions.

**Trigger phrases:** "search VA minutes", "scan Virginia agendas", "find cannabis discussions in VA"

## Inputs and outputs

| Input | Where it comes from |
|---|---|
| City configs | `scrapers/va/config.py` |
| Keywords | Hardcoded: `cannabis`, `cannabis retail`, `dispensary`, `marijuana license` |

| Output | Where it lands |
|---|---|
| Matching PDFs | `cannabis_hits/va/` |
| Hit log | Console output |

## Platform coverage

| Platform | Count | Notable entries |
|---|---|---|
| `--agendacenter` | 39 | Norfolk, Chesapeake, Charlottesville, Lynchburg, Fredericksburg, Williamsburg, Bristol, plus 24 counties |
| `--civic-scraper` | 43 | All `va-*.civicplus.com` CivicPlus sites (Bedford through York County) |
| `--legistar` | 8 | Richmond, Alexandria, Hampton, Harrisonburg, Albemarle County, Vienna, Brunswick County, Petersburg |
| `--civicweb` | 6 | Williamsburg, Winchester, Newport News, Lancaster County, Lexington, Northampton County |
| `--civicclerk` | 11 | Petersburg, Danville, plus 9 counties (Amherst, Augusta, Bedford, Frederick, Greene, Isle of Wight, James City, Mathews, Scott) |

**Total coverage:** ~107 entries across 5 platforms.

## Flow

```mermaid
flowchart TD
    A[Parse $ARGUMENTS] --> B{Platform flag?}
    B -->|--agendacenter| C1[39 AgendaCenter cities/counties]
    B -->|--civic-scraper| C2[43 CivicPlus va-* sites]
    B -->|--legistar| C3[8 Legistar entries]
    B -->|--civicweb| C4[6 CivicWeb entries]
    B -->|--civicclerk| C5[11 CivicClerk entries]
    B -->|--all| C6[All 107 entries]
    C1 --> D[For each city/county]
    C2 --> D
    C3 --> D
    C4 --> D
    C5 --> D
    C6 --> D
    D --> E[Fetch agenda/minutes list]
    E --> F[Download each PDF]
    F --> G[Extract text]
    G --> H{Keyword<br/>matches?}
    H -->|No| I[Skip]
    H -->|Yes| J[Save PDF to cannabis_hits/va/]
    J --> K[Log hit]
    I --> L{More entries?}
    K --> L
    L -->|Yes| D
    L -->|No| M[Print summary by platform]
```

## Run commands

```bash
# All platforms
python -m scrapers.va --all

# Just AgendaCenter
python -m scrapers.va --agendacenter

# Single city
python -m scrapers.va --legistar --city "richmond"

# CivicPlus va-* sites
python -m scrapers.va --civic-scraper
```

## Known issues

| Site | Issue |
|---|---|
| Essex County | HTTP 522 (intermittent Cloudflare timeout) |
| Norton | Connection reset by remote host (intermittent) |

## Differences vs NJ

| Aspect | NJ | VA |
|---|---|---|
| Date window | 2 years | Longer (VA legalization is older) |
| Total coverage | 222 rows | ~107 entries |
| Largest platform | AgendaCenter (135) | civic-scraper (43) |
| Custom-PDF sites | 86 | Folded into civic-scraper/civicplus |
| Platform detection tools | Yes (`detect_platform`, `deep_sweep`) | No |
