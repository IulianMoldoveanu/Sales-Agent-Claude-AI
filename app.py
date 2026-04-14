"""
Sales Agent Claude AI — Web Interface
Mobile-friendly FastAPI app. Start with: python app.py
Then open http://<server-ip>:8000 on your phone.
"""

import csv
import io
import os
import threading
from typing import Optional

from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

load_dotenv()

from config import SECTORS, TARGET_COUNTRIES, COUNTRY_NAMES, WARM_LEAD_THRESHOLD
from src.database import db

app = FastAPI(title="Sales Agent Claude AI")
templates = Jinja2Templates(directory="templates")

# ── Job state (in-memory, one job at a time) ──────────────────────────────────
_job: dict = {"running": False, "log": [], "done": False, "error": None}
_job_lock = threading.Lock()


def _reset_job():
    global _job
    _job = {"running": False, "log": [], "done": False, "error": None}


def _log(msg: str):
    _job["log"].append(msg)


# ── Background pipeline task ──────────────────────────────────────────────────

def _run_pipeline(command: str, sector: Optional[str], country: Optional[str]):
    """Runs in a background thread so the HTTP response returns immediately."""
    import sys, io as _io

    with _job_lock:
        _job["running"] = True
        _job["done"] = False
        _job["error"] = None
        _job["log"] = []

    try:
        db.init_db()

        if command == "run":
            from src.agent.sales_agent import run_agent
            _log(f"Avem start! Caut companii in sectorul {sector} din {country}...")
            scores = run_agent(sector=sector, country=country, verbose=False)
            _log(f"Gata! Am gasit si scorat {len(scores)} companii.")

        elif command == "discover":
            from src.discovery.job_board_scraper import discover_leads
            _log(f"Scanez job board-uri pentru {sector} / {country}...")
            companies, postings = discover_leads(sector=sector, country=country)
            for c in companies:
                db.upsert_company(c)
            for p in postings:
                db.save_job_posting(p)
            _log(f"Gasit {len(companies)} companii si {len(postings)} anunturi.")
            _log("Ruleaza 'Score Leads' pentru a le evalua cu AI.")

        elif command == "score":
            from src.scoring.lead_scorer import score_lead
            unscored = db.get_unscored_companies()
            _log(f"Scorez {len(unscored)} companii cu Claude AI...")
            ok = 0
            for rec in unscored:
                try:
                    score = score_lead(
                        company_name=rec["company_name"],
                        country=rec["country"],
                        sector=rec["sector"],
                        posting_count=int(rec.get("posting_count", 1)),
                        max_days_open=int(rec.get("max_days_open", 0)),
                        total_openings=int(rec.get("total_openings", 1)),
                        repeated_count=int(rec.get("repeated_count", 0)),
                        job_titles=rec.get("titles", ""),
                    )
                    db.upsert_lead_score(score)
                    _log(f"  {rec['company_name']} → scor {score.total_score:.1f}")
                    ok += 1
                except Exception as e:
                    _log(f"  [eroare] {rec.get('company_name')}: {e}")
            _log(f"Done! {ok} companii evaluate.")

    except Exception as e:
        _job["error"] = str(e)
        _log(f"[EROARE] {e}")
    finally:
        _job["running"] = False
        _job["done"] = True


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    db.init_db()
    stats = db.get_stats()
    leads = db.get_top_leads(limit=30, min_score=0.0)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "sectors": SECTORS,
        "countries": TARGET_COUNTRIES,
        "country_names": COUNTRY_NAMES,
        "stats": stats,
        "leads": leads,
        "hot": WARM_LEAD_THRESHOLD,
        "job": _job,
        "api_key_set": bool(os.getenv("ANTHROPIC_API_KEY")),
    })


@app.post("/action", response_class=JSONResponse)
async def action(
    background_tasks: BackgroundTasks,
    command: str = Form(...),
    sector: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
):
    if _job["running"]:
        return JSONResponse({"ok": False, "msg": "Un job deja ruleaza. Asteapta sa se termine."})

    _reset_job()
    background_tasks.add_task(_run_pipeline, command, sector, country)
    return JSONResponse({"ok": True, "msg": "Job pornit!"})


@app.get("/status", response_class=JSONResponse)
async def status():
    return JSONResponse({
        "running": _job["running"],
        "done":    _job["done"],
        "error":   _job["error"],
        "log":     _job["log"],
    })


@app.get("/leads", response_class=JSONResponse)
async def leads_api(
    country: Optional[str] = None,
    sector:  Optional[str] = None,
    min_score: float = 0.0,
):
    db.init_db()
    data = db.get_top_leads(limit=100, min_score=min_score, country=country, sector=sector)
    return JSONResponse({"leads": data, "count": len(data)})


@app.get("/export")
async def export_csv():
    db.init_db()
    leads = db.get_top_leads(limit=10000, min_score=0.0)
    output = io.StringIO()
    fieldnames = [
        "company_name", "country", "sector", "urgency_score", "value_score",
        "total_score", "open_roles_count", "pitch_angle", "recommended_contact", "scored_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(leads)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    print(f"\n Sales Agent pornit pe http://{host}:{port}")
    print(" Deschide adresa de mai sus pe telefon (acelasi WiFi)\n")
    uvicorn.run("app:app", host=host, port=port, reload=False)
