---
name: cannabis-search-va
description: Search Virginia municipal meeting minutes for cannabis keywords across AgendaCenter, Legistar, CivicWeb, civic-scraper, and CivicClerk platforms
argument-hint: "[--agendacenter|--legistar|--civic-scraper|--civicweb|--civicclerk|--all] [--city <name>]"
---

Search **Virginia** municipal meeting minutes for cannabis-related keywords.

## Platform map

| Platform flag | Count | Cities / Portals |
|---|---|---|
| `--agendacenter` | 39 | **Independent cities:** Waynesboro, Chesapeake, Colonial Heights, Fredericksburg, Norfolk, Lynchburg, Charlottesville, Hopewell, Emporia, Martinsville, Williamsburg, Bristol, Salem, Norton — **Counties:** Middlesex, Cumberland, Madison, Henry, Roanoke, Chesterfield, Shenandoah, Appomattox, King William, Essex, Wythe, Botetourt, Franklin, Pittsylvania, New Kent, Halifax, Mecklenburg, Surry, Warren, Craig, Grayson, Patrick, Wise, Westmoreland — **Regional:** Hampton Roads PDC |
| `--civic-scraper` | 43 | All `va-*.civicplus.com` CivicPlus sites (va-bedford through va-yorkcountyed) |
| `--legistar` | 8 | Richmond, Alexandria, Hampton, Harrisonburg, Albemarle County, Town of Vienna, Brunswick County, Petersburg |
| `--civicweb` | 6 | Williamsburg, Winchester, Newport News, Lancaster County, Lexington, Northampton County |
| `--civicclerk` | 11 | Petersburg, Danville — **Counties:** Amherst, Augusta, Bedford, Frederick, Greene, Isle of Wight, James City, Mathews, Scott |

**Total coverage: ~107 entries across all platforms**

City configs live in [scrapers/va/config.py](../../../scrapers/va/config.py).

## Known issues

- `Essex County` — HTTP 522 (Cloudflare timeout, intermittent)
- `Norton` — connection reset by remote host (intermittent)

## Your task

1. Parse `$ARGUMENTS` to determine which platform(s) and city filter to use.
   - If no platform flag given, run `--all`.
   - If the user names a city, pass `--city <name>`.

2. Run from `d:\Deployboys\FOIA\`:
   ```
   c:/python312/python.exe -m scrapers.va $ARGUMENTS
   ```

3. Report back:
   - How many sites searched
   - How many confirmed cannabis documents found
   - Which cities had hits, what dates, what document types
   - Where files were saved (`cannabis_hits/va/`)

## Examples

```bash
# All platforms
c:/python312/python.exe -m scrapers.va --all

# Just AgendaCenter
c:/python312/python.exe -m scrapers.va --agendacenter

# One city
c:/python312/python.exe -m scrapers.va --agendacenter --city waynesboro

# Legistar – Richmond only
c:/python312/python.exe -m scrapers.va --legistar --city richmond

# civic-scraper – one CivicPlus site
c:/python312/python.exe -m scrapers.va --civic-scraper --city va-fredericksburg

# CivicWeb (requires Playwright)
c:/python312/python.exe -m scrapers.va --civicweb
```

## Adding a new VA city

Edit [scrapers/va/config.py](../../../scrapers/va/config.py) and add a `CityConfig` entry to `CITIES` with the correct `Platform` value, then re-run.
