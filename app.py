"""
FastAPI backend for the LinkedIn Job Scraper.
Serves the React frontend and provides API endpoints for scraping.
Each user gets an isolated session with independent scrape state and results.
"""

import json
import os
import tempfile
import threading
import time as _time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Cookie, FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from rn_linkedin_scraper import run_scraper_with_progress, TIME_RANGES, DEFAULT_TIME_RANGE, ALL_ENGINES
from tech_profiles import get_profile_summary

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))

# Per-session state keyed by session_id
_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()

# Auto-cleanup sessions older than 2 hours
SESSION_TTL_SECONDS = 2 * 60 * 60


def _get_session(session_id: str) -> dict:
    """Get or create a session's state."""
    with _sessions_lock:
        if session_id not in _sessions:
            _sessions[session_id] = {
                "status": {
                    "last_scrape_time": None,
                    "result_count": 0,
                    "is_running": False,
                },
                "progress": _make_empty_progress(),
                "last_active": _time.time(),
            }
        else:
            _sessions[session_id]["last_active"] = _time.time()
        return _sessions[session_id]


def _make_empty_progress() -> dict:
    return {
        "phase": "", "phase_num": 0, "total_phases": 5,
        "query": "", "query_num": 0, "total_queries": 0,
        "found_so_far": 0, "phase_found": 0, "step": "",
        "started_at": None, "elapsed_seconds": 0, "log": [],
    }


MAX_LOG_LINES = 30


def _make_progress_callback(session_id: str):
    """Create a progress callback bound to a specific session."""
    def on_progress(event: dict):
        session = _get_session(session_id)
        progress = session["progress"]
        for k, v in event.items():
            if k == "log_line":
                progress["log"].append(v)
                if len(progress["log"]) > MAX_LOG_LINES:
                    progress["log"] = progress["log"][-MAX_LOG_LINES:]
            elif k in progress:
                progress[k] = v
        if progress["started_at"]:
            progress["elapsed_seconds"] = round(_time.time() - progress["started_at"], 1)
    return on_progress


def _results_file(session_id: str) -> Path:
    """Each session stores results in its own file."""
    return DATA_DIR / f"results_{session_id}.json"


def _cleanup_stale_sessions():
    """Remove sessions and their data files if they've been inactive too long."""
    now = _time.time()
    with _sessions_lock:
        stale = [
            sid for sid, s in _sessions.items()
            if not s["status"]["is_running"] and now - s["last_active"] > SESSION_TTL_SECONDS
        ]
        for sid in stale:
            del _sessions[sid]
            try:
                _results_file(sid).unlink(missing_ok=True)
            except OSError:
                pass


def do_scrape(session_id: str, time_range: str = DEFAULT_TIME_RANGE,
              techs: list[str] = None, engines: list[str] = None):
    session = _get_session(session_id)
    status = session["status"]
    if status["is_running"]:
        return
    status["is_running"] = True
    session["progress"] = _make_empty_progress()
    session["progress"]["started_at"] = _time.time()
    try:
        results = run_scraper_with_progress(
            max_results=100,
            time_range=time_range,
            on_progress=_make_progress_callback(session_id),
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
        out_file = _results_file(session_id)
        fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, out_file)
        except Exception:
            os.unlink(tmp_path)
            raise
        status["last_scrape_time"] = datetime.now(timezone.utc).isoformat()
        status["result_count"] = len(results)
        _make_progress_callback(session_id)({"step": "Done", "phase": "Complete"})
    finally:
        status["is_running"] = False


def _ensure_session_cookie(session_id: Optional[str], response: Response) -> str:
    """Return existing session_id or create a new one and set the cookie."""
    if session_id and len(session_id) <= 64:
        return session_id
    new_id = uuid.uuid4().hex[:16]
    response.set_cookie("session_id", new_id, max_age=SESSION_TTL_SECONDS, httponly=True, samesite="lax")
    return new_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Periodic cleanup of stale sessions every 30 minutes
    stop_event = threading.Event()

    def cleanup_loop():
        while not stop_event.wait(1800):
            _cleanup_stale_sessions()

    t = threading.Thread(target=cleanup_loop, daemon=True)
    t.start()
    yield
    stop_event.set()


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
def get_results(response: Response, session_id: Optional[str] = Cookie(None)):
    sid = _ensure_session_cookie(session_id, response)
    rf = _results_file(sid)
    if rf.exists():
        try:
            with open(rf, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return {"metadata": {"total_results": 0}, "results": []}


@app.post("/api/scrape")
def trigger_scrape(
    response: Response,
    time_range: str = DEFAULT_TIME_RANGE,
    techs: Optional[str] = None,
    engines: Optional[str] = None,
    session_id: Optional[str] = Cookie(None),
):
    sid = _ensure_session_cookie(session_id, response)
    session = _get_session(sid)

    if session["status"]["is_running"]:
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
        args=(sid, time_range, tech_list, engine_list),
        daemon=True,
    ).start()
    return {"status": "started", "message": f"Scrape started ({time_range})."}


@app.get("/api/status")
def get_status(response: Response, session_id: Optional[str] = Cookie(None)):
    sid = _ensure_session_cookie(session_id, response)
    session = _get_session(sid)
    status = session["status"]

    result_count = status["result_count"]
    job_count = 0
    post_count = 0
    rf = _results_file(sid)
    if rf.exists():
        try:
            with open(rf, "r", encoding="utf-8") as f:
                data = json.load(f)
            results = data.get("results", [])
            result_count = len(results)
            job_count = sum(1 for r in results if r.get("result_type") == "job")
            post_count = sum(1 for r in results if r.get("result_type") == "post")
        except Exception:
            pass
    return {
        "last_scrape_time": status["last_scrape_time"],
        "result_count": result_count,
        "job_count": job_count,
        "post_count": post_count,
        "is_running": status["is_running"],
        "progress": dict(session["progress"]) if status["is_running"] else None,
    }


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"))
