#!/usr/bin/env python3
"""
Tests for the Mike inbox (shared/mike.py) and its hook in shared/telegram.py.
No network and no real push: Popen and the Telegram API are mocked.
"""

import io
import json
import os
import sys
import tempfile
import threading
import time
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from shared import mike, telegram

PASS = "✓"
FAIL = "✗"
results = {"passed": 0, "failed": 0}


def test(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results["passed" if condition else "failed"] += 1
    print(f"  {status} {name}" + (f"  ({detail})" if detail and not condition else ""))


ALERT = ('<b>RN Engineer</b> · Acme\n<a href="https://example.com/apply?a=1&amp;b=2">Link para candidatar</a>'
         ' · <a href="https://linkedin.com/posts/x">Abrir no LinkedIn</a>')
KEYBOARD = telegram.buttons([[("📝 Candidatar", "applypost")], [("✅ Enviar", "submit:ab12"), ("❌", "cancel:ab12")]])

print("\nmike: text and buttons")
text, links = mike.plain(ALERT)
test("tags removed", "<b>" not in text and "RN Engineer" in text)
test("link kept as label (url), &amp; decoded", "Link para candidatar (https://example.com/apply?a=1&b=2)" in text)
test("links map", links.get("Link para candidatar") == "https://example.com/apply?a=1&b=2")
btns = mike.buttons_of(KEYBOARD)
test("buttons numbered in order", [(b["n"], b["dado"]) for b in btns] == [(1, "applypost"), (2, "submit:ab12"), (3, "cancel:ab12")])
test("no keyboard = no buttons", mike.buttons_of(None) == [])

with tempfile.TemporaryDirectory() as d:
    apns_script = os.path.join(d, "apns.py")
    open(apns_script, "w").close()
    env = {"MIKE_INBOX": d, "MIKE_OPENCLAW": "/bin/echo", "MIKE_BOT": "vagas", "MIKE_APNS": apns_script,
           "MIKE_BOT_AGENTS": os.path.join(d, "agentes")}
    with mock.patch.dict(os.environ, env), mock.patch.object(mike.subprocess, "Popen") as popen:
        print("\nmike: inbox and push")
        mike.post(ALERT, KEYBOARD)
        mike.post("<i>segunda</i>")
        items = mike.read("vagas")
        test("two messages saved", len(items) == 2 and items[1]["texto"] == "segunda")
        test("only one push inside the minute (web + app)", popen.call_count == 2, str(popen.call_count))
        params = json.loads(popen.call_args_list[0][0][0][-1])
        app = popen.call_args_list[1][0][0]
        test("app push opens the bot", app[-2:] == ["--abrir", "bot:vagas"] and "Mike · vagas" in app, str(app))
        os.makedirs(os.path.join(d, "agentes", "vagas"))
        open(os.path.join(d, "agentes", "vagas", "IDENTITY.md"), "w").close()
        popen.reset_mock()
        mike._push_app("vagas", "x")
        test("a bot with a character sends no raw app push", popen.call_count == 0, str(popen.call_count))
        test("push has bot title and plain body", params["title"] == "Mike · vagas" and "<b>" not in params["body"])

        print("\nmike: requests to the bot")
        mike.ask("vagas", {"texto": "oi"})
        mike.ask("vagas", {"dado": "cancel:ab12"})
        got = mike.take_requests("vagas")
        test("requests in order, then gone", got == [{"texto": "oi"}, {"dado": "cancel:ab12"}]
             and mike.take_requests("vagas") == [])

        print("\nmike: CLI")
        mike.REPLY_WAIT_SECONDS = 2

        def bot_answers():
            # play the bot: take the request and write a reply
            for _ in range(40):
                reqs = mike.take_requests("vagas")
                if reqs:
                    mike.post(f"recebi {json.dumps(reqs[0], ensure_ascii=False)}")
                    return
                time.sleep(0.05)

        worker = threading.Thread(target=bot_answers)
        worker.start()
        out = io.StringIO()
        with redirect_stdout(out):
            mike.main(["botao", "vagas#1", "1"])
        worker.join()
        test("applypost button sends the apply link as text",
             'recebi {"texto": "https://example.com/apply?a=1&b=2"}' in out.getvalue(), out.getvalue())

        worker = threading.Thread(target=bot_answers)
        worker.start()
        out = io.StringIO()
        with redirect_stdout(out):
            mike.main(["botao", "vagas#1", "2"])
        worker.join()
        test("other button sends its data", '"dado": "submit:ab12"' in out.getvalue(), out.getvalue())

        out = io.StringIO()
        with redirect_stdout(out):
            code = mike.main(["botao", "vagas#99", "1"])
        test("unknown message refused", code == 2)
        out = io.StringIO()
        with redirect_stdout(out):
            mike.main(["ler", "vagas", "2"])
        test("ler shows ids", "[vagas#" in out.getvalue())

        print("\ntelegram hook")
        with mock.patch.dict(os.environ, {"TELEGRAM_OFF": "true", "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}), \
                mock.patch.object(telegram, "call") as call:
            before = len(mike.read("vagas"))
            telegram.send_message("<b>só Mike</b>")
            test("TELEGRAM_OFF: message goes to Mike", len(mike.read("vagas")) == before + 1)
            test("TELEGRAM_OFF: Telegram not called", call.call_count == 0)
            test("TELEGRAM_OFF: still configured", telegram.is_configured())
        with mock.patch.dict(os.environ, {"TELEGRAM_OFF": "", "TELEGRAM_CHAT_ID": "1", "TELEGRAM_BOT_TOKEN": "t"}), \
                mock.patch.object(telegram, "call", return_value={"result": {}}) as call, \
                mock.patch.object(telegram.time, "sleep"):
            before = len(mike.read("vagas"))
            telegram.send_message("nos dois")
            test("parallel week: both Telegram and Mike", call.call_count == 1 and len(mike.read("vagas")) == before + 1)

with mock.patch.dict(os.environ, {"MIKE_INBOX": ""}):
    test("off without MIKE_INBOX", mike.post("x") == {} and mike.take_requests("vagas") == [])

print(f"\n{results['passed']} passed, {results['failed']} failed")
if results["failed"]:
    sys.exit(1)
