#!/usr/bin/env python3
"""
Job watcher: runs the scraper on a schedule and sends only NEW jobs to Telegram.

Usage:
    python watcher.py            # Loop forever (every WATCH_INTERVAL_MINUTES)
    python watcher.py --once     # One run, then exit (for cron / GitHub Actions)
    python watcher.py --dry-run  # Print new jobs instead of sending them

Config (environment variables or .env):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   required (see notifier.py)
    WATCH_TECHS              comma-separated tech IDs   (default: react_native)
    WATCH_ENGINES            comma-separated engines    (default: linkedin,yahoo)
    WATCH_LOCATIONS          LinkedIn search locations  (default: Worldwide,Latin America,Brazil)
    WATCH_CONTRACT_ONLY      true = only contractor/B2B (default: false)
    WATCH_ALLOW_SPONSORSHIP  true = keep jobs needing work authorization (default: false)
    WATCH_TIME_RANGE         24h, 3d, 1w, ...           (default: 24h)
    WATCH_INTERVAL_MINUTES   minutes between runs       (default: 120)
    WATCH_MIN_SCORE          only notify at/above score (default: 50)
    WATCH_MAX_PER_RUN        max jobs per notification  (default: 15)
    DATA_DIR                 where seen_jobs.json lives (default: ./data)
"""

import argparse
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

import notifier
from rn_linkedin_scraper import Opportunity, dedup_key, run_scraper_with_progress

log = logging.getLogger("watcher")

SEEN_TTL_DAYS = 60  # forget jobs after this, keeps the file small


def _env_list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))


class SeenStore:
    """Remembers which jobs were already sent, so each job is sent once."""

    def __init__(self, path: Path):
        self.path = path
        self.seen: dict[str, str] = {}  # dedup key -> ISO time first seen
        if path.exists():
            try:
                self.seen = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                log.warning("Corrupt %s, starting fresh", path)

    @property
    def is_empty(self) -> bool:
        return not self.seen

    def is_new(self, opp: Opportunity) -> bool:
        return dedup_key(opp) not in self.seen

    def mark(self, opps: list[Opportunity]):
        now = datetime.now(timezone.utc).isoformat()
        for opp in opps:
            self.seen.setdefault(dedup_key(opp), now)

    def prune(self, ttl_days: int = SEEN_TTL_DAYS):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat()
        self.seen = {k: v for k, v in self.seen.items() if v >= cutoff}

    def save(self):
        """Atomic write: a crash mid-write never leaves a broken file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.seen, f)
            os.replace(tmp, self.path)
        except Exception:
            os.unlink(tmp)
            raise


def select_new(results: list[Opportunity], store: SeenStore, min_score: float) -> list[Opportunity]:
    return [o for o in results if store.is_new(o) and o.relevance_score >= min_score]


def run_once(dry_run: bool = False) -> int:
    """One scrape + notify cycle. Returns the number of new jobs sent."""
    min_score = float(os.environ.get("WATCH_MIN_SCORE", "50"))
    max_per_run = int(os.environ.get("WATCH_MAX_PER_RUN", "15"))

    results = run_scraper_with_progress(
        max_results=200,
        time_range=os.environ.get("WATCH_TIME_RANGE", "24h"),
        on_progress=lambda e: log.info(e["log_line"]) if "log_line" in e else None,
        techs=_env_list("WATCH_TECHS", "react_native"),
        engines=_env_list("WATCH_ENGINES", "linkedin,yahoo"),
        locations=_env_list("WATCH_LOCATIONS", "Worldwide,Latin America,Brazil"),
        contract_only=_env_bool("WATCH_CONTRACT_ONLY", False),
        exclude_sponsorship=not _env_bool("WATCH_ALLOW_SPONSORSHIP", False),
    )

    store = SeenStore(_data_dir() / "seen_jobs.json")
    first_run = store.is_empty
    new = select_new(results, store, min_score)
    to_send = new[:max_per_run]

    if first_run and to_send:
        header = f"👋 Job Hunter started. Top {len(to_send)} jobs right now:"
    else:
        header = None

    if dry_run:
        print(notifier.format_digest(to_send, header or f"{len(to_send)} new jobs"))
    elif to_send:
        notifier.notify_new(to_send, header=header)

    # Mark every result as seen (not only the sent ones), so low-score
    # jobs don't come back on every run.
    if not dry_run:
        store.mark(results)
        store.prune()
        store.save()

    log.info("Run done: %d results, %d new, %d sent", len(results), len(new), len(to_send))
    return len(to_send)


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description="Send new jobs to Telegram")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print instead of sending")
    args = parser.parse_args()

    if not args.dry_run and not notifier.is_configured():
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first (see notifier.py).")

    if args.once or args.dry_run:
        run_once(dry_run=args.dry_run)
        return

    interval = int(os.environ.get("WATCH_INTERVAL_MINUTES", "120")) * 60
    while True:
        try:
            run_once()
        except Exception:
            # Never let one bad run kill the watcher
            log.exception("Run failed, will retry next cycle")
        log.info("Sleeping %d minutes", interval // 60)
        time.sleep(interval)


if __name__ == "__main__":
    main()
