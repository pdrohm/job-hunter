#!/usr/bin/env python3
"""
Morning brief: one Telegram message a day, from its own bot.

    📅 Today's calendar (interviews marked 🎯)
    🌤 Weather
    💵 Dollar rate
    📧 Unread important emails
    💼 Job hunt: applications sent in the last 24 h

Each part is optional: a part with no config (or that fails) is left out.

Config (.env):
    MORNING_BOT_TOKEN                 a second bot from @BotFather (required)
    TELEGRAM_CHAT_ID                  same chat ID as the job bot
    CALENDAR_ICS_URL                  see calendar_feed.py
    MORNING_LAT, MORNING_LON          weather location (Open-Meteo, no key)
    MORNING_CITY                      label for the weather line
    MORNING_CURRENCIES=USD-BRL        AwesomeAPI pairs, comma-separated
    GMAIL_ADDRESS, GMAIL_APP_PASSWORD Gmail over IMAP (read-only, app password)
    MORNING_GMAIL_QUERY               Gmail search, default below
    MORNING_GMAIL_MAX=8

Run:
    python morning_brief.py --dry-run     print it, send nothing
    python morning_brief.py               send it (launchd runs this at 08:00)
    python morning_brief.py --get-chat-id
"""

import argparse
import email
import html
import imaplib
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr
from pathlib import Path

import requests
from dotenv import load_dotenv

import calendar_feed
import notifier
from interview_prep import is_interview

log = logging.getLogger("morning_brief")

WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
DEFAULT_GMAIL_QUERY = "is:unread is:important newer_than:1d -category:promotions -category:social"

# WMO weather codes (Open-Meteo) → short Portuguese label
WEATHER_CODES = {
    0: "☀️ céu limpo", 1: "🌤 quase limpo", 2: "⛅ parcialmente nublado", 3: "☁️ nublado",
    45: "🌫 neblina", 48: "🌫 neblina",
    51: "🌦 garoa", 53: "🌦 garoa", 55: "🌦 garoa forte",
    61: "🌧 chuva fraca", 63: "🌧 chuva", 65: "🌧 chuva forte",
    80: "🌦 pancadas", 81: "🌧 pancadas", 82: "⛈ pancadas fortes",
    95: "⛈ trovoadas", 96: "⛈ trovoadas com granizo", 99: "⛈ trovoadas com granizo",
}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


# ─────────────────────────────────────────────
# Parts. Each returns HTML lines, or [] to leave the part out.
# ─────────────────────────────────────────────

def agenda_part(events: list[calendar_feed.Event]) -> list[str]:
    if not events:
        return ["📅 <b>Agenda</b>", "Nada na agenda hoje."]
    lines = [f"📅 <b>Agenda</b> ({len(events)})"]
    for ev in events:
        when = "dia todo" if ev.all_day else f"{ev.start:%H:%M}–{ev.end:%H:%M}"
        mark = "🎯 " if is_interview(ev) else ""
        title = html.escape(ev.title)
        if ev.url:
            title = f'<a href="{html.escape(ev.url, quote=True)}">{title}</a>'
        lines.append(f"• {when}  {mark}{title}")
    return lines


def weather_part() -> list[str]:
    lat, lon = _env("MORNING_LAT"), _env("MORNING_LON")
    if not (lat and lon):
        return []
    resp = requests.get("https://api.open-meteo.com/v1/forecast", timeout=15, params={
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 1,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    })
    resp.raise_for_status()
    d = resp.json()["daily"]
    code = d["weather_code"][0]
    label = WEATHER_CODES.get(code, "🌡")
    rain = d["precipitation_probability_max"][0]
    city = html.escape(_env("MORNING_CITY", "Tempo"))
    line = (f"{label}, {round(d['temperature_2m_min'][0])}° a {round(d['temperature_2m_max'][0])}°"
            + (f", chuva {rain}%" if rain else ""))
    tip = "  ☂️ leve guarda-chuva" if (rain or 0) >= 50 else ""
    return [f"🌤 <b>{city}</b>", line + tip]


def currency_part() -> list[str]:
    pairs = [p.strip().upper() for p in _env("MORNING_CURRENCIES", "USD-BRL").split(",") if p.strip()]
    if not pairs:
        return []
    resp = requests.get(f"https://economia.awesomeapi.com.br/json/last/{','.join(pairs)}", timeout=15)
    resp.raise_for_status()
    data = resp.json()
    lines = ["💵 <b>Câmbio</b>"]
    for pair in pairs:
        q = data.get(pair.replace("-", ""))
        if not q:
            continue
        change = float(q.get("pctChange") or 0)
        arrow = "▲" if change > 0 else "▼" if change < 0 else "•"
        lines.append(f"{pair.replace('-', '→')}: {float(q['bid']):.2f}  {arrow} {change:+.2f}%")
    return lines if len(lines) > 1 else []


def _header(raw: str) -> str:
    try:
        return str(make_header(decode_header(raw or ""))).strip()
    except Exception:
        return (raw or "").strip()


def email_part() -> list[str]:
    user, password = _env("GMAIL_ADDRESS"), _env("GMAIL_APP_PASSWORD")
    if not (user and password):
        return []
    query = _env("MORNING_GMAIL_QUERY", DEFAULT_GMAIL_QUERY)
    limit = int(_env("MORNING_GMAIL_MAX", "8"))
    with imaplib.IMAP4_SSL("imap.gmail.com", timeout=30) as imap:
        imap.login(user, password)
        imap.select("INBOX", readonly=True)  # read-only: nothing gets marked as read
        _, data = imap.search(None, "X-GM-RAW", f'"{query}"')
        ids = data[0].split()
        if not ids:
            return ["📧 <b>Emails</b>", "Nenhum email importante novo."]
        lines = [f"📧 <b>Emails</b> ({len(ids)})"]
        for msg_id in reversed(ids[-limit:]):  # newest first
            _, parts = imap.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
            msg = email.message_from_bytes(parts[0][1])
            name, addr = parseaddr(_header(msg.get("From", "")))
            subject = _header(msg.get("Subject", "")) or "(sem assunto)"
            lines.append(f"• <b>{html.escape(name or addr)}</b>: {html.escape(subject[:90])}")
        if len(ids) > limit:
            lines.append(f"… e mais {len(ids) - limit}")
    return lines


def jobs_part(now: datetime) -> list[str]:
    """Applications from the apply bot's log in the last 24 h."""
    path = Path(_env("APPLY_HOME", "~/.job-hunter")).expanduser() / "applications.jsonl"
    if not path.exists():
        return []
    since = now - timedelta(days=1)
    sent = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            at = datetime.fromisoformat(row["at"])
        except (ValueError, KeyError):
            continue
        if at >= since and row.get("status") == "submitted":
            sent.append(row)
    if not sent:
        return []
    lines = [f"💼 <b>Candidaturas (24 h)</b> ({len(sent)})"]
    for row in sent[-5:]:
        lines.append(f"• {html.escape(row.get('company', '?'))} – {html.escape(row.get('role', '?'))}")
    return lines


# ─────────────────────────────────────────────

def build_brief(now: datetime = None) -> str:
    now = now or datetime.now().astimezone()
    today = now.date()
    header = f"☀️ <b>Bom dia!</b> {WEEKDAYS[today.weekday()]}, {today.day} {MONTHS[today.month - 1]}"
    blocks = [header]

    parts = []
    if calendar_feed.ics_urls():
        parts.append(("agenda", lambda: agenda_part(calendar_feed.fetch_events(*calendar_feed.day_bounds(today)))))
    parts += [("weather", weather_part), ("currency", currency_part),
              ("email", email_part), ("jobs", lambda: jobs_part(now))]

    for name, build in parts:
        try:
            lines = build()
        except Exception as e:  # one broken part must not stop the brief
            log.warning("Part %s failed: %s", name, e)
            lines = [f"⚠️ {name}: falhou ({html.escape(type(e).__name__)})"]
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Daily morning brief on Telegram")
    parser.add_argument("--dry-run", action="store_true", help="Print the brief, send nothing")
    parser.add_argument("--get-chat-id", action="store_true", help="Print your chat ID for this bot")
    args = parser.parse_args()

    token = _env("MORNING_BOT_TOKEN")
    if args.get_chat_id:
        notifier.print_chat_ids(token=token)
        return
    text = build_brief()
    if args.dry_run:
        print(text)
        return
    if not token:
        sys.exit("Set MORNING_BOT_TOKEN in .env (a new bot from @BotFather).")
    notifier.send_message(text, token=token)
    log.info("Morning brief sent.")


if __name__ == "__main__":
    main()
