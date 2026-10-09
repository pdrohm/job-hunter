#!/usr/bin/env python3
"""
Tests for the Telegram notifier and the job watcher.
No network: Telegram calls are mocked.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import notifier
from rn_linkedin_scraper import Opportunity, ResultType
from watcher import SeenStore, select_new

PASS = "✓"
FAIL = "✗"
results = {"passed": 0, "failed": 0}


def test(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results["passed" if condition else "failed"] += 1
    print(f"  {status} {name}" + (f"  ({detail})" if detail and not condition else ""))


def make_opp(**kwargs) -> Opportunity:
    defaults = {
        "title": "React Native Developer",
        "result_type": ResultType.JOB,
        "company_or_author": "TechCo",
        "location": "Remote",
        "url": "https://www.linkedin.com/jobs/view/4475865328/",
        "snippet": "React Native role",
        "relevance_score": 80,
        "job_id": "4475865328",
    }
    defaults.update(kwargs)
    return Opportunity(**defaults)


# ─────────────────────────────────────────────
print("\n━━━ Message Formatting Tests ━━━")

msg = notifier.format_opportunity(make_opp(title="Dev <Senior> & Lead", posted_at="2026-10-08",
                                           seniority="Not Applicable", applicants="12 applicants"))
test("Escapes HTML in title", "Dev &lt;Senior&gt; &amp; Lead" in msg, msg)
test("Shows posted date", "Posted 2026-10-08" in msg)
test("Hides 'Not Applicable' seniority", "Not Applicable" not in msg)
test("Shows applicants", "12 applicants" in msg)
test("Has LinkedIn link", 'href="https://www.linkedin.com/jobs/view/4475865328/"' in msg)

long_text = "\n\n".join(["x" * 1000] * 10)
chunks = notifier.split_message(long_text)
test("Splits long messages", len(chunks) > 1, f"{len(chunks)} chunks")
test("Every chunk under Telegram limit", all(len(c) <= notifier.MAX_MESSAGE_CHARS for c in chunks))
test("Short message is one chunk", len(notifier.split_message("hello")) == 1)


# ─────────────────────────────────────────────
print("\n━━━ Telegram Send Tests ━━━")

with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "42"}), \
        mock.patch("notifier.time.sleep"), \
        mock.patch("notifier.requests.post") as post:
    post.return_value = mock.Mock(status_code=200, content=b"{}", json=lambda: {"ok": True})
    notifier.notify_new([make_opp(), make_opp(job_id="2", url="https://x/2")])
    payload = post.call_args.kwargs["json"]
    test("Sends to configured chat", payload["chat_id"] == "42")
    test("Uses HTML parse mode", payload["parse_mode"] == "HTML")
    test("Header counts jobs", "2 new jobs" in payload["text"], payload["text"][:60])

    post.reset_mock()
    notifier.notify_new([])
    test("Sends nothing when no jobs", not post.called)

with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "42"}), \
        mock.patch("notifier.time.sleep") as sleep, \
        mock.patch("notifier.requests.post") as post:
    limited = mock.Mock(status_code=429, content=b"{}",
                        json=lambda: {"ok": False, "parameters": {"retry_after": 7}})
    ok = mock.Mock(status_code=200, content=b"{}", json=lambda: {"ok": True})
    post.side_effect = [limited, ok]
    notifier.send_message("hi")
    test("Retries after 429", post.call_count == 2)
    test("Waits Telegram's retry_after", mock.call(7) in sleep.call_args_list)

with mock.patch.dict(os.environ, {}, clear=True):
    test("Not configured without env", not notifier.is_configured())


# ─────────────────────────────────────────────
print("\n━━━ Seen Store Tests ━━━")

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "seen.json"
    store = SeenStore(path)
    a = make_opp()
    b = make_opp(job_id="9999999999", url="https://www.linkedin.com/jobs/view/9999999999/", title="Other")
    test("Empty store on first run", store.is_empty)
    test("Unseen job is new", store.is_new(a))

    store.mark([a])
    store.save()
    reloaded = SeenStore(path)
    test("Persists across runs", not reloaded.is_new(a))
    test("Other job still new", reloaded.is_new(b))

    same_job_other_url = make_opp(url="https://br.linkedin.com/jobs/view/dev-at-x-4475865328")
    test("Same job via other URL is not new", not reloaded.is_new(same_job_other_url))

    reloaded.seen["job:old"] = "2000-01-01T00:00:00+00:00"
    reloaded.prune()
    test("Prunes old entries", "job:old" not in reloaded.seen)

    low = make_opp(job_id="1111111111", url="https://www.linkedin.com/jobs/view/1111111111/", relevance_score=10)
    new = select_new([a, b, low], reloaded, min_score=50)
    test("select_new skips seen and low-score", [o.job_id for o in new] == ["9999999999"],
         str([o.job_id for o in new]))

    path.write_text("not json")
    test("Survives corrupt file", SeenStore(path).is_empty)


# ─────────────────────────────────────────────
print(f"\n{'━' * 50}")
total = results["passed"] + results["failed"]
print(f"Results: {results['passed']}/{total} passed", end="")
if results["failed"]:
    print(f"  ({results['failed']} FAILED)")
    sys.exit(1)
print("  ✓ All tests passed!")
