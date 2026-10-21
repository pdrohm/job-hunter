#!/usr/bin/env python3
"""
Telegram Bot API client shared by all bots: send messages, files and buttons.

Setup:
    1. Create a bot with @BotFather on Telegram and copy the token.
    2. Send any message to your new bot.
    3. Run `python -m shared.telegram --get-chat-id` to print your chat ID.
    4. Put TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.
    5. Run `python -m shared.telegram --test` to check it works.

Other bots pass their own token (`token=...`); the chat ID is the same.
"""

import argparse
import json
import logging
import os
import sys
import time

import requests
from dotenv import load_dotenv

log = logging.getLogger("telegram")

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
MAX_MESSAGE_CHARS = 4096  # Telegram hard limit per message


def _token(override: str = None) -> str:
    """The job bot's token, or another bot's (morning brief, interview prep)."""
    token = (override or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    return token


def _chat_id() -> str:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is not set (run: python -m shared.telegram --get-chat-id)")
    return chat_id


def is_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def call(method: str, payload: dict, retries: int = 3, files: dict = None, timeout: int = 15,
         token: str = None) -> dict:
    """Call a Telegram Bot API method. `files` sends multipart (photos, documents).
    `token` sends as another bot; the default is TELEGRAM_BOT_TOKEN."""
    token = _token(token)
    url = TELEGRAM_API.format(token=token, method=method)
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
                        str(e).replace(token, "<redacted>"))
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


def send_message(text: str, reply_markup: dict = None, token: str = None) -> dict:
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
        message = call("sendMessage", payload, token=token).get("result", {})
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


def print_chat_ids(token: str = None):
    """Print chat IDs of everyone who recently messaged the bot."""
    data = call("getUpdates", {}, token=token)
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
    parser = argparse.ArgumentParser(description="Telegram helper")
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
