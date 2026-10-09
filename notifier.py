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
import logging
import os
import sys
import time

import requests
from dotenv import load_dotenv

from rn_linkedin_scraper import Opportunity

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


def _call(method: str, payload: dict, retries: int = 3) -> dict:
    url = TELEGRAM_API.format(token=_token(), method=method)
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, timeout=15)
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


def send_message(text: str):
    """Send an HTML-formatted message, split into chunks under Telegram's limit."""
    for chunk in split_message(text):
        _call("sendMessage", {
            "chat_id": _chat_id(),
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        time.sleep(0.5)  # stay well under 1 msg/sec per chat


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


def format_opportunity(opp: Opportunity) -> str:
    e = html.escape
    lines = [f'<b>{e(opp.title)}</b> · {round(opp.relevance_score)} pts']
    meta = [opp.company_or_author]
    if opp.location and opp.location != "Not specified":
        meta.append(opp.location)
    lines.append(e(" · ".join(meta)))
    extra = [x for x in (
        f"Posted {opp.posted_at}" if opp.posted_at else "",
        opp.seniority if opp.seniority not in ("", "Not Applicable") else "",
        opp.employment_type,
        opp.applicants,
    ) if x]
    if extra:
        lines.append(e(" · ".join(extra)))
    lines.append(f'<a href="{e(opp.url, quote=True)}">Open on LinkedIn</a>')
    return "\n".join(lines)


def format_digest(opportunities: list[Opportunity], header: str) -> str:
    parts = [f"<b>{html.escape(header)}</b>"]
    parts.extend(format_opportunity(o) for o in opportunities)
    return "\n\n".join(parts)


def notify_new(opportunities: list[Opportunity], header: str = None):
    if not opportunities:
        return
    n = len(opportunities)
    header = header or f"🔔 {n} new job{'s' if n != 1 else ''}"
    send_message(format_digest(opportunities, header))


def print_chat_ids():
    """Print chat IDs of everyone who recently messaged the bot."""
    data = _call("getUpdates", {})
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
