#!/usr/bin/env python3
"""
Telegram notifier for new job opportunities.

Setup:
    1. Create a bot with @BotFather on Telegram and copy the token.
    2. Send any message to your new bot.
    3. Run `python notifier.py --get-chat-id` to print your chat ID.
    4. Put TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.
    5. Run `python notifier.py --test` to check it works.
"""

import argparse
import html
import json
import logging
import os
import sys
import time
from typing import Optional

import requests
from dotenv import load_dotenv

import focus
from rn_linkedin_scraper import Opportunity, _age_days_from_iso

log = logging.getLogger("notifier")

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
MAX_MESSAGE_CHARS = 4096  # Telegram hard limit per message


def _token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    return token


def _chat_id() -> str:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is not set (run: python notifier.py --get-chat-id)")
    return chat_id


def is_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def call(method: str, payload: dict, retries: int = 3, files: dict = None, timeout: int = 15) -> dict:
    """Call a Telegram Bot API method. `files` sends multipart (photos, documents)."""
    url = TELEGRAM_API.format(token=_token(), method=method)
    for attempt in range(retries):
        try:
            if files:
                for f in files.values():
                    f.seek(0)  # a retry must re-send the whole file
                # Multipart fields must be strings; nested JSON (reply_markup) is encoded
                form = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in payload.items()}
                resp = requests.post(url, data=form, files=files, timeout=60)
            else:
                resp = requests.post(url, json=payload, timeout=timeout)
        except requests.RequestException as e:
            # The URL contains the bot token, and request errors echo the URL
            log.warning("Telegram request failed (%s), retrying",
                        str(e).replace(_token(), "<redacted>"))
            time.sleep(2 ** attempt)
            continue
        data = resp.json() if resp.content else {}
        if resp.status_code == 429:
            # Telegram tells us exactly how long to wait
            wait = data.get("parameters", {}).get("retry_after", 5)
            log.warning("Telegram rate limit, waiting %ss", wait)
            time.sleep(wait)
            continue
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {data.get('description', resp.text)}")
        return data
    raise RuntimeError(f"Telegram {method} failed after {retries} attempts")


def send_message(text: str, reply_markup: dict = None) -> dict:
    """Send an HTML-formatted message, split into chunks under Telegram's limit.
    Buttons (reply_markup) go on the last chunk. Returns the last message."""
    chunks = split_message(text)
    message = {}
    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": _chat_id(),
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup and i == len(chunks) - 1:
            payload["reply_markup"] = reply_markup
        message = call("sendMessage", payload).get("result", {})
        time.sleep(0.5)  # stay well under 1 msg/sec per chat
    return message


def send_file(path: str, caption: str = "", reply_markup: dict = None) -> dict:
    """Send an image as a photo (inline preview). Telegram rejects very tall
    photos (full-page screenshots), so fall back to sending it as a document."""
    payload = {"chat_id": _chat_id(), "caption": caption[:1024], "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        with open(path, "rb") as f:
            return call("sendPhoto", payload, files={"photo": f}).get("result", {})
    except RuntimeError as e:
        log.info("sendPhoto failed (%s), sending as document", e)
        with open(path, "rb") as f:
            return call("sendDocument", payload, files={"document": f}).get("result", {})


def buttons(rows: list[list[tuple[str, str]]]) -> dict:
    """[[("label", "callback_data"), ...], ...] → Telegram inline keyboard."""
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


def split_message(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Split on blank lines so a job entry (and its HTML tags) is never cut in half."""
    chunks, current = [], ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = block[:limit]
    if current:
        chunks.append(current)
    return chunks


MIN_MONTHLY_USD = float(os.environ.get("WATCH_MIN_MONTHLY_USD", "") or 6000)
ABOUT_CHARS = 220


def apply_button(opp: Opportunity) -> Optional[dict]:
    """Candidatar button for one job. callback_data is capped at 64 bytes by
    Telegram, so it carries only the LinkedIn job ID (posts have none)."""
    if not opp.job_id:
        return None
    return buttons([[("📝 Candidatar", f"apply:{opp.job_id}")]])


def _k(value: float) -> str:
    return f"{value / 1000:.1f}k".replace(".0k", "k")


def format_salary(salary: str) -> str:
    """'$110,400.00/yr - $220,800.00/yr' → '$110,400.00/yr - $220,800.00/yr (≈ $9.2k–18.4k/mês)'
    plus a warning when even the top is below your monthly minimum."""
    if not salary:
        return "💰 salário não informado"
    line = f"💰 {html.escape(salary)}"
    monthly = focus.monthly_usd_range(salary)
    if monthly:
        low, high = monthly
        rng = f"${_k(low)}" if round(low) == round(high) else f"${_k(low)}–{_k(high)}"
        line += f" (≈ {rng}/mês)"
        if high < MIN_MONTHLY_USD:
            line += " ⚠️ abaixo do seu mínimo"
    return line


def _days_ago(days: float) -> str:
    d = int(days)
    if d <= 0:
        return "hoje"
    if d == 1:
        return "ontem"
    if d < 30:
        return f"há {d} dias"
    months = round(d / 30)
    return f"há ~{months} {'mês' if months == 1 else 'meses'}"


REPOST_NOTE_MIN_GAP_DAYS = 3


def format_age(opp: Opportunity) -> str:
    """'🕒 hoje' or '🕒 ontem · ♻️ vaga original há ~2 meses (repost)'."""
    listed = _age_days_from_iso(opp.posted_at)
    real = opp.original_age_days
    if listed is None and real is None:
        return ""
    line = f"🕒 {_days_ago(listed if listed is not None else real)}"
    if real is not None and real - (listed or 0) >= REPOST_NOTE_MIN_GAP_DAYS:
        line += f" · ♻️ vaga original {_days_ago(real)} (repost)"
    return line


def _about(opp: Opportunity) -> str:
    """First sentences of the description: what the job/company is about."""
    text = " ".join((opp.description or opp.snippet or "").split())
    if not text or text.lower().startswith(opp.title.lower()[:20]):
        return ""
    if len(text) <= ABOUT_CHARS:
        return text
    cut = text[:ABOUT_CHARS]
    end = max(cut.rfind(". "), cut.rfind("! "))
    return (cut[:end + 1] if end > 80 else cut.rsplit(" ", 1)[0] + "…")


def format_opportunity(opp: Opportunity, index: int = None) -> str:
    e = html.escape
    prefix = f"{index}. " if index is not None else ""
    kind = "" if opp.result_type == "job" else " · post"
    lines = [f"<b>{prefix}{e(opp.title)}</b>{kind} · {round(opp.relevance_score)} pts"]

    place = f"🏢 {e(opp.company_or_author)}"
    if opp.location and opp.location != "Not specified":
        place += f" · 📍 {e(opp.location)}"
    lines.append(place)

    if opp.result_type == "job" or opp.salary:
        lines.append(format_salary(opp.salary))

    text = " ".join([opp.title, opp.snippet, opp.description])
    contract = opp.contractor or focus.is_contractor(text, opp.employment_type)
    work = [x for x in (
        "Contractor" if contract and opp.employment_type.lower() != "contract" else "",
        opp.employment_type,
        opp.seniority if opp.seniority not in ("", "Not Applicable") else "",
        opp.applicants,
    ) if x]
    if work:
        lines.append("🧾 " + e(" · ".join(work)))

    age = format_age(opp)
    if age:
        lines.append(age)

    tags = focus.tech_tags(text)
    if tags:
        lines.append("🛠 " + e(", ".join(tags)))
    if focus.is_open_abroad(f"{opp.location} {text}"):
        lines.append("🌎 aceita LATAM / qualquer lugar")

    about = _about(opp)
    if about:
        lines.append(f"<i>{e(about)}</i>")

    source = "LinkedIn" if "linkedin.com" in opp.url else "a vaga"
    lines.append(f'<a href="{e(opp.url, quote=True)}">Abrir no {source}</a>')
    return "\n".join(lines)


def format_digest(opportunities: list[Opportunity], header: str) -> str:
    parts = [f"<b>{html.escape(header)}</b>"]
    parts.extend(format_opportunity(o, i) for i, o in enumerate(opportunities, 1))
    return "\n\n".join(parts)


def notify_new(opportunities: list[Opportunity], header: str = None):
    """A header, then one message per job with its own Candidatar button,
    so the button always sits right under the job it applies to."""
    if not opportunities:
        return
    n = len(opportunities)
    header = header or f"🔔 {n} new job{'s' if n != 1 else ''}"
    send_message(f"<b>{html.escape(header)}</b>")
    for i, opp in enumerate(opportunities, 1):
        send_message(format_opportunity(opp, i), reply_markup=apply_button(opp))


def print_chat_ids():
    """Print chat IDs of everyone who recently messaged the bot."""
    data = call("getUpdates", {})
    chats = {}
    for update in data.get("result", []):
        msg = update.get("message") or update.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name", "")
    if not chats:
        print("No messages found. Send any message to your bot on Telegram, then run this again.")
        return
    for chat_id, name in chats.items():
        print(f"TELEGRAM_CHAT_ID={chat_id}   ({name})")


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Telegram notifier helper")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--get-chat-id", action="store_true", help="Print your chat ID")
    group.add_argument("--test", action="store_true", help="Send a test message")
    args = parser.parse_args()

    try:
        if args.get_chat_id:
            print_chat_ids()
        else:
            send_message("✅ <b>Job Hunter</b> is connected. You will get new jobs here.")
            print("Test message sent.")
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
