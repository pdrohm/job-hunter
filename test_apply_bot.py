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
from apply_bot import (AnswerMemory, ApplyBot, ClaudeResult, Config, _parse_intent, build_claude_cmd,
                       build_intent_cmd, extract_url, format_report, parse_report)

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
test("All built-in tools off", cmd[cmd.index("--tools") + 1] == "")
test("Step has a cost cap", "--max-budget-usd" in cmd)
icmd = build_intent_cmd(cfg, "hi")
test("Router has no tools", icmd[icmd.index("--tools") + 1] == "" and "--mcp-config" not in icmd)
with mock.patch.dict(apply_bot.os.environ, {"CLAUDE_CODE_SESSION_ID": "x", "CLAUDECODE": "1", "PATH": "/bin"}):
    env = apply_bot.clean_env()
test("Child claude not tied to a parent session", "CLAUDE_CODE_SESSION_ID" not in env and "CLAUDECODE" not in env
     and env.get("PATH") == "/bin")
test("Router uses small model", icmd[icmd.index("--model") + 1] == "haiku")
test("Router output is schema-checked", "--json-schema" in icmd)
test("Router can't submit by itself", "submit" in apply_bot.INTENT_ACTIONS and "SUBMIT NOW" not in apply_bot.INTENT_PROMPT)
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
test("Candidate's own facts are allowed", "facts the candidate states about themselves" in apply_bot.SYSTEM_PROMPT)
test("Do-not-claim still wins", "Do not claim" in apply_bot.SYSTEM_PROMPT)
test("Router sends notes to edit", "fala que eu uso LLMs" in apply_bot.INTENT_PROMPT)
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

    bot.handle_update(update_cb(f"edit:{app.id}"))
    test("Edit hint says voice and notes work", "áudio" in bot.said[-1][0] and "LLMs" in bot.said[-1][0])
    notes = "describe the API of pelvtime and I implemented LLMs all the time, using skills and the best practices"
    with mock.patch("apply_bot.voice_problem", return_value=""), \
            mock.patch("apply_bot.transcribe_voice", return_value=notes):
        bot.handle_update({"update_id": 9, "message": {"chat": {"id": 42},
                                                        "voice": {"file_id": "v9", "duration": 8}}})
    test("Voice notes during Corrigir go to Claude", notes in bot.prompts[-1], bot.prompts[-1][:200])
    test("Notes are written as an answer, not pasted", "Never" in bot.prompts[-1]
         and "paste the notes word for word" in bot.prompts[-1])
    test("Misheard names can be fixed", "speech-to-text" in bot.prompts[-1])
    test("Back to review after voice edit", app.stage == "review")

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
print("\n━━━ Natural Language Tests ━━━")

test("Intent from structured_output", _parse_intent({"structured_output": {"action": "status"}}) == {"action": "status"})
test("Intent from result text", _parse_intent({"result": 'ok {"action": "help"}'}) == {"action": "help"})
test("No intent → empty", _parse_intent({"result": "nothing"}) == {})


class InlineThread:
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


with mock.patch("apply_bot.ensure_chrome"), mock.patch("apply_bot.notifier.call"), \
        mock.patch("apply_bot.threading.Thread", InlineThread), \
        mock.patch("apply_bot.run_claude") as rc, mock.patch("apply_bot.classify_intent") as ci:
    bot = SyncBot(cfg)
    rc.return_value = fake_result("ready")

    ci.return_value = {"action": "apply", "url": "https://jobs.ashbyhq.com/k/9"}
    bot.handle_update(update_msg("candidata nessa aqui https://jobs.ashbyhq.com/k/9 por favor"))
    test("'candidata nessa <link>' starts application", bot.app and bot.app.url == "https://jobs.ashbyhq.com/k/9")

    ci.return_value = {"action": "edit", "text": "notice period 2 weeks"}
    bot.handle_update(update_msg("põe que eu tenho 2 semanas de aviso"))
    test("Free-text change during review edits the form", "notice period 2 weeks" in bot.prompts[-1])

    ci.return_value = {"action": "submit"}
    bot.handle_update(update_msg("pode enviar"))
    caption, kb = bot.said[-1]
    test("'pode enviar' does NOT submit", not bot.prompts[-1].startswith("SUBMIT NOW"))
    test("'pode enviar' shows the ✅ button", "✅ Enviar" in caption and kb is not None)

    ci.return_value = {"action": "status"}
    bot.handle_update(update_msg("como tá?"))
    test("'como tá?' → status", "Etapa" in bot.said[-1][0])

    ci.return_value = {"action": "cancel"}
    bot.handle_update(update_msg("deixa pra lá"))
    test("'deixa pra lá' → cancel", bot.app is None)

    ci.return_value = {"action": "apply", "url": "https://made-up.example/job"}
    bot.handle_update(update_msg("quero me candidatar naquela da Kraken"))
    test("Model-invented link is ignored", bot.app is None and "link" in bot.said[-1][0])

    ci.return_value = {"action": "chat", "reply": "Oi! <b>Mande</b> um link."}
    bot.handle_update(update_msg("oi"))
    test("Chat reply is HTML-escaped", "&lt;b&gt;" in bot.said[-1][0])

    ci.return_value = {}
    bot.handle_update(update_msg("asdfgh"))
    test("Router failure → help", "Pode falar normal" in bot.said[-1][0])

    ci.reset_mock()
    bot.handle_update(update_msg("https://jobs.lever.co/x/1"))
    test("Bare link skips the router", not ci.called and bot.app is not None)
    bot.handle_update(update_msg("/cancelar"))


# ─────────────────────────────────────────────
print("\n━━━ Pause / Idle Tests ━━━")

with mock.patch("apply_bot.ensure_chrome"), mock.patch("apply_bot.notifier.call"), \
        mock.patch("apply_bot.threading.Thread", InlineThread), \
        mock.patch("apply_bot.close_chrome") as close, mock.patch("apply_bot.chrome_running", return_value=True), \
        mock.patch("apply_bot.run_claude") as rc, mock.patch("apply_bot.classify_intent") as ci:
    rc.return_value = fake_result("ready")
    bot = SyncBot(cfg)
    bot.handle_update(update_msg("/pausar"))
    test("/pausar pauses", bot.paused and "pausado" in bot.said[-1][0])
    test("Pausing with nothing open closes Chrome", close.called)
    bot.handle_update(update_msg("/candidatar https://x.com/1"))
    test("Paused bot does not apply", bot.app is None and "pausado" in bot.said[-1][0])
    bot.handle_update(update_cb("apply:4475865328"))
    test("Paused bot ignores Candidatar button", bot.app is None)
    test("Status says paused", "pausado" in bot.status_text())
    test("Pause survives a restart", SyncBot(cfg).paused)

    ci.return_value = {"action": "resume"}
    bot.handle_update(update_msg("ativa o aplicar"))
    test("'ativa o aplicar' resumes", not bot.paused and "ativado" in bot.said[-1][0])
    test("Resume survives a restart", not SyncBot(cfg).paused)

    ci.return_value = {"action": "pause"}
    bot.handle_update(update_msg("/candidatar https://x.com/2"))
    bot.handle_update(update_msg("pausa o aplicar"))
    test("Pause keeps the open application", bot.app is not None and "continua" in bot.said[-1][0])
    bot.handle_update(update_msg("/cancelar"))
    bot.handle_update(update_msg("/ativar"))

    close.reset_mock()
    bot.last_activity = apply_bot.time.time()
    bot.close_chrome_if_idle()
    test("Recent activity keeps Chrome", not close.called)
    bot.last_activity -= apply_bot.CHROME_IDLE_SECONDS + 1
    bot.close_chrome_if_idle()
    test("Idle Chrome is closed", close.called)
    close.reset_mock()
    bot.app = object()
    bot.close_chrome_if_idle()
    test("Chrome stays open during an application", not close.called)
    bot.app = None


with mock.patch("apply_bot.subprocess.run") as run:
    apply_bot.close_chrome(cfg)
    args = run.call_args.args[0]
test("pkill pattern is not read as an option", args[:3] == ["pkill", "-f", "--"], str(args))
test("pkill only targets the bot's Chrome profile", args[3] == f"--user-data-dir={cfg.home / 'chrome-profile'}")


def fake_get(body):
    resp = mock.Mock()
    resp.json.return_value = body
    return mock.patch("apply_bot.requests.get", return_value=resp)


real_chrome = {"Browser": "Chrome/155.0.8059.40", "webSocketDebuggerUrl": "ws://127.0.0.1:9333/devtools/browser/x"}
with fake_get(real_chrome):
    test("Real Chrome counts as running", apply_bot.chrome_running(cfg))
with fake_get({"error": "not chrome"}):
    test("Other program on the port is not Chrome", not apply_bot.chrome_running(cfg))
with mock.patch("apply_bot.requests.get", side_effect=apply_bot.requests.ConnectionError()):
    test("Closed port is not Chrome", not apply_bot.chrome_running(cfg))

auto = Config(**{**cfg.__dict__, "chrome_port": 0})
port_file = auto.home / "chrome-profile" / "DevToolsActivePort"
port_file.unlink(missing_ok=True)
test("Auto port: no Chrome yet, no endpoint", apply_bot.chrome_endpoint(auto) == "")
test("Auto port: not running without the port file", not apply_bot.chrome_running(auto))
port_file.parent.mkdir(parents=True, exist_ok=True)
port_file.write_text("54321\n/devtools/browser/x\n")
test("Auto port read from DevToolsActivePort", apply_bot.chrome_endpoint(auto) == "http://127.0.0.1:54321")

with mock.patch("apply_bot.subprocess.Popen") as popen, mock.patch("apply_bot.time.sleep"), \
        mock.patch("apply_bot.chrome_running", side_effect=[False, False, True]):
    apply_bot.ensure_chrome(auto)
    launch = popen.call_args.args[0]
test("Chrome starts with a free port", "--remote-debugging-port=0" in launch, str(launch))
test("Stale port file removed before start", not port_file.exists())
with mock.patch("apply_bot.subprocess.Popen") as popen, mock.patch("apply_bot.chrome_running", return_value=True):
    apply_bot.ensure_chrome(auto)
test("Running Chrome is reused", not popen.called)


# ─────────────────────────────────────────────
print("\n━━━ Voice Tests ━━━")


def update_voice(duration=5, chat_id=42):
    return {"update_id": 3, "message": {"chat": {"id": chat_id},
                                         "voice": {"file_id": "v1", "duration": duration}}}


with mock.patch("apply_bot.voice_problem", return_value=""), \
        mock.patch("apply_bot.transcribe_voice", return_value="como tá?") as tv, \
        mock.patch("apply_bot.notifier.call"):
    bot = SyncBot(cfg)
    with mock.patch.object(bot, "handle_text") as ht:
        bot.handle_update(update_voice())
    test("Voice is transcribed", tv.call_args.args[1] == "v1")
    test("Says it is listening first", bot.said[0][0].startswith("🎧 Ouvindo"))
    test("Shows what it heard", "Ouvi" in bot.said[-1][0] and "como tá?" in bot.said[-1][0])
    test("Heard text goes the typed-message path", ht.call_args.args[0] == "como tá?")

    tv.reset_mock()
    bot.handle_update(update_voice(duration=apply_bot.MAX_VOICE_SECONDS + 1))
    test("Too long audio is refused", not tv.called and "longo demais" in bot.said[-1][0])

    tv.return_value = "[BLANK_AUDIO]"
    with mock.patch.object(bot, "handle_text") as ht:
        bot.handle_update(update_voice())
    test("Silence is not sent on as text", not ht.called and "Não ouvi nada" in bot.said[-1][0])

    tv.side_effect = RuntimeError("could not download")
    bot.handle_update(update_voice())
    test("Transcribe error is reported", "Não consegui entender" in bot.said[-1][0])

    tv.reset_mock()
    bot.said.clear()
    bot.handle_update(update_voice(chat_id=99))
    test("Voice from strangers is ignored", not tv.called and not bot.said)

with mock.patch("apply_bot.voice_problem", return_value="whisper-cli não está instalado"), \
        mock.patch("apply_bot.transcribe_voice") as tv, mock.patch("apply_bot.notifier.call"):
    bot = SyncBot(cfg)
    bot.handle_update(update_voice())
    test("Missing whisper is explained", not tv.called and "whisper-cli" in bot.said[-1][0])

no_voice = Config(**{**cfg.__dict__, "whisper_bin": "/nope/whisper-cli"})
test("voice_problem finds missing whisper", "whisper-cli" in apply_bot.voice_problem(no_voice))
no_model = Config(**{**cfg.__dict__, "whisper_bin": "/bin/echo", "ffmpeg_bin": "/bin/echo",
                     "whisper_model": tmp / "missing.bin"})
test("voice_problem finds missing model", "modelo" in apply_bot.voice_problem(no_model))

# The audio must not stay on disk, also when a step fails
seen_dirs = []


def fake_run(cmd, **kw):
    seen_dirs.append(Path(cmd[cmd.index("-i") + 1]).parent if "-i" in cmd else Path(cmd[cmd.index("-f") + 1]).parent)
    if "-f" in cmd:
        return mock.Mock(stdout="  muda o salário\n para 7k \n")
    return mock.Mock()


audio = mock.Mock(content=b"OggS fake")
with mock.patch("apply_bot.notifier.call", return_value={"result": {"file_path": "voice/f.oga"}}), \
        mock.patch("apply_bot.notifier._token", return_value="T"), \
        mock.patch("apply_bot.requests.get", return_value=audio), \
        mock.patch("apply_bot.subprocess.run", side_effect=fake_run):
    text = apply_bot.transcribe_voice(cfg, "v1")
test("Transcript is cleaned", text == "muda o salário para 7k", text)
test("Audio folder deleted after use", seen_dirs and not seen_dirs[0].exists())

seen_dirs.clear()
with mock.patch("apply_bot.notifier.call", return_value={"result": {"file_path": "voice/f.oga"}}), \
        mock.patch("apply_bot.notifier._token", return_value="T"), \
        mock.patch("apply_bot.requests.get", return_value=audio), \
        mock.patch("apply_bot.subprocess.run", side_effect=[mock.Mock(), apply_bot.subprocess.CalledProcessError(1, "w")]) as run:
    try:
        apply_bot.transcribe_voice(cfg, "v1")
    except apply_bot.subprocess.CalledProcessError:
        pass
    wav_dir = Path(run.call_args_list[0].args[0][-1]).parent
test("Audio folder deleted on error too", not wav_dir.exists())

with mock.patch("apply_bot.notifier.call", return_value={"result": {"file_path": "voice/f.oga"}}), \
        mock.patch("apply_bot.notifier._token", return_value="SECRET"), \
        mock.patch("apply_bot.requests.get", side_effect=apply_bot.requests.ConnectionError("https://x/botSECRET/f")):
    try:
        apply_bot.transcribe_voice(cfg, "v1")
        err = ""
    except RuntimeError as e:
        err = str(e)
test("Download error hides the bot token", err and "SECRET" not in err, err)


# ─────────────────────────────────────────────
print("\n━━━ Restart Tests ━━━")

rcfg = Config(**{**cfg.__dict__, "home": Path(tempfile.mkdtemp())})
with mock.patch("apply_bot.ensure_chrome"), mock.patch("apply_bot.notifier.call"), \
        mock.patch("apply_bot.run_claude") as rc:
    bot = SyncBot(rcfg)
    rc.return_value = fake_result("ready")
    bot.handle_update(update_msg("/candidatar https://jobs.example.com/initech/1"))
    bot.app.session_id, bot.app.stage = "sess-9", "review"
    bot.app.report = {"company": "Initech", "role": "Sr. Fullstack AI Engineer", "answers": []}
    bot.save_app()
    test("Open application saved to disk", bot.app_path.exists())
    old_id = bot.app.id

with mock.patch("apply_bot.chrome_running", return_value=True):
    bot2 = SyncBot(rcfg)
    bot2.restore_app()
test("Restart brings the application back", bot2.app and bot2.app.id == old_id and bot2.app.session_id == "sess-9")
test("Owner is told, with review buttons", "Reiniciei" in bot2.said[-1][0] and "Initech" in bot2.said[-1][0]
     and bot2.said[-1][1]["inline_keyboard"][0][0]["callback_data"] == f"submit:{old_id}")
with mock.patch("apply_bot.run_claude") as rc, mock.patch("apply_bot.ensure_chrome"), mock.patch("apply_bot.notifier.call"):
    rc.return_value = fake_result("ready", screenshot="review-2.png")
    bot2.handle_update(update_cb(f"edit:{old_id}"))
    test("Old buttons work after restart", bot2.app.stage == "editing")
    bot2.handle_update(update_msg("fala que eu uso LLMs todo dia"))
    test("Edit after restart resumes the Claude session", rc.call_args.args[3] == "sess-9")

bot2.app.stage = "submitting"
bot2.save_app()
with mock.patch("apply_bot.chrome_running", return_value=True):
    bot3 = SyncBot(rcfg)
    bot3.restore_app()
test("Restart during submit: warn, never auto-submit", bot3.app.stage == "review" and "envio" in bot3.said[-1][0])
with mock.patch("apply_bot.chrome_running", return_value=False):
    bot4 = SyncBot(rcfg)
    bot4.restore_app()
test("Chrome gone: says the form is lost", "fechou" in bot4.said[-1][0])

with mock.patch("apply_bot.notifier.call"):
    bot4.handle_update(update_msg("/cancelar"))
test("Cancel removes the saved application", not bot4.app_path.exists())
bot5 = SyncBot(rcfg)
bot5.restore_app()
test("Nothing to restore → quiet", bot5.app is None and not bot5.said)
bot5.app_path.write_text("{broken")
bot5.restore_app()
test("Broken file is dropped", bot5.app is None and not bot5.app_path.exists())


# ─────────────────────────────────────────────
print("\n━━━ Search / History Tests ━━━")

with mock.patch("apply_bot.notifier.call"), mock.patch("apply_bot.threading.Thread") as thread:
    bot = SyncBot(cfg)
    bot.handle_update(update_msg("/procurar"))
    test("/procurar starts a background search", thread.called and bot.searching and "Procurando" in bot.said[-1][0])
    bot.handle_update(update_msg("/procurar"))
    test("Only one search at a time", thread.call_count == 1 and "Já estou procurando" in bot.said[-1][0])

import job_search  # noqa: E402
from rn_linkedin_scraper import Opportunity  # noqa: E402

opp = Opportunity(title="RN", result_type="job", company_or_author="Acme", location="Remote",
                  url="https://www.linkedin.com/jobs/view/900/", snippet="", relevance_score=90, job_id="900")
with mock.patch("job_search.run", return_value=([opp], [opp], 30)), \
        mock.patch("apply_bot.notifier.notify_new") as nn:
    bot.run_search()
headers = [c.kwargs["header"] for c in nn.call_args_list]
test("New and again sent apart", len(headers) == 2 and "com match" in headers[0] and "🔁" in headers[1], str(headers))
test("Search flag cleared", not bot.searching)
with mock.patch("job_search.run", return_value=([], [], 30)), mock.patch("apply_bot.notifier.notify_new") as nn:
    bot.run_search()
test("Nothing found is told", not nn.called and "Nenhuma nova" in bot.said[-1][0])
with mock.patch("job_search.run", side_effect=RuntimeError("linkedin down")):
    bot.run_search()
test("Search error is told and cleared", "falhou" in bot.said[-1][0] and not bot.searching)

hist = Config(**{**cfg.__dict__, "home": Path(tempfile.mkdtemp())})
bot = SyncBot(hist)
bot.handle_update(update_msg("/aplicadas"))
test("Empty history", "nenhuma" in bot.said[-1][0])
(hist.home / "applications.jsonl").write_text(json.dumps(
    {"at": "2026-10-14T15:37:16+00:00", "url": "https://www.linkedin.com/jobs/view/4478468098/",
     "status": "submitted", "company": "Globex", "role": "RN <Engineer>"}) + "\n")
bot.handle_update(update_msg("/aplicadas"))
text, kb = bot.said[-1]
test("Lists applied jobs", "Globex" in text and "RN &lt;Engineer&gt;" in text, text)
data = kb["inline_keyboard"][0][0]["callback_data"]
test("Trash button per job", data.startswith("forget:"))
bot.handle_update(update_cb(data))
test("Button removes the job", "Tirei do histórico" in bot.said[-1][0] and job_search.submitted(hist.home) == [])
bot.handle_update(update_cb(data))
test("Second tap is harmless", "já não está" in bot.said[-1][0])

with mock.patch("apply_bot.notifier.call"), mock.patch("apply_bot.classify_intent") as ci:
    bot = SyncBot(cfg)
    with mock.patch.object(bot, "start_search") as ss, mock.patch.object(bot, "show_applied") as sa:
        ci.return_value = {"action": "search"}
        bot.route_free_text("procura vaga pra mim")
        ci.return_value = {"action": "applied"}
        bot.route_free_text("quais vagas apliquei?")
    test("Voice/text 'procura vaga' searches", ss.called)
    test("Voice/text 'quais apliquei' shows history", sa.called)


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
print("\n━━━ Auto-apply Tests ━━━")

from rn_linkedin_scraper import Opportunity as _Opp, ResultType as _RT


def auto_opp(url, score):
    o = _Opp(title="RN Engineer", result_type=_RT.JOB, company_or_author="Acme", location="Remote",
             url=url, snippet="")
    o.relevance_score = score
    return o


acfg = Config(**{**cfg.__dict__, "home": tmp / "auto-home"})
with mock.patch("apply_bot.ensure_chrome"), mock.patch("apply_bot.notifier.call"), \
        mock.patch("apply_bot.run_claude") as rc:
    bot = SyncBot(acfg)
    bot.queue_auto([auto_opp("https://www.linkedin.com/jobs/view/1111111111/", 100),
                    auto_opp("https://www.linkedin.com/jobs/view/2222222222/", 99)])
    test("Only 100-pt jobs queued", bot.auto_queue == ["https://www.linkedin.com/jobs/view/1111111111/"], str(bot.auto_queue))
    bot.queue_auto([auto_opp("https://www.linkedin.com/jobs/view/1111111111/?ref=x", 100)])
    test("Same job not queued twice", len(bot.auto_queue) == 1)

    rc.side_effect = [fake_result("ready"), fake_result("submitted", screenshot="submitted.png")]
    bot.last_search = apply_bot.time.time()  # no timed search in this test
    bot.tick_auto()
    test("Complete form sent without ✅", bot.app is None and "SUBMIT NOW" in bot.prompts[-1])
    test("Auto send logged", "1111111111" in (acfg.home / "applications.jsonl").read_text())
    test("Owner told it was sent", any("enviada" in t for t, _ in bot.said))
    bot.queue_auto([auto_opp("https://www.linkedin.com/jobs/view/1111111111/", 100)])
    test("Sent job never re-queued", not bot.auto_queue)

    rc.side_effect = [fake_result("ready", missing=["Salary?"])]
    bot.queue_auto([auto_opp("https://www.linkedin.com/jobs/view/3333333333/", 100)])
    bot.tick_auto()
    test("Missing answers → waits for ✅", bot.app and bot.app.stage == "review"
         and "SUBMIT NOW" not in bot.prompts[-1])
    bot.queue_auto([auto_opp("https://www.linkedin.com/jobs/view/4444444444/", 100)])
    bot.tick_auto()
    test("One application at a time", bot.app.url.endswith("/3333333333/") and len(bot.auto_queue) == 1)
    bot.handle_update(update_msg("/cancelar"))

    rc.side_effect = [fake_result("skip")]
    bot.tick_auto()
    test("Profile skip drops auto job", bot.app is None and "skipped" in (acfg.home / "applications.jsonl").read_text())

    bot.paused = True
    bot.queue_auto([auto_opp("https://www.linkedin.com/jobs/view/5555555555/", 100)])
    bot.tick_auto()
    test("Paused → no auto apply", bot.app is None and len(bot.auto_queue) == 1)
    bot.paused = False

    with mock.patch.object(bot, "start_search") as ss:
        bot.auto_queue.clear()
        bot.last_search = 0
        bot.tick_auto()
        test("Timed quiet search", ss.call_args == mock.call(quiet=True))

    off = SyncBot(Config(**{**acfg.__dict__, "auto_score": 0}))
    off.queue_auto([auto_opp("https://www.linkedin.com/jobs/view/6666666666/", 100)])
    test("APPLY_AUTO_SCORE=0 turns it off", not off.auto_queue)

    rc.side_effect = [fake_result("ready")]
    bot.handle_update(update_msg("/candidatar https://x.com/manual"))
    test("Manual application still needs ✅", bot.app and bot.app.stage == "review"
         and "SUBMIT NOW" not in bot.prompts[-1])
    bot.handle_update(update_msg("/cancelar"))


# ─────────────────────────────────────────────
print("\n━━━ Notifier Button Tests ━━━")

from rn_linkedin_scraper import Opportunity, ResultType

opps = [
    Opportunity(title="React Native Engineer at a very long company name", result_type=ResultType.JOB,
                company_or_author="X", location="Remote", url="u1", snippet="", job_id="4475865328"),
    Opportunity(title="Hiring post", result_type=ResultType.POST, company_or_author="Y",
                location="", url="u2", snippet=""),
]
btn = notifier.apply_button(opps[0])["inline_keyboard"][0][0]
test("Button says Candidatar", btn["text"] == "📝 Candidatar")
test("Callback carries job ID", btn["callback_data"] == "apply:4475865328")
test("Callback under 64 bytes", len(btn["callback_data"].encode()) <= 64)
test("Post gets a Candidatar button",
     notifier.apply_button(opps[1])["inline_keyboard"][0][0]["callback_data"] == "applypost")
opps[1].apply_url = "https://www.linkedin.com/jobs/view/4471234567/"
test("Post linking a LinkedIn job uses its ID",
     notifier.apply_button(opps[1])["inline_keyboard"][0][0]["callback_data"] == "apply:4471234567")


def tg_message(html_text):
    """What Telegram sends back for an HTML message: plain text + text_link
    entities with UTF-16 offsets (built the same way Telegram does)."""
    import re as _re
    text, ents, pos = "", [], 0
    for m in _re.finditer(r'<a href="([^"]+)">(.*?)</a>|<[^>]+>', html_text):
        text += html.unescape(html_text[pos:m.start()])
        if m.group(1):
            label = html.unescape(m.group(2))
            ents.append({"type": "text_link", "url": html.unescape(m.group(1)),
                         "offset": len(text.encode("utf-16-le")) // 2,
                         "length": len(label.encode("utf-16-le")) // 2})
            text += label
        pos = m.end()
    text += html.unescape(html_text[pos:])
    return {"chat": {"id": 42}, "text": text, "entities": ents}


import html
post = Opportunity(title="🚀 WE’RE HIRING: Senior Mobile 🔥 Engineer", result_type=ResultType.POST,
                   company_or_author="Tamer 😀 Omar", location="Not specified",
                   url="https://www.linkedin.com/posts/tamer_hiring-activity-7380000000000000000-abcd",
                   snippet="", apply_url="https://jobs.lever.co/acme/123?x=1&y=2", apply_email="hr@acme.com")
alert = notifier.format_opportunity(post, 3)
test("Alert shows apply link and email", notifier.APPLY_LINK_LABEL in alert and "hr@acme.com" in alert)
test("Bot reads apply link from alert (emoji offsets)",
     apply_bot.post_apply_url(tg_message(alert)) == "https://jobs.lever.co/acme/123?x=1&y=2",
     apply_bot.post_apply_url(tg_message(alert)))
post.apply_url = ""
test("No apply link → bot opens the post",
     apply_bot.post_apply_url(tg_message(notifier.format_opportunity(post, 3))) == post.url)
test("Old message without links → empty", apply_bot.post_apply_url({"date": 0}) == "")

with mock.patch("apply_bot.ensure_chrome"), mock.patch("apply_bot.notifier.call"), \
        mock.patch("apply_bot.run_claude") as rc:
    bot = SyncBot(cfg)
    rc.return_value = fake_result("ready")
    post.apply_url = "https://jobs.ashbyhq.com/acme/9"
    cb = update_cb("applypost")
    cb["callback_query"]["message"] = tg_message(notifier.format_opportunity(post, 1))
    bot.handle_update(cb)
    test("Post button applies via its link", bot.app and bot.app.url == "https://jobs.ashbyhq.com/acme/9")
    bot.handle_update(update_msg("/cancelar"))
    bot.handle_update(update_cb("applypost"))
    test("Post button without links asks for the link", "Não achei o link" in bot.said[-1][0])
test("Fill prompt knows posts", "LinkedIn POST" in apply_bot.FILL_PROMPT)


# ─────────────────────────────────────────────
print(f"\n{'━' * 50}")
total = results["passed"] + results["failed"]
print(f"Results: {results['passed']}/{total} passed", end="")
if results["failed"]:
    print(f"  ({results['failed']} FAILED)")
    sys.exit(1)
print("  ✓ All tests passed!")
