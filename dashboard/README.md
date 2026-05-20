# License Watch Dashboard

React + FastAPI web app showing NJ cannabis RFP hits, town summaries, and deep-dive research cards. Deployed on Vercel.

## Deploy to Vercel

1. Import the repo into Vercel.
2. Set **Root Directory** = `dashboard`.
3. Framework preset: **Vite**. Build command: `npm run build`. Output directory: `dist`.
4. Vercel auto-detects `api.py` and deploys it as a Python serverless function.
5. No environment variables required.

## Local development

```bash
# Backend (port 7700)
pip install fastapi uvicorn
python api.py

# Frontend (port 5173)
npm install
npm run dev
```

The frontend proxies `/api/*` to the backend in dev via Vite config.

## Project structure

```
api.py              FastAPI backend — serves data from ./data/
vercel.json         Vercel build + routing config
requirements.txt    Python deps
src/                React/TypeScript frontend
  App.tsx           Main app — routing and layout
  components/       UI components (cards, tables, filters)
  api/              HTTP client functions
  types/            TypeScript interfaces
data/               Data files (committed, served read-only)
  rfp_monitor.db    SQLite — rfp_hits table
  first_run_summary.csv  Town-level cannabis status
  rfp_hits.csv      RFP hits export
  deep_dives/       Per-town research JSONs
```

## API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/hits` | All RFP hits ordered by first_seen |
| `GET /api/summary` | Town summaries from first_run_summary.csv |
| `GET /api/dives` | All deep-dive research cards (normalized) |
| `GET /api/dives/{slug}` | Single town JSON (raw) |
| `GET /health` | Health check — DB and dives dir status |

## Refreshing data

After running the pipeline scraper, copy updated files here and push to trigger a Vercel redeploy:

```bash
# From repo root (Windows)
copy pipeline\nj_rfp_monitor\data\rfp_monitor.db dashboard\data\rfp_monitor.db
copy pipeline\nj_rfp_monitor\data\first_run_summary.csv dashboard\data\first_run_summary.csv
copy pipeline\nj_rfp_monitor\hits\rfp_hits.csv dashboard\data\rfp_hits.csv
xcopy /E /Y pipeline\nj_rfp_monitor\hits\deep_dives dashboard\data\deep_dives\

git add dashboard/data
git commit -m "refresh dashboard data"
git push
```

Vercel redeploys automatically on push. New data is live within ~1 minute.
