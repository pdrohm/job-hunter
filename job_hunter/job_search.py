"""
On-demand job search for the apply bot (/procurar) and the applied-jobs history
(/aplicadas).

Rules for /procurar:
  - Jobs you already applied to never come back.
  - New jobs at/above APPLY_SEARCH_MIN_SCORE are sent.
  - A job the bot already showed comes back only when its match is very high
    (APPLY_SEARCH_RESEND_SCORE) and it is still recent (the search keeps only
    jobs first posted in the last WATCH_MAX_JOB_AGE_DAYS days).

The bot keeps its own "already shown" list in ~/.job-hunter/search-data: the
2-hour watcher runs on GitHub, so its list is not on this Mac.
"""

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from job_hunter.rn_linkedin_scraper import Opportunity, dedup_key, extract_linkedin_job_id
from job_hunter.watcher import SeenStore, _env, _env_list, scrape

APPLICATIONS_FILE = "applications.jsonl"


# ─────────────────────────────────────────────
# Applied-jobs history (~/.job-hunter/applications.jsonl)
# ─────────────────────────────────────────────

def url_key(url: str) -> str:
    """Same identity as the watcher's dedup_key: the LinkedIn job ID when there is one."""
    job_id = extract_linkedin_job_id(url)
    return f"job:{job_id}" if job_id else f"url:{url.strip().rstrip('/').lower()}"


def short_id(url: str) -> str:
    """Short, stable ID for a Telegram button (callback_data max 64 bytes)."""
    return hashlib.md5(url_key(url).encode()).hexdigest()[:10]


def _read(home: Path) -> list[dict]:
    path = home / APPLICATIONS_FILE
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # keep going: one broken line must not hide the rest
    return rows


def submitted(home: Path) -> list[dict]:
    """Jobs applied to with success, newest first, one row per job."""
    out, seen = [], set()
    for row in reversed(_read(home)):
        key = url_key(row.get("url", ""))
        if row.get("status") == "submitted" and key not in seen:
            seen.add(key)
            out.append(row)
    return out


def applied_keys(home: Path) -> set[str]:
    return {url_key(r["url"]) for r in submitted(home)}


def tried_keys(home: Path) -> set[str]:
    """Every job with any history line (sent, cancelled, skipped). Auto-apply
    tries a job once: if you cancelled it, it never comes back on its own."""
    return {url_key(r["url"]) for r in _read(home) if r.get("url")}


def forget(home: Path, sid: str) -> dict:
    """Remove every history line of the job with this short_id. Returns the
    removed submitted row ({} if nothing matched). Atomic rewrite."""
    rows = _read(home)
    keep = [r for r in rows if short_id(r.get("url", "")) != sid]
    if len(keep) == len(rows):
        return {}
    removed = next((r for r in reversed(rows) if short_id(r.get("url", "")) == sid
                    and r.get("status") == "submitted"), None) \
        or next(r for r in rows if short_id(r.get("url", "")) == sid)
    path = home / APPLICATIONS_FILE
    fd, tmp = tempfile.mkstemp(dir=str(home), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in keep)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise
    return removed


def format_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d/%m")
    except ValueError:
        return ""


# ─────────────────────────────────────────────
# Search
# ─────────────────────────────────────────────

def pick(results: list[Opportunity], store: SeenStore, applied: set[str],
         min_score: float, resend_score: float, max_n: int) -> tuple[list[Opportunity], list[Opportunity]]:
    """(new jobs, high-match jobs shown before), best match first."""
    best = sorted((o for o in results if dedup_key(o) not in applied),
                  key=lambda o: o.relevance_score, reverse=True)
    new = [o for o in best if store.is_new(o) and o.relevance_score >= min_score]
    again = [o for o in best if not store.is_new(o) and o.relevance_score >= resend_score]
    return new[:max_n], again[:max(0, max_n - len(new[:max_n]))]


def run(home: Path, mark: bool = True) -> tuple[list[Opportunity], list[Opportunity], int]:
    """Search now. Returns (new, again, total results). Marks all results as
    shown, unless mark=False (the quiet auto-apply search shows you nothing)."""
    results = scrape(
        time_range=_env("APPLY_SEARCH_TIME_RANGE", "1w"),
        # LinkedIn post search needs its own logged-in Chrome: only jobs here
        engines=_env_list("APPLY_SEARCH_ENGINES", "linkedin"),
    )
    store = SeenStore(home / "search-data" / "seen_jobs.json")
    new, again = pick(results, store, applied_keys(home),
                      min_score=float(_env("APPLY_SEARCH_MIN_SCORE", _env("WATCH_MIN_SCORE", "50"))),
                      resend_score=float(_env("APPLY_SEARCH_RESEND_SCORE", "80")),
                      max_n=int(_env("APPLY_SEARCH_MAX", "10")))
    if mark:
        store.mark(results)
        store.prune()
        store.save()
    return new, again, len(results)
