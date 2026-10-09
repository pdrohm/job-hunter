#!/usr/bin/env python3
"""
Tests for the apply bot: safety rules, command handling and the review flow.
No network, no Chrome, no Claude: those are mocked.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import apply_bot
import notifier
from apply_bot import (AnswerMemory, ApplyBot, ClaudeResult, Config, build_claude_cmd, extract_url,
                       format_report, parse_report)

PASS = "✓"
FAIL = "✗"
results = {"passed": 0, "failed": 0}


def test(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results["passed" if condition else "failed"] += 1
    print(f"  {status} {name}" + (f"  ({detail})" if detail and not condition else ""))


tmp = Path(tempfile.mkdtemp())
(tmp / "profile.md").write_text("Name: Test Person")
(tmp / "resume.pdf").write_bytes(b"%PDF-1.4 test")
cfg = Config(chat_id="42", profile_path=tmp / "profile.md", resume_path=tmp / "resume.pdf",
             memory_path=tmp / "memory.json", home=tmp / "home", chrome_port=9333, chrome_bin="/bin/echo",
             claude_bin="/bin/echo", model="sonnet")


def update_msg(text, chat_id=42):
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text}}


def update_cb(data, chat_id=42):
    return {"update_id": 2, "callback_query": {"id": "cb1", "data": data,
                                               "message": {"chat": {"id": chat_id}}}}


class SyncBot(ApplyBot):
    """Runs steps inline instead of in a thread, and records what it says."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.said = []
        self.prompts = []

    def say(self, text, reply_markup=None):
        self.said.append((text, reply_markup))

    def send_screenshot(self, app, name, caption, reply_markup=None):
        self.said.append((caption, reply_markup))

    def run_step(self, app, stage, prompt):
        app.stage = stage
        self.prompts.append(prompt)
        self._run_step(app, prompt)


def fake_result(status, **extra):
    report = {"status": status, "company": "Kraken", "role": "RN Engineer",
              "summary": "Filled.", "answers": [{"question": "Why?", "answer": "Because."}],
              "screenshot": "review-1.png", **extra}
    return ClaudeResult(True, "done\n```json\n" + json.dumps(report) + "\n```", "sess-1", report, 0.12)


# ─────────────────────────────────────────────
print("\n━━━ Safety Tests ━━━")

cmd = build_claude_cmd(cfg, "hi", tmp / "mcp.json")
allowed = cmd[cmd.index("--allowedTools") + 1: cmd.index("--disallowedTools")]
disallowed = cmd[cmd.index("--disallowedTools") + 1: cmd.index("--append-system-prompt")]
test("Only browser tools allowed", all(t.startswith("mcp__browser__browser_") for t in allowed), str(allowed))
test("No code-execution tool allowed", not any("run_code" in t or "evaluate" in t for t in allowed))
test("No cookie/storage tool allowed", not any("cookie" in t or "storage" in t for t in allowed))
test("Shell and file tools disallowed", {"Bash", "Read", "Write", "Edit"} <= set(disallowed))
test("Ignores other MCP servers", "--strict-mcp-config" in cmd)
test("System prompt forbids submit without approval", "SUBMIT NOW" in cmd[cmd.index("--append-system-prompt") + 1])
test("Resume flag only when resuming", "--resume" not in cmd)
test("Resume flag passed", "--resume" in build_claude_cmd(cfg, "hi", tmp / "m.json", "sess-1"))

bot = SyncBot(cfg)
with mock.patch.object(bot, "start_application") as start:
    bot.handle_update(update_msg("/candidatar https://x.com/job", chat_id=999))
    test("Ignores strangers", not start.called and not bot.said)
    bot.handle_update(update_cb("apply:4475865328", chat_id=999))
    test("Ignores stranger buttons", not start.called)


# ─────────────────────────────────────────────
print("\n━━━ Parsing Tests ━━━")

test("Parses last JSON block", parse_report('a ```json\n{"status":"x"}\n``` b ```json\n{"status":"ready"}\n```')
     == {"status": "ready"})
test("No JSON → empty", parse_report("no json here") == {})
test("Broken JSON → empty", parse_report("```json\n{bad}\n```") == {})
test("Extracts URL", extract_url("/candidatar https://jobs.ashbyhq.com/k/123?utm=x") == "https://jobs.ashbyhq.com/k/123?utm=x")
test("No URL", extract_url("/candidatar") == "")


# ─────────────────────────────────────────────
print("\n━━━ Flow Tests ━━━")

with mock.patch("apply_bot.ensure_chrome"), \
        mock.patch("apply_bot.notifier.call"), \
        mock.patch("apply_bot.run_claude") as rc:
    bot = SyncBot(cfg)

    bot.handle_update(update_msg("/candidatar"))
    test("Asks for a link", "candidatar https://" in bot.said[-1][0])

    rc.return_value = fake_result("ready")
    bot.handle_update(update_msg("/candidatar https://jobs.ashbyhq.com/kraken/1"))
    app = bot.app
    test("Starts application", app is not None and app.url == "https://jobs.ashbyhq.com/kraken/1")
    test("Resume copied into sandbox", (app.workdir / "resume.pdf").exists())
    test("Profile in fill prompt", "Name: Test Person" in bot.prompts[-1])
    test("Fill prompt says do not submit", "Do NOT submit" in bot.prompts[-1])
    test("Goes to review", app.stage == "review")
    caption, kb = bot.said[-1]
    test("Review shows answers", "Why?" in caption and "Because." in caption)
    test("Review says NOT sent", "NÃO enviado" in caption)
    labels = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    test("Review has 3 buttons", labels == [f"submit:{app.id}", f"edit:{app.id}", f"cancel:{app.id}"], str(labels))

    bot.handle_update(update_msg("/candidatar https://other.com/2"))
    test("One application at a time", bot.app is app and "Já estou" in bot.said[-1][0])

    bot.handle_update(update_cb("submit:wrongid"))
    test("Old button is rejected", "não está ativa" in bot.said[-1][0])

    bot.handle_update(update_cb(f"edit:{app.id}"))
    test("Edit asks what to change", app.stage == "editing")
    rc.return_value = fake_result("ready", screenshot="review-2.png")
    bot.handle_update(update_msg("muda o salário para 6000 USD"))
    test("Edit text goes to Claude", "6000 USD" in bot.prompts[-1] and "Do NOT submit" in bot.prompts[-1])
    test("Edit resumes the same session", rc.call_args.args[3] == "sess-1")
    test("Back to review after edit", app.stage == "review")

    rc.return_value = fake_result("submitted", screenshot="submitted.png")
    bot.handle_update(update_cb(f"submit:{app.id}"))
    test("Submit prompt sent", bot.prompts[-1].startswith("SUBMIT NOW"))
    test("Success message", "enviada" in bot.said[-1][0])
    test("Application closed", bot.app is None)
    history = (cfg.home / "applications.jsonl").read_text()
    test("History logged", '"status": "submitted"' in history and "Kraken" in history)

    # needs_human path
    rc.return_value = fake_result("needs_human", summary="CAPTCHA on page")
    bot.handle_update(update_cb("apply:4475865328"))
    test("Button opens LinkedIn job", bot.app.url == "https://www.linkedin.com/jobs/view/4475865328/")
    test("needs_human asks for help", "Preciso de você" in bot.said[-1][0] and "CAPTCHA" in bot.said[-1][0])

    bot.handle_update(update_msg("/cancelar"))
    test("Cancel clears", bot.app is None and "Nada foi enviado" in bot.said[-1][0])

    rc.return_value = fake_result("skip", summary="Range USD 3-4k/month is below the minimum")
    bot.handle_update(update_msg("/candidatar https://x.com/lowpay"))
    test("skip explains and does not fill", "Não candidatei" in bot.said[-1][0] and "below the minimum" in bot.said[-1][0])
    bot.handle_update(update_msg("/cancelar"))

    # Submit not confirmed → stay in review
    rc.return_value = fake_result("ready")
    bot.handle_update(update_msg("/candidatar https://x.com/3"))
    rc.return_value = fake_result("failed", summary="Button disabled")
    bot.handle_update(update_cb(f"submit:{bot.app.id}"))
    test("Failed submit stays in review", bot.app is not None and bot.app.stage == "review")

    rc.side_effect = RuntimeError("boom")
    bot.handle_update(update_cb(f"submit:{bot.app.id}"))
    test("Crash does not kill the bot", bot.app is not None and "Não consegui" in bot.said[-1][0])
    rc.side_effect = None


# ─────────────────────────────────────────────
print("\n━━━ Memory Tests ━━━")

history = json.loads(cfg.memory_path.read_text())
test("Correction saved from ✏️ Corrigir", any("6000 USD" in c["text"] for c in history["corrections"]))
test("Correction keeps the company", history["corrections"][0]["company"] == "Kraken")
test("Submitted answers saved", any(a["question"] == "Why?" for a in history["answers"]))

with mock.patch("apply_bot.ensure_chrome"), mock.patch("apply_bot.notifier.call"), \
        mock.patch("apply_bot.run_claude") as rc:
    bot = SyncBot(cfg)  # fresh bot = memory loaded from disk
    rc.return_value = fake_result("ready")
    bot.handle_update(update_msg("/candidatar https://x.com/next"))
    test("Next fill prompt includes past correction", "6000 USD" in bot.prompts[-1])
    test("Next fill prompt includes approved answer", "Because." in bot.prompts[-1])
    bot.handle_update(update_msg("/cancelar"))
    bot.handle_update(update_msg("/memoria"))
    test("/memoria shows counts", "correções" in bot.said[-1][0])

mem = AnswerMemory(tmp / "m2.json")
test("Empty memory renders placeholder", "empty" in mem.render())
mem.add_submitted_answers({"company": "A", "answers": [{"question": "Why us?", "answer": "Old"}]})
mem.add_submitted_answers({"company": "B", "answers": [{"question": "why US?!", "answer": "New"},
                                                        {"question": "Salary", "answer": "(left blank)"}]})
answers = AnswerMemory(tmp / "m2.json").data["answers"]
test("Same question replaced by newest", [a["answer"] for a in answers] == ["New"], str(answers))
test("Blank placeholders not saved", not any(a["question"] == "Salary" for a in answers))
for i in range(30):
    mem.add_correction(f"fix {i}", {})
test("Corrections capped", len(mem.data["corrections"]) == apply_bot.MEMORY_MAX_CORRECTIONS)
(tmp / "bad.json").write_text("{not json")
test("Corrupt memory file survives", AnswerMemory(tmp / "bad.json").render().startswith("(empty"))

rep_text = format_report({"summary": "ok", "missing": ["Salary expectation?"]})
test("Report lists missing fields", "Salary expectation?" in rep_text and "em branco" in rep_text)

sp = apply_bot.SYSTEM_PROMPT
test("Prompt bans hype words", "passionate" in sp and "leverage" in sp)
test("Prompt forbids answering TODO items", "[TODO]" in sp and "EMPTY" in sp)
test("Prompt respects Do not claim", "Do not claim" in sp)


# ─────────────────────────────────────────────
print("\n━━━ Notifier Button Tests ━━━")

from rn_linkedin_scraper import Opportunity, ResultType

opps = [
    Opportunity(title="React Native Engineer at a very long company name", result_type=ResultType.JOB,
                company_or_author="X", location="Remote", url="u1", snippet="", job_id="4475865328"),
    Opportunity(title="Hiring post", result_type=ResultType.POST, company_or_author="Y",
                location="", url="u2", snippet=""),
]
kb = notifier.apply_keyboard(opps)
rows = kb["inline_keyboard"]
test("One button per job (posts skipped)", len(rows) == 1)
test("Callback carries job ID", rows[0][0]["callback_data"] == "apply:4475865328")
test("Callback under 64 bytes", len(rows[0][0]["callback_data"].encode()) <= 64)
test("Label is short", len(rows[0][0]["text"]) <= notifier.APPLY_BUTTON_LABEL_CHARS)
test("No buttons when no jobs", notifier.apply_keyboard(opps[1:]) is None)


# ─────────────────────────────────────────────
print(f"\n{'━' * 50}")
total = results["passed"] + results["failed"]
print(f"Results: {results['passed']}/{total} passed", end="")
if results["failed"]:
    print(f"  ({results['failed']} FAILED)")
    sys.exit(1)
print("  ✓ All tests passed!")
