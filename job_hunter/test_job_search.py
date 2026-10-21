#!/usr/bin/env python3
"""
Tests for /procurar (which jobs are sent) and /aplicadas (applied-jobs history).
No network: the scraper is mocked.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

from job_hunter import job_search
from job_hunter.rn_linkedin_scraper import Opportunity
from job_hunter.watcher import SeenStore

PASS = "✓"
FAIL = "✗"
results = {"passed": 0, "failed": 0}


def test(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results["passed" if condition else "failed"] += 1
    print(f"  {status} {name}" + (f"  ({detail})" if detail and not condition else ""))


def job(job_id: str, score: float) -> Opportunity:
    return Opportunity(title=f"RN {job_id}", result_type="job", company_or_author="Acme", location="Remote",
                       url=f"https://www.linkedin.com/jobs/view/{job_id}/", snippet="", relevance_score=score,
                       job_id=job_id)


home = Path(tempfile.mkdtemp())
rows = [
    {"at": "2026-10-09T17:00:00+00:00", "url": "https://www.linkedin.com/jobs/view/4400000111/", "status": "submitted",
     "company": "Kraken", "role": "RN Engineer"},
    {"at": "2026-10-10T17:00:00+00:00", "url": "https://www.linkedin.com/jobs/view/4400000222/", "status": "cancelled",
     "company": "Other", "role": "Mobile"},
    {"at": "2026-10-11T17:00:00+00:00", "url": "https://br.linkedin.com/jobs/view/rn-dev-4400000333", "status": "submitted",
     "company": "Darwoft", "role": "RN Dev"},
]
(home / "applications.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n{broken\n")


# ─────────────────────────────────────────────
print("\n━━━ History Tests ━━━")

subs = job_search.submitted(home)
test("Only submitted jobs", [r["company"] for r in subs] == ["Darwoft", "Kraken"], str(subs))
test("Broken line is skipped", len(subs) == 2)
test("Applied keys use the job ID", job_search.applied_keys(home) == {"job:4400000111", "job:4400000333"},
     str(job_search.applied_keys(home)))
test("Same job, other URL, same short ID",
     job_search.short_id("https://br.linkedin.com/jobs/view/x-4400000111") == job_search.short_id(rows[0]["url"]))
test("Button data is short", len(f"forget:{job_search.short_id(rows[0]['url'])}".encode()) <= 64)

removed = job_search.forget(home, job_search.short_id(rows[0]["url"]))
test("Forget returns the removed job", removed.get("company") == "Kraken")
test("Forgotten job is gone", [r["company"] for r in job_search.submitted(home)] == ["Darwoft"])
test("Other history lines stay", any(r.get("status") == "cancelled" for r in job_search._read(home)))
test("Forget unknown ID does nothing", job_search.forget(home, "nope") == {})
test("No history file → empty", job_search.submitted(Path(tempfile.mkdtemp())) == [])


# ─────────────────────────────────────────────
print("\n━━━ Pick Tests ━━━")

store = SeenStore(home / "seen.json")
store.mark([job("500", 90), job("501", 60)])  # shown before
results_ = [job("4400000333", 99), job("500", 90), job("501", 60), job("600", 55), job("601", 40), job("602", 85)]
new, again = job_search.pick(results_, store, job_search.applied_keys(home),
                             min_score=50, resend_score=80, max_n=10)
test("Applied job never comes back", all(o.job_id != "4400000333" for o in new + again))
test("New jobs above the minimum, best first", [o.job_id for o in new] == ["602", "600"], str([o.job_id for o in new]))
test("Low score is not sent", all(o.job_id != "601" for o in new + again))
test("Shown before + high match → sent again", [o.job_id for o in again] == ["500"])
test("Shown before + normal match → not again", all(o.job_id != "501" for o in again))

new, again = job_search.pick(results_, store, set(), min_score=50, resend_score=80, max_n=2)
test("Cap counts new jobs first", len(new) == 2 and again == [], f"{len(new)} {len(again)}")


# ─────────────────────────────────────────────
print("\n━━━ Run Tests ━━━")

with mock.patch("job_hunter.job_search.scrape", return_value=[job("700", 70), job("500", 90)]) as sc:
    new, again, total = job_search.run(home)
test("Searches the last week, jobs only", sc.call_args.kwargs == {"time_range": "1w", "engines": ["linkedin"]},
     str(sc.call_args))
test("First run sends everything with match", {o.job_id for o in new} == {"700", "500"} and total == 2)
with mock.patch("job_hunter.job_search.scrape", return_value=[job("700", 70), job("500", 90)]):
    new, again, _ = job_search.run(home)
test("Second run: no repeats, except high match", new == [] and [o.job_id for o in again] == ["500"])
test("Bot keeps its own shown list", (home / "search-data" / "seen_jobs.json").exists())
with mock.patch("job_hunter.job_search.scrape", return_value=[job("800", 70)]):
    new, _, _ = job_search.run(home, mark=False)
with mock.patch("job_hunter.job_search.scrape", return_value=[job("800", 70)]):
    new2, _, _ = job_search.run(home)
test("Quiet search doesn't hide jobs from /procurar", [o.job_id for o in new] == [o.job_id for o in new2] == ["800"])


# ─────────────────────────────────────────────
print(f"\n{'━' * 50}")
total = results["passed"] + results["failed"]
print(f"Results: {results['passed']}/{total} passed", end="")
if results["failed"]:
    print(f"  ({results['failed']} FAILED)")
    sys.exit(1)
print("  ✓ All tests passed!")
