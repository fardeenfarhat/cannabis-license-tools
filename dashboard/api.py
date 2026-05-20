"""License Watch API — serves SQLite rfp_hits + deep_dive JSONs."""
import json
import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

_DATA      = Path(__file__).parent / "data"
DB_PATH    = _DATA / "rfp_monitor.db"
DIVES_DIR  = _DATA / "deep_dives"
SUMMARY_CSV= _DATA / "first_run_summary.csv"

app = FastAPI(title="License Watch API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/hits")
def get_hits():
    if not DB_PATH.exists():
        return []
    with _db() as conn:
        rows = conn.execute("SELECT * FROM rfp_hits ORDER BY first_seen DESC").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/summary")
def get_summary():
    if not SUMMARY_CSV.exists():
        return []
    import csv
    rows = []
    with open(SUMMARY_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "town":    row.get("town", ""),
                "date":    row.get("date") or row.get("key_date") or None,
                "summary": row.get("summary", ""),
            })
    return rows


def _normalize_dive(fp: Path, data: dict) -> dict:
    """Normalize raw JSON workspace to the shape TypeScript types expect."""
    # --- ordinance ---
    ord_raw = data.get("ordinance") or {}
    ord_norm = {
        "found":                  ord_raw.get("found", False),
        "is_prohibition":         ord_raw.get("is_prohibition", False),
        "url":                    ord_raw.get("url", ""),
        "title":                  ord_raw.get("title", ""),
        "ordinance_number":       ord_raw.get("ordinance_number", ""),
        "adopted_date":           ord_raw.get("adopted_date", ""),
        "allowed_zones":          ord_raw.get("allowed_zones") if isinstance(ord_raw.get("allowed_zones"), list) else [],
        "cap":                    str(ord_raw.get("cap", "") or ""),
        "application_fee":        str(ord_raw.get("application_fee", "") or ""),
        "annual_fee":             str(ord_raw.get("annual_fee", "") or ""),
        "buffer_schools":         str(ord_raw.get("buffer_schools") or ord_raw.get("buffers", "") or ""),
        "buffer_houses_of_worship": str(ord_raw.get("buffer_houses_of_worship", "") or ""),
        "hours":                  str(ord_raw.get("hours", "") or ""),
        "tax_rate":               str(ord_raw.get("tax_rate") or ord_raw.get("local_tax", "") or ""),
    }

    # --- council_votes ---
    cv_raw = data.get("council_votes") or {}
    if isinstance(cv_raw, list):
        # old schema: array of members
        members = cv_raw
        cv_norm = {"members": members, "yes": 0, "no": 0, "abstain": 0,
                   "vote_source_type": "", "vote_source_url": "", "needs_foia": False}
    else:
        members = cv_raw.get("members") or []
        yes = cv_raw.get("yes", sum(1 for m in members if (m.get("vote") or "").lower() in ("yes", "aye")))
        no  = cv_raw.get("no",  sum(1 for m in members if (m.get("vote") or "").lower() == "no"))
        ab  = cv_raw.get("abstain", sum(1 for m in members if (m.get("vote") or "").lower() == "abstain"))
        cv_norm = {
            "members":         [_norm_member(m) for m in members],
            "yes":             yes, "no": no, "abstain": ab,
            "vote_source_type": cv_raw.get("vote_source_type", ""),
            "vote_source_url":  cv_raw.get("vote_source_url", ""),
            "needs_foia":       cv_raw.get("needs_foia", False),
        }

    # --- zoning ---
    z_raw = data.get("zoning") or {}
    zones_raw = z_raw.get("zones") or []
    z_norm = {
        "found":          z_raw.get("found", False),
        "url":            z_raw.get("url", ""),
        "description":    z_raw.get("description", ""),
        "zones":          zones_raw,
        "cannabis_overlay": z_raw.get("cannabis_overlay"),
        "zoning_map_url": z_raw.get("zoning_map_url", ""),
        "gis_portal_url": z_raw.get("gis_portal_url", ""),
        "zones_source":   z_raw.get("zones_source", ""),
    }

    # --- rfp_signals ---
    sig_raw = data.get("rfp_signals") or {}
    if isinstance(sig_raw, list):
        signals_list = sig_raw
        cap = {"cap": 0, "awarded": 0, "slots_open": 0, "saturated": False}
        next_action = ""
    else:
        signals_list = sig_raw.get("signals") or []
        cap = sig_raw.get("cap_status") or {"cap": 0, "awarded": 0, "slots_open": 0, "saturated": False}
        next_action = sig_raw.get("next_action_date", "")
    sig_norm = {
        "found":           sig_raw.get("found", bool(signals_list)) if isinstance(sig_raw, dict) else bool(signals_list),
        "signals":         signals_list,
        "awarded_licenses": (sig_raw.get("awarded_licenses") or []) if isinstance(sig_raw, dict) else [],
        "cap_status":      cap,
        "next_action_date": next_action,
    }

    # --- attorneys ---
    a_raw = data.get("attorneys") or {}
    attys = a_raw.get("attorneys") or []
    a_norm = {
        "found":          a_raw.get("found", False),
        "attorneys":      [_norm_attorney(a) for a in attys],
        "top_picks":      a_raw.get("top_picks") or [],
        "town_solicitor": a_raw.get("town_solicitor"),
        "needs_foia":     a_raw.get("needs_foia", False),
    }

    # derive card-level confidence from signals
    conf = "low"
    if any(s.get("confidence") == "high" for s in signals_list):
        conf = "high"
    elif any(s.get("confidence") == "medium" for s in signals_list):
        conf = "medium"

    return {
        "slug":          fp.stem,
        "municipality":  data.get("municipality", fp.stem),
        "county":        data.get("county", ""),
        "run_date":      data.get("run_date", ""),
        "confidence":    conf,
        "ordinance":     ord_norm,
        "council_votes": cv_norm,
        "zoning":        z_norm,
        "rfp_signals":   sig_norm,
        "attorneys":     a_norm,
        "draft_emails":  data.get("draft_emails") or [],
    }


def _norm_member(m: dict) -> dict:
    return {
        "name":           m.get("name", ""),
        "role":           m.get("role", ""),
        "current_title":  m.get("current_title", m.get("role", "")),
        "vote":           m.get("vote", ""),
        "friendly":       m.get("friendly", 0),
        "still_in_office": m.get("still_in_office", True),
        "email":          m.get("email", ""),
        "phone":          m.get("phone", ""),
        "source_url":     m.get("source_url", ""),
    }


def _norm_attorney(a: dict) -> dict:
    return {
        "name":              a.get("name", ""),
        "firm":              a.get("firm", ""),
        "email":             a.get("email", ""),
        "phone":             a.get("phone", ""),
        "tier":              a.get("tier", "C"),
        "score":             a.get("score", 0),
        "this_town_wins":    a.get("this_town_wins", 0),
        "this_town_losses":  a.get("this_town_losses", 0),
        "cannabis_experience": a.get("cannabis_experience", False),
        "appearances":       a.get("appearances") or [],
        "sources":           a.get("sources") or [],
        "why":               a.get("why", ""),
    }


@app.get("/api/dives")
def list_dives():
    if not DIVES_DIR.exists():
        return []
    dives = []
    for fp in sorted(DIVES_DIR.glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            dives.append(_normalize_dive(fp, data))
        except Exception:
            continue
    return dives


@app.get("/api/dives/{slug}")
def get_dive(slug: str):
    fp = DIVES_DIR / f"{slug}.json"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="Dive not found")
    return json.loads(fp.read_text(encoding="utf-8"))


@app.get("/health")
def health():
    return {"ok": True, "db": DB_PATH.exists(), "dives": DIVES_DIR.exists()}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7700))
    uvicorn.run(app, host="127.0.0.1", port=port, reload=False)
