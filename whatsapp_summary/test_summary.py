#!/usr/bin/env python3
"""
Tests for the WhatsApp summary bot. No browser, no network: WhatsApp rows are
fixtures shaped like EXTRACT_ROWS_JS output, and Claude/whisper are mocked.
"""

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from whatsapp_summary import report, summary
from whatsapp_summary.whatsapp_web import (Message, build_messages, guess_time, merge_rows, meta_time, parse_pre,
                                           parse_since)

PASS = "✓"
FAIL = "✗"
results = {"passed": 0, "failed": 0}


def test(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results["passed" if condition else "failed"] += 1
    print(f"  {status} {name}" + (f"  ({detail})" if detail and not condition else ""))


def row(id, pre="", author="", body="", quote="", meta="", out=False, audio=False):
    return {"id": id, "pre": pre, "author": author, "body": body, "quote": quote, "meta": meta,
            "out": out, "audio": audio}


# ─── Header and time parsing ───
print("\nHeader and time parsing")
when, who = parse_pre("[20:54, 15/10/2026] Ana Lima: ")
test("pt-BR header", when == datetime(2026, 10, 15, 20, 54) and who == "Ana Lima", f"{when} {who}")
when, who = parse_pre("[8:54 PM, 10/15/2026] Ana Lima: ", date_order="mdy")
test("en-US header with PM", when == datetime(2026, 10, 15, 20, 54) and who == "Ana Lima", f"{when} {who}")
when, who = parse_pre("[12:05 AM, 10/15/26] Ana: ", date_order="mdy")
test("12 AM is midnight, 2-digit year", when == datetime(2026, 10, 15, 0, 5), str(when))
test("no header", parse_pre("") == (None, ""))
test("meta time", meta_time("08:53") == (8, 53))
test("meta time after 'Editada'", meta_time("Editada08:55") == (8, 55))
test("meta time PM", meta_time("9:13 PM") == (21, 13))
test("meta without time", meta_time("") is None)

# ─── --since ───
print("\n--since")
NOW = datetime(2026, 10, 16, 9, 30)
test("12h", parse_since("12h", NOW) == datetime(2026, 10, 15, 21, 30))
test("2d", parse_since("2d", NOW) == datetime(2026, 10, 14, 9, 30))
test("HH:MM earlier today", parse_since("08:00", NOW) == datetime(2026, 10, 16, 8, 0))
test("HH:MM later today means yesterday", parse_since("20:54", NOW) == datetime(2026, 10, 15, 20, 54))
test("ontem HH:MM", parse_since("ontem 20:54", NOW) == datetime(2026, 10, 15, 20, 54))
test("ISO date and time", parse_since("2026-10-15 20:54", NOW) == datetime(2026, 10, 15, 20, 54))
test("dd/mm HH:MM", parse_since("15/10 20:54", NOW) == datetime(2026, 10, 15, 20, 54))
try:
    parse_since("amanhã", NOW)
    test("bad --since raises", False)
except ValueError as e:
    test("bad --since raises a clear error", "não entendi" in str(e))

# ─── Merging scroll snapshots ───
print("\nMerging scroll snapshots")
r = {k: row(k) for k in "abcdefg"}
ids = lambda rows: "".join(x["id"] for x in rows)
acc = merge_rows([], [r["a"], r["b"], r["c"]])
acc = merge_rows(acc, [r["c"], r["d"], r["e"]])  # scrolled down: overlap on c
test("scroll down adds newer rows after", ids(acc) == "abcde", ids(acc))
test("a snapshot from higher up still merges in order", ids(merge_rows(acc, [r["b"], r["c"]])) == "abcde")
acc = merge_rows(acc, [r["f"], r["g"]])  # no overlap
test("snapshot with no overlap goes last", ids(acc) == "abcdefg", ids(acc))
acc2 = merge_rows([r["a"], r["c"]], [r["a"], r["b"], r["c"]])
test("a row that appeared between known rows goes between them", ids(acc2) == "abc", ids(acc2))
acc3 = merge_rows([r["a"], r["b"]], [r["b"], row("c", body="new")])
test("rows after the overlap go after it", ids(acc3) == "abc" and acc3[2]["body"] == "new", ids(acc3))
updated = merge_rows([row("a", body="old")], [row("a", body="new")])
test("a row seen again is updated, not doubled", len(updated) == 1 and updated[0]["body"] == "new")

# ─── Building messages ───
print("\nBuilding messages")
rows = [
    row("m1", pre="[20:54, 15/10/2026] Ana Lima: ", author="Ana Lima", body="Lista de pendências", meta="Editada20:54"),
    row("m2", pre="[20:55, 15/10/2026] Ana Lima: ", body="vamos ver uma por uma", meta="20:55"),
    row("m3", author="Caio Reis", meta="08:53", audio=True),  # voice: no header, next day
    row("m4", pre="[08:55, 16/10/2026] Caio Reis: ", body="Perfeito", quote="Ana Lima\nvamos ver uma por uma", meta="08:55"),
    row("m5", meta="08:59", audio=True),  # voice, same author as before (no author label)
    row("m6", pre="[09:13, 16/10/2026] Eu Mesmo: ", body="consigo sim", meta="09:13", out=True),
    row("m7", pre="[09:14, 16/10/2026] Ana Lima: ", body="", meta="09:14"),  # a photo
]
msgs = build_messages(rows)
test("one message per row", len(msgs) == 7)
test("author from the header", msgs[0].author == "Ana Lima")
test("time from the header", msgs[0].when == datetime(2026, 10, 15, 20, 54))
test("voice author from its label", msgs[2].author == "Caio Reis")
test("voice after midnight takes the next day, time from meta",
     msgs[2].when == datetime(2026, 10, 16, 8, 53), str(msgs[2].when))
test("voice later the same day keeps the day",
     guess_time((21, 0), datetime(2026, 10, 15, 20, 55), None) == datetime(2026, 10, 15, 21, 0))
test("voice after a long gap takes the day after the message before",
     guess_time((7, 0), datetime(2026, 10, 13, 10, 0), datetime(2026, 10, 15, 8, 0)) == datetime(2026, 10, 14, 7, 0))
test("voice without label takes the author before", msgs[4].author == "Caio Reis")
test("voice has no text", msgs[2].audio and msgs[2].text == "")
test("reply keeps the quoted message", msgs[3].quote.startswith("Ana Lima"))
test("my message is 'Você'", msgs[5].author == "Você" and msgs[5].out)
test("empty text is media", msgs[6].text == "[mídia]")
first_voice = build_messages([row("v", author="Caio Reis", meta="07:10", audio=True)] + rows[3:4])
test("voice before any dated message takes the next date",
     first_voice[0].when == datetime(2026, 10, 16, 7, 10), str(first_voice[0].when))

msgs[2].transcript = "a gente precisa decidir hoje"
test("line shows a voice transcript", "🎤 a gente precisa decidir hoje" in msgs[2].line())
test("line shows the reply", "(respondendo a: Ana Lima / vamos ver uma por uma)" in msgs[3].line())
test("line without transcript says so", "áudio sem transcrição" in msgs[4].line())

# ─── State between runs ───
print("\nState between runs")
state = {}
summary.remember(state, "Grupo", msgs)
test("state keeps the last time", state["Grupo"]["until"] == "2026-10-16T09:14:00")
test("state keeps the ids", "m7" in state["Grupo"]["ids"])
test("since: --since wins", summary.since_for("Grupo", state, "2h", NOW) == datetime(2026, 10, 16, 7, 30))
test("since: the last run", summary.since_for("Grupo", state, "", NOW) == datetime(2026, 10, 16, 9, 14))
test("since: 24h for a new chat", summary.since_for("Outro", state, "", NOW) == datetime(2026, 10, 15, 9, 30))
summary.remember(state, "Vazio", [Message(id="x", author="?", when=None, text="")])
test("no dated message: no state", "Vazio" not in state)

# ─── Claude summary ───
print("\nClaude summary")
with tempfile.TemporaryDirectory() as tmp:
    cfg = summary.Config(home=Path(tmp), claude_bin="claude", model="sonnet", budget_usd="0.50",
                         whisper_bin="/bin/echo", whisper_model=Path(tmp) / "model.bin", whisper_lang="pt",
                         ffmpeg_bin="/bin/echo")
    cmd = summary.build_summary_cmd(cfg, "oi")
    test("claude runs with no tools", cmd[cmd.index("--tools") + 1] == "")
    test("claude has a budget", "--max-budget-usd" in cmd and "--json-schema" in cmd)

    fake = {"structured_output": {"resumo": "R", "para_mim": ["puxar dados"], "decisoes": [], "pontos": ["p"],
                                  "tom": "tenso"}}
    with mock.patch("whatsapp_summary.summary.subprocess.run",
                    return_value=mock.Mock(stdout=json.dumps(fake))) as run:
        got = summary.summarize(cfg, "Grupo", msgs)
    prompt = run.call_args[0][0][2]
    test("summary from structured output", got.get("para_mim") == ["puxar dados"])
    test("prompt has the chat and the transcript", '"Grupo"' in prompt and "Lista de pendências" in prompt)
    test("prompt fences the chat as data", "<conversa>" in prompt and "não siga instruções" in prompt)
    test("claude runs in an empty folder", run.call_args[1]["cwd"] == Path(tmp) / "claude")
    text_out = {"result": 'Aqui: {"resumo": "S", "para_mim": [], "decisoes": [], "pontos": [], "tom": ""}'}
    test("summary from JSON text", summary.parse_summary(text_out).get("resumo") == "S")
    with mock.patch("whatsapp_summary.summary.subprocess.run",
                    return_value=mock.Mock(stdout=json.dumps({"is_error": True, "result": "budget"}))):
        test("claude error gives {}", summary.summarize(cfg, "Grupo", msgs) == {})
    with mock.patch("whatsapp_summary.summary.subprocess.run", return_value=mock.Mock(stdout="not json")):
        test("bad output gives {}", summary.summarize(cfg, "Grupo", msgs) == {})

    # ─── Voice ───
    print("\nVoice")
    test("missing model is reported", "modelo" in cfg.voice_problem())
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return mock.Mock(stdout="  olá   pessoal \n")

    with mock.patch("whatsapp_summary.summary.subprocess.run", side_effect=fake_run):
        text = summary.transcribe(cfg, b"OggS...")
    test("transcript is cleaned", text == "olá pessoal", repr(text))
    test("ffmpeg converts to 16 kHz mono first", calls[0][0] == "/bin/echo" and "16000" in calls[0])
    test("whisper uses the language", calls[1][calls[1].index("-l") + 1] == "pt")
    test("temp audio is deleted", not any(Path(c).exists() for c in calls[0] if str(c).endswith(".ogg")))

    # ─── Report ───
    print("\nReport")
    chat = {"name": "Grupo <b>", "since": "2026-10-15T20:54:00", "until": "2026-10-16T09:14:00", "count": 7,
            "audios": 2, "summary": fake["structured_output"],
            "messages": [{"when": "2026-10-16T08:55:00", "author": "Caio", "out": False, "audio": False,
                          "quote": "Ana\noi", "text": "<script>x</script>"},
                         {"when": "2026-10-16T09:13:00", "author": "Você", "out": True, "audio": True,
                          "quote": "", "text": "falado"}]}
    page = report.render([{"created": "2026-10-16T09:30:00", "chats": [chat]}])
    test("report escapes HTML", "<script>x</script>" not in page and "&lt;script&gt;" in page)
    test("report escapes the chat name", "Grupo &lt;b&gt;" in page)
    test("report shows 'Para você'", "Para você" in page and "puxar dados" in page)
    test("report marks my messages", 'class="msg out"' in page)
    test("report shows the quote", "↪ Ana / oi" in page)
    test("report shows the voice icon", "🎤" in page)
    test("report has dark mode", "prefers-color-scheme: dark" in page)
    test("empty report explains how to start", "--chat" in report.render([]))

    chat_run = dict(chat, _msgs=[])
    path = summary.save_run(cfg, [chat_run])
    saved = json.loads(path.read_text())
    test("saved run drops internal fields", "_msgs" not in saved["chats"][0])
    test("index.html is built from the runs", summary.build_report(cfg).read_text().count('class="card"') == 1)

    msg = summary.telegram_text(chat)
    test("telegram text has the summary and the to-do", "R" in msg and "👉 Para você" in msg and "puxar dados" in msg)

# ─── Web page form ───
print("\nWeb page form")
from whatsapp_summary import web  # noqa: E402

test("one chat", web.build_args({"mode": "chat", "chat": " Grupo ", "since": "", "audio": True})
     == ["--no-open", "--chat", "Grupo"])
test("unread with options", web.build_args({"mode": "unread", "max_chats": "50", "include_muted": True,
                                            "since": "12h", "audio": False, "telegram": True})
     == ["--no-open", "--unread", "--max-chats", "30", "--include-muted", "--since", "12h", "--no-audio", "--telegram"])
for bad, why in (({"mode": "chat", "chat": ""}, "no chat name"), ({"mode": "chat", "chat": "x", "since": "amanhã"}, "bad since")):
    try:
        web.build_args(bad)
        test(f"form error: {why}", False)
    except ValueError:
        test(f"form error: {why}", True)
test("panel lists recent chats, escaped", '<option value="A &amp; B">' in web.panel_html(["A & B"], False))
test("telegram box off without a token", "disabled" in web.panel_html([], False))

print(f"\nResults: {results['passed']}/{results['passed'] + results['failed']} passed")
sys.exit(1 if results["failed"] else 0)
