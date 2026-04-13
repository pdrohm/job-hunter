"""
FastAPI backend for the LinkedIn Job Scraper.
Serves the React frontend and provides API endpoints for scraping.
"""

import json
import os
import tempfile
import threading
import time as _time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from rn_linkedin_scraper import run_scraper_with_progress, TIME_RANGES, DEFAULT_TIME_RANGE, ALL_ENGINES
from tech_profiles import get_profile_summary

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
RESULTS_FILE = DATA_DIR / "results.json"

_scrape_lock = threading.Lock()
_scrape_status = {
    "last_scrape_time": None,
    "result_count": 0,
    "is_running": False,
}

_progress = {
    "phase": "",
    "phase_num": 0,
    "total_phases": 5,
    "query": "",
    "query_num": 0,
    "total_queries": 0,
    "found_so_far": 0,
    "phase_found": 0,
    "step": "",
    "started_at": None,
    "elapsed_seconds": 0,
    "log": [],
}

MAX_LOG_LINES = 30


def _on_progress(event: dict):
    for k, v in event.items():
        if k == "log_line":
            _progress["log"].append(v)
            if len(_progress["log"]) > MAX_LOG_LINES:
                _progress["log"] = _progress["log"][-MAX_LOG_LINES:]
        elif k in _progress:
            _progress[k] = v
    if _progress["started_at"]:
        _progress["elapsed_seconds"] = round(_time.time() - _progress["started_at"], 1)


def _reset_progress():
    _progress.update({
        "phase": "", "phase_num": 0, "total_phases": 5,
        "query": "", "query_num": 0, "total_queries": 0,
        "found_so_far": 0, "phase_found": 0, "step": "",
        "started_at": _time.time(), "elapsed_seconds": 0, "log": [],
    })


def do_scrape(time_range: str = DEFAULT_TIME_RANGE, techs: list[str] = None, engines: list[str] = None):
    if _scrape_status["is_running"]:
        return
    _scrape_status["is_running"] = True
    _reset_progress()
    try:
        results = run_scraper_with_progress(
            max_results=100,
            time_range=time_range,
            on_progress=_on_progress,
            techs=techs,
            engines=engines,
        )
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_results": len(results),
            },
            "results": [asdict(o) for o in results],
        }
        fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, RESULTS_FILE)
        except Exception:
            os.unlink(tmp_path)
            raise
        _scrape_status["last_scrape_time"] = datetime.now(timezone.utc).isoformat()
        _scrape_status["result_count"] = len(results)
        _on_progress({"step": "Done", "phase": "Complete"})
    finally:
        _scrape_status["is_running"] = False


scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=do_scrape, daemon=True).start()
    scheduler.add_job(do_scrape, "interval", hours=6, id="scrape_job")
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)


@app.get("/api/techs")
def get_techs():
    """Return available tech profiles for the frontend selector."""
    return get_profile_summary()


@app.get("/api/engines")
def get_engines():
    """Return available search engines."""
    return [
        {"id": "linkedin", "label": "LinkedIn Jobs"},
        {"id": "duckduckgo", "label": "DuckDuckGo"},
        {"id": "bing", "label": "Bing"},
        {"id": "google", "label": "Google"},
    ]


@app.get("/api/results")
def get_results():
    if RESULTS_FILE.exists():
        try:
            with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return {"metadata": {"total_results": 0}, "results": []}


@app.post("/api/scrape")
def trigger_scrape(
    time_range: str = DEFAULT_TIME_RANGE,
    techs: Optional[str] = None,
    engines: Optional[str] = None,
):
    if _scrape_status["is_running"]:
        return JSONResponse(
            {"status": "already_running", "message": "A scrape is already in progress."},
            status_code=409,
        )
    if time_range not in TIME_RANGES:
        time_range = DEFAULT_TIME_RANGE

    tech_list = [t.strip() for t in techs.split(",") if t.strip()] if techs else None
    engine_list = [e.strip() for e in engines.split(",") if e.strip()] if engines else None

    threading.Thread(
        target=do_scrape,
        args=(time_range, tech_list, engine_list),
        daemon=True,
    ).start()
    return {"status": "started", "message": f"Scrape started ({time_range})."}


@app.get("/api/status")
def get_status():
    result_count = _scrape_status["result_count"]
    job_count = 0
    post_count = 0
    if RESULTS_FILE.exists():
        try:
            with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            results = data.get("results", [])
            result_count = len(results)
            job_count = sum(1 for r in results if r.get("result_type") == "job")
            post_count = sum(1 for r in results if r.get("result_type") == "post")
        except Exception:
            pass
    return {
        "last_scrape_time": _scrape_status["last_scrape_time"],
        "result_count": result_count,
        "job_count": job_count,
        "post_count": post_count,
        "is_running": _scrape_status["is_running"],
        "progress": dict(_progress) if _scrape_status["is_running"] else None,
    }


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"))
