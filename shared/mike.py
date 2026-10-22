#!/usr/bin/env python3
"""
Mike inbox: the bots also write their messages here, Pedro gets a push on the
Mike PWA, and he answers by talking to Mike. It replaces Telegram step by step.

Off unless MIKE_INBOX is set. shared/telegram.py calls post() on every send.

    python -m shared.mike ler [bot] [n]                 last messages (with ids like vagas#12)
    python -m shared.mike responder <bot> "texto"       send text to the bot, print its replies
    python -m shared.mike botao <bot>#<n> <botao>       press button <botao> (1, 2, ...) of message n

Config (environment variables):
    MIKE_INBOX       folder for the messages, e.g. /home/ia/mike/caixa
    MIKE_OPENCLAW    openclaw CLI used for the push (default: openclaw on PATH)
    TELEGRAM_OFF     true = do not send to Telegram anymore, only to Mike
"""

import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# Which bot is talking, from the module that runs (python -m <module>)
BOT_NAMES = {
    "apply_bot": "vagas",
    "job_hunter": "vagas",
    "daily.morning_brief": "brief",
    "daily.interview_prep": "entrevista",
    "whatsapp_summary": "whatsapp",
}
PUSH_GAP_SECONDS = 60  # a job digest is 15 messages: one push is enough
REPLY_WAIT_SECONDS = 25
APPLY_LINK_LABEL = "Link para candidatar"  # same label as job_hunter.notifier


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def enabled() -> bool:
    return bool(os.environ.get("MIKE_INBOX", "").strip())


def telegram_off() -> bool:
    return enabled() and _env_bool("TELEGRAM_OFF")


def inbox() -> Path:
    return Path(os.environ["MIKE_INBOX"]).expanduser()


def bot_name() -> str:
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    module = spec.name if spec else ""
    for prefix, bot in BOT_NAMES.items():
        if module.startswith(prefix):
            return bot
    return os.environ.get("MIKE_BOT", "bots")


def plain(text: str) -> tuple[str, dict]:
    """Telegram HTML → plain text. Links become "label (url)"; also returns {label: url}."""
    links = {}

    def link(m):
        label = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        url = html.unescape(m.group(1))
        links.setdefault(html.unescape(label), url)
        return f"{label} ({url})"

    text = re.sub(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', link, text or "", flags=re.S)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip(), links


def buttons_of(reply_markup: dict) -> list[dict]:
    rows = (reply_markup or {}).get("inline_keyboard") or []
    flat = [b for row in rows for b in row if b.get("callback_data")]
    return [{"n": i, "texto": b.get("text", ""), "dado": b["callback_data"]} for i, b in enumerate(flat, 1)]


def _messages_file(bot: str) -> Path:
    return inbox() / f"{bot}.jsonl"


def post(text: str, reply_markup: dict = None, file: str = "") -> dict:
    """Save one bot message in the inbox and push it (at most one push a minute per bot)."""
    if not enabled():
        return {}
    bot = bot_name()
    body, links = plain(text)
    item = {"hora": datetime.now().isoformat(timespec="seconds"), "bot": bot, "texto": body,
            "links": links, "botoes": buttons_of(reply_markup), "arquivo": file}
    inbox().mkdir(parents=True, exist_ok=True)
    with open(_messages_file(bot), "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    _push(bot, body)
    return item


def _push(bot: str, body: str):
    stamp = inbox() / f".push-{bot}"
    if stamp.exists() and time.time() - stamp.stat().st_mtime < PUSH_GAP_SECONDS:
        return
    cli = os.environ.get("MIKE_OPENCLAW") or shutil.which("openclaw")
    if not cli:
        return
    stamp.touch()
    env = dict(os.environ, PATH=f"{Path(cli).parent}:{os.environ.get('PATH', '')}")
    params = json.dumps({"title": f"Mike · {bot}", "body": body[:300]}, ensure_ascii=False)
    # In the background: the CLI takes seconds and a bot must never wait for a push
    subprocess.Popen([cli, "gateway", "call", "push.web.test", "--params", params],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
                     start_new_session=True)
    _push_app(bot, body)


def _push_app(bot: str, body: str):
    """Also to the iPhone app (APNs); a tap opens this bot in the Bots tab."""
    script = Path(os.environ.get("MIKE_APNS") or Path.home() / "mike/api/apns.py")
    if not script.is_file():
        return
    agents = Path(os.environ.get("MIKE_BOT_AGENTS") or Path.home() / "mike/bots-agentes")
    if (agents / bot / "IDENTITY.md").is_file():
        return  # this bot has a character: it sends the notice in its own words (mike-bots)
    subprocess.Popen(["/usr/bin/python3", str(script), "--titulo", f"Mike · {bot}", "--texto", body[:300],
                      "--abrir", f"bot:{bot}"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def read(bot: str) -> list[dict]:
    try:
        lines = _messages_file(bot).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


# ── Answers from Pedro (through Mike) to a bot ──

def _requests_dir(bot: str) -> Path:
    return inbox() / "entrada" / bot


def ask(bot: str, request: dict):
    """Queue a request for the bot: {"texto": ...} or {"dado": <callback_data>}."""
    folder = _requests_dir(bot)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{time.time():.6f}-{uuid.uuid4().hex[:6]}"
    tmp = folder / f".{name}.tmp"
    tmp.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    tmp.rename(folder / f"{name}.json")  # the bot only reads whole files


def take_requests(bot: str) -> list[dict]:
    """Called by the bot in its loop: returns and removes the waiting requests."""
    if not enabled():
        return []
    out = []
    for path in sorted(_requests_dir(bot).glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        path.unlink(missing_ok=True)
    return out


def _wait_replies(bot: str, before: int) -> list[dict]:
    end = time.time() + REPLY_WAIT_SECONDS
    seen = before
    while time.time() < end:
        now = len(read(bot))
        if now > seen:
            seen = now
            end = min(end, time.time() + 4)  # more lines may follow; stop when quiet
        time.sleep(1)
    return read(bot)[before:seen]


def _show(bot: str, index: int, item: dict) -> str:
    lines = [f"[{bot}#{index}] {item['hora'][5:16].replace('T', ' ')}  {item['texto']}"]
    for b in item.get("botoes", []):
        lines.append(f"    botão {b['n']}: {b['texto']}")
    return "\n".join(lines)


def main(argv: list[str] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not enabled():
        print("MIKE_INBOX não está definido")
        return 2
    if not argv or argv[0] not in ("ler", "responder", "botao"):
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]

    if cmd == "ler":
        bots = [args[0]] if args and not args[0].isdigit() else sorted(p.stem for p in inbox().glob("*.jsonl"))
        n = int(next((a for a in args if a.isdigit()), "5"))
        for bot in bots:
            items = read(bot)
            for i in range(max(0, len(items) - n), len(items)):
                print(_show(bot, i + 1, items[i]))
        return 0

    if cmd == "responder" and len(args) == 2:
        bot, text = args
        request = {"texto": text}
    elif cmd == "botao" and len(args) == 2 and "#" in args[0] and args[1].isdigit():
        bot, _, index = args[0].partition("#")
        items = read(bot)
        if not index.isdigit() or not 1 <= int(index) <= len(items):
            print("mensagem não existe")
            return 2
        item = items[int(index) - 1]
        button = next((b for b in item.get("botoes", []) if b["n"] == int(args[1])), None)
        if not button:
            print("botão não existe")
            return 2
        if button["dado"] == "applypost":
            # Telegram found the link in the alert itself; here the link is saved with the message
            links = item.get("links", {})
            url = links.get(APPLY_LINK_LABEL) or next((u for l, u in links.items() if l.startswith("Abrir no")), "")
            if not url:
                print("não achei o link desse post")
                return 2
            request = {"texto": url}
        else:
            request = {"dado": button["dado"]}
    else:
        print(__doc__)
        return 2

    before = len(read(bot))
    ask(bot, request)
    replies = _wait_replies(bot, before)
    if not replies:
        print(f"Pedido entregue ao bot {bot}. Ainda sem resposta; veja depois com: ler {bot}")
    for offset, item in enumerate(replies):
        print(_show(bot, before + offset + 1, item))
    return 0


if __name__ == "__main__":
    sys.exit(main())
