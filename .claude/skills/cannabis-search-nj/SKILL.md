---
name: cannabis-search-nj
description: Search New Jersey municipal meeting minutes for cannabis keywords across AgendaCenter, CivicClerk, Legistar, and custom-PDF platforms (222 rows / ~210 unique municipalities covered)
argument-hint: "[--agendacenter|--civicclerk|--legistar|--custom-pdf|--all] [--city <name>]"
---

Search **New Jersey** municipal meeting minutes for cannabis-related keywords.

City list loads dynamically from [nj_cannabis/data/nj_portals.csv](../../../nj_cannabis/data/nj_portals.csv) — no hardcoded list, always reflects the latest detection sweep.

## Platform map

| Platform flag | Rows | Notes |
|---|---|---|
| `--agendacenter` | 135 | Largest bucket — Aberdeen, Allenhurst, Alpine, Asbury Park, Barrington, Bay Head, Beachwood, Bedminster, Belmar, Belvidere, Bergenfield, Berkeley Heights, Bernardsville, Bloomsbury, Bradley Beach, Brielle, Byram, Califon, Cedar Grove, Cherry Hill, Chesilhurst, Chesterfield, Clark, Clayton, Clifton, Commercial, Corbin City, Cranford, Deal, Dunellen, East Amwell, East Brunswick, East Greenwich, East Rutherford, Eastampton, Edison, Egg Harbor, Elmer, Englewood, Fair Haven, Fredon, Frelinghuysen, Gloucester, Haddon Heights, Hampton, Hanover, Hawthorne, Hazlet, High Bridge, Ho-Ho-Kus, Holmdel, Howell, Jackson, Kenilworth, Lacey, Laurel Springs, Lavallette, Leonia, Lindenwold, Little Silver, Livingston, Logan, Long Branch, Lopatcong, Lower Alloways Creek, Madison, Magnolia, Mahwah, Manasquan, Mansfield, Mantoloking, Manville, Margate City, Medford Lakes, Mendham, Middletown, Midland Park, Millburn, Montgomery, Montville, Moonachie, Morris, Morris Plains, Neptune, New Providence, North Caldwell, Ocean, Oradell, Palisades Park, Palmyra, Pennsville, Perth Amboy, Pilesgrove, Pittsgrove, Plainsboro, Plumsted, Point Pleasant Beach, Pompton Lakes, Ramsey, Randolph, Ridgefield Park, Ridgewood, Rocky Hill, Roseland, Roxbury, Sea Bright, Sea Girt, Seaside Heights, Seaside Park, South Harrison, Sparta, Stafford, Stratford, Summit, Toms River, Union Beach, Upper Freehold, Upper Saddle River, Wall, Wallington, Walpack, Warren, Wayne, Weehawken, West Long Branch, Westampton, Westfield, Westwood, Wildwood, Wildwood Crest, Wyckoff |
| `--custom-pdf` | 86 | CivicPlus GovOffice/CivicEngage CMS + bare-PDF municipal WordPress/custom sites. Includes: Allamuchy, Allendale, Allentown, Alloway, Barnegat, Barnegat Light, Bayonne, Bethlehem, Bloomingdale, Brigantine, Branchville, Buena Vista, Caldwell, Chatham, Colts Neck, Downe, Dumont, Emerson, Essex Fells, Fair Lawn, Florence, Folsom, Franklin Lakes, Garwood, Glen Ridge, Green, Green Brook, Guttenberg, Hardyston, Harvey Cedars, Hasbrouck Heights, Haworth, Helmetta, Hi-Nella, Hillsdale, Hightstown, Independence, Interlaken, Kearny†, Kinnelon, Liberty, Linwood, Little Egg Harbor, Long Beach, Longport, Lower, Manchester, Marlboro, Maurice River, Millstone, Milltown, Mine Hill, Montague, Mount Arlington, Mountain Lakes, Mountainside, Mullica, New Milford, Northfield, Ogdensburg, Peapack-Gladstone, Pitman, Port Republic, Robbinsville, Saddle River, Sayreville, Shrewsbury, Somers Point, South Hackensack, Stockton, Union, Upper Pittsgrove, Wanaque, West Windsor, Westville, Woodstown, Woolwich |
| `--civicclerk` | 1 | Oceanport Borough (Monmouth) |
| `--legistar` | 1 | Hillside Township (Union) |
| `--civicweb` | 0 | None detected |

† Kearny is classified custom_pdf but blocked by SG Captcha — plain-requests scrape returns 0 PDFs. Needs Playwright to bypass.

## Platform coverage summary

| Status | Rows | Notes |
|---|---|---|
| **Covered by scrapers** | **222** | agendacenter 135 + custom_pdf 64 + civicplus 21 + civicclerk 1 + legistar 1 |
| Platform detected, no scraper | 4 | Laserfiche (Carteret), IQM2 (Lebanon ×2, Teaneck) |
| No URL | 23 | Small boroughs with no public web presence |
| **Still unknown** | **126** | Probed — no platform fingerprint matched; likely custom CMS or no public meeting portal |
| **Total in CSV** | **375** | All NJ municipalities |

## Known hits from previous runs

| Town | County | Platform | Docs | Notes |
|---|---|---|---|---|
| Stockton Borough | Hunterdon | custom_pdf | 9 | Active RFP/RFA process — scoring rubric + 8 addenda through Apr 2026 |
| Haddon Township | Camden | custom_pdf | 21 | Agendas + minutes + planning board, Apr 2025–Jan 2026 |
| Florence Township | Burlington | custom_pdf | 5 | Regular meeting agendas/minutes Nov 2025–Apr 2026 |
| Interlaken Borough | Monmouth | custom_pdf | 2 | 2021 minutes |
| Upper Pittsgrove Township | Salem | custom_pdf | 2 | 2021 minutes |

Files saved to `cannabis_hits/nj/`.

## Keywords searched

`cannabis`, `cannabis retail`, `dispensary`, `marijuana license`

Date window: **2 years** rolling (NJ legalization is more recent than VA).

## Your task

1. Parse `$ARGUMENTS` to determine which platform(s) and city filter to use.
   - If no platform flag given, run `--all`.
   - If the user names a municipality, pass `--city <name>`.

2. Run from `d:\Deployboys\FOIA\`:
   ```
   c:/python312/python.exe -m scrapers.nj $ARGUMENTS
   ```

3. Report back:
   - How many sites searched per platform
   - How many confirmed cannabis documents found
   - Which municipalities had hits, what dates/labels, what document types
   - Where files were saved (`cannabis_hits/nj/`)

## Examples

```bash
# All platforms
c:/python312/python.exe -m scrapers.nj --all

# Just AgendaCenter (135 rows — fastest)
c:/python312/python.exe -m scrapers.nj --agendacenter

# One municipality
c:/python312/python.exe -m scrapers.nj --agendacenter --city "toms river"

# Custom-PDF sites
c:/python312/python.exe -m scrapers.nj --custom-pdf

# CivicClerk – Oceanport
c:/python312/python.exe -m scrapers.nj --civicclerk

# Legistar – Hillside
c:/python312/python.exe -m scrapers.nj --legistar
```

## Platform detection tools

```bash
# Full re-detection sweep (unknown towns)
c:/python312/python.exe -m scrapers.nj.detect_platform --workers 25

# Retry timeouts/errors only
c:/python312/python.exe -m scrapers.nj.retry_timeouts

# Deep sweep — 35 paths per town + link-following (for stubborn unknowns)
c:/python312/python.exe -m scrapers.nj.deep_sweep --workers 20
```

## Adding a new NJ municipality

New towns are picked up automatically from [nj_cannabis/data/nj_portals.csv](../../../nj_cannabis/data/nj_portals.csv) once their `detected_platform` is set to a supported value. No code changes needed — just update the CSV and re-run.
