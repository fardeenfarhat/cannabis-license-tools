# cannabis-license-tools

NJ cannabis retail license intelligence platform. Two components:

- **`dashboard/`** — React + FastAPI web app, deployed on Vercel. Shows RFP hits, town summaries, and deep-dive research cards.
- **`pipeline/`** — Python scraper + research pipeline. Runs locally or on a schedule.

## Repo layout

```
dashboard/              Vercel deployment (frontend + backend)
  src/                  React/TypeScript frontend (Vite)
  api.py                FastAPI backend (Vercel Python serverless)
  vercel.json           Vercel build config
  requirements.txt      Python deps (fastapi, uvicorn)
  data/                 Data files served by the API
    rfp_monitor.db      SQLite — RFP hits table
    first_run_summary.csv  Town-level cannabis status summary
    rfp_hits.csv        RFP hits export
    deep_dives/         Per-town research JSONs (one file per town)

pipeline/               Scraper + research pipeline
  nj_rfp_monitor/       RFP monitor + deep-dive (rfp-monitor + deep-dive skills)
    scripts/
      rfp_monitor.py    Daily RFP sweep orchestrator
      deep_dive/        Six sub-task modules (ordinance, council votes, zoning,
                        rfp signals, attorneys, email drafter)
    data/               nj_opted_in_municipalities.csv, nj_legal_notices.csv
    hits/               RFP hits CSV + deep-dive workspace JSONs (gitignored)
  nj_cannabis/          NJ portal CSV + helper scripts
  scrapers/             NJ + VA municipal minutes scrapers

.claude/skills/         Claude Code skill definitions
  rfp-monitor/          Daily RFP sweep skill
  deep-dive/            Single-town research skill
  cannabis-search-nj/   NJ municipal minutes search skill
  cannabis-search-va/   VA municipal minutes search skill
```

## Dashboard — Vercel deploy

1. Push this repo to GitHub (already done).
2. Import into Vercel. Set **Root Directory** = `dashboard`.
3. Framework: **Vite**. Build command: `npm run build`. Output dir: `dist`.
4. Vercel auto-detects `api.py` and deploys it as a Python serverless function.
5. No environment variables needed — the API reads committed data files.

**Local dev:**
```bash
cd dashboard
pip install fastapi uvicorn
python api.py           # API on http://127.0.0.1:7700

npm install
npm run dev             # Frontend on http://localhost:5173
```

**API endpoints:**

| Endpoint | Returns |
|---|---|
| `GET /api/hits` | All RFP hits from rfp_monitor.db |
| `GET /api/summary` | Town-level summaries from first_run_summary.csv |
| `GET /api/dives` | All deep-dive research cards |
| `GET /api/dives/{slug}` | Single town deep-dive JSON |
| `GET /health` | Health check |

**Refreshing data:** after a pipeline run, copy the updated files into `dashboard/data/` and push:
```bash
copy pipeline\nj_rfp_monitor\data\rfp_monitor.db dashboard\data\rfp_monitor.db
copy pipeline\nj_rfp_monitor\data\first_run_summary.csv dashboard\data\first_run_summary.csv
copy pipeline\nj_rfp_monitor\hits\rfp_hits.csv dashboard\data\rfp_hits.csv
xcopy /E /Y pipeline\nj_rfp_monitor\hits\deep_dives dashboard\data\deep_dives\
git add dashboard/data && git commit -m "refresh dashboard data" && git push
```

## Pipeline — setup

```bash
cd pipeline
pip install requests openai firecrawl-py python-dotenv notion-client
cp nj_rfp_monitor/.env.example nj_rfp_monitor/.env
# fill in FIRECRAWL_API_KEY, NOTION_TOKEN, OPENAI_API_KEY
```

**Quick commands:**
```bash
# Daily RFP sweep (all 344 towns)
c:/python312/python.exe pipeline/nj_rfp_monitor/scripts/rfp_monitor.py

# Deep-dive a single town
c:/python312/python.exe pipeline/nj_rfp_monitor/scripts/rfp_monitor.py --deep "Asbury Park"

# Quick test (1 URL, minimal API credits)
c:/python312/python.exe pipeline/nj_rfp_monitor/scripts/rfp_monitor.py --limit 1

# First-run summary CSV (all towns with any cannabis content)
c:/python312/python.exe pipeline/nj_rfp_monitor/scripts/rfp_monitor.py --first-run
```

## Claude Code skills

Use these phrases in Claude Code to trigger each skill:

| Say… | Skill triggered |
|---|---|
| "run the monitor", "check RFPs", "scan towns" | `rfp-monitor` |
| "deep dive [Town]", "research [Town]" | `deep-dive` |
| "search NJ minutes", "cannabis search NJ" | `cannabis-search-nj` |
| "search VA minutes", "cannabis search VA" | `cannabis-search-va` |

Skills are defined in `.claude/skills/`. Claude Code loads them automatically when this directory is the working directory.
