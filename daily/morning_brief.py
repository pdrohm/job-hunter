#!/usr/bin/env python3
"""
Morning brief: one Telegram message a day, from its own bot.

    📅 Today's calendar (interviews marked 🎯)
    🌤 Weather
    💵 Dollar rate
    📧 Unread important emails
    💼 Job hunt: applications sent in the last 24 h
    🔀 PRs waiting for your review (asks the Mac through Mike)
    ⏰ Today's reminders (Mike / OpenClaw)

Each part is optional: a part with no config (or that fails) is left out.

Config (.env):
    MORNING_BOT_TOKEN                 a second bot from @BotFather (required)
    TELEGRAM_CHAT_ID                  same chat ID as the job bot
    CALENDAR_ICS_URL                  see daily/calendar_feed.py
    MORNING_LAT, MORNING_LON          weather location (Open-Meteo, no key)
    MORNING_CITY                      label for the weather line
    MORNING_CURRENCIES=USD-BRL        AwesomeAPI pairs, comma-separated
    GMAIL_ADDRESS, GMAIL_APP_PASSWORD Gmail over IMAP (read-only, app password)
    GMAIL_ADDRESS_2, GMAIL_APP_PASSWORD_2 ... _5   more Gmail accounts, same way
    MORNING_GMAIL_QUERY               Gmail search, default below
    MORNING_GMAIL_MAX=8
    MORNING_PRS_CMD                   command that prints the PRs, e.g. "ssh mac-mike prs"
    MORNING_REMINDERS_CMD             e.g. "openclaw automations list --json"
    MORNING_TODOS_CMD                 today's to-dos, e.g. "/home/ia/mike/bin/tarefa listar hoje"
    MORNING_CARD                      also write the brief as JSON cards for the Mike app (path)

Run:
    python -m daily.morning_brief --dry-run     print it, send nothing
    python -m daily.morning_brief --part email  print one part (Mike: "tenho email importante?")
    python -m daily.morning_brief --dry-run --card brief.json   also write it as cards for the app
    python -m daily.morning_brief               send it (launchd runs this at 08:00)
    python -m daily.morning_brief --get-chat-id
"""

import argparse
import re
import email
import html
import imaplib
import json
import logging
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr
from pathlib import Path

import requests
from dotenv import load_dotenv

from daily import calendar_feed
from daily.interview_prep import is_interview
from shared import mike, telegram

log = logging.getLogger("morning_brief")

WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MAX_GMAIL_ACCOUNTS = 5
EXTERNAL_TIMEOUT = 100  # the Mac answers `prs` in up to 90 s
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


def gmail_accounts() -> list[tuple[str, str]]:
    """GMAIL_ADDRESS/GMAIL_APP_PASSWORD, then GMAIL_ADDRESS_2 ... _5."""
    out = []
    for i in range(1, MAX_GMAIL_ACCOUNTS + 1):
        suffix = "" if i == 1 else f"_{i}"
        user, password = _env(f"GMAIL_ADDRESS{suffix}"), _env(f"GMAIL_APP_PASSWORD{suffix}")
        if user and password:
            out.append((user, password))
    return out


def email_part() -> list[str]:
    accounts = gmail_accounts()
    if not accounts:
        return []
    if len(accounts) == 1:
        return _email_lines(*accounts[0])
    lines = []
    for user, password in accounts:
        try:
            part = _email_lines(user, password)
        except Exception as e:  # one account down must not hide the others
            log.warning("Email %s failed: %s", user, e)
            part = ["📧 <b>Emails</b>", f"⚠️ falhou ({html.escape(type(e).__name__)})"]
        part[0] += f" · {html.escape(user)}"
        lines += part
    return lines


def _email_lines(user: str, password: str) -> list[str]:
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
            subject = " ".join(_header(msg.get("Subject", "")).split()) or "(sem assunto)"  # folded headers: one line
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


def _run(cmd_env: str) -> str:
    """Runs the command in env var cmd_env (no shell). Empty = this part is off."""
    cmd = _env(cmd_env)
    if not cmd:
        return ""
    r = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=EXTERNAL_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError((r.stdout + r.stderr).strip()[-200:] or f"exit {r.returncode}")
    return r.stdout.strip()


def prs_part() -> list[str]:
    try:
        out = _run("MORNING_PRS_CMD")
    except (RuntimeError, subprocess.TimeoutExpired):
        return ["🔀 <b>PRs</b>", "Mac fora do ar; não deu para ver."]
    if not out:
        return []
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    if lines and lines[0].startswith("Nenhum"):
        return []  # nothing waiting: keep the brief short
    return ["🔀 <b>PRs para revisar</b>"] + [html.escape(l) for l in lines[1:9]]


def todos_part() -> list[str]:
    """Today's open to-dos from Mike's list ("tarefa listar hoje": "  <id> | <texto> | [atrasada ]<dia>[ HH:MM]")."""
    out = _run("MORNING_TODOS_CMD")
    rows = [l.strip().split(" | ") for l in out.splitlines() if l.startswith("  ") and l.count(" | ") >= 2]
    if not rows:
        return []
    lines = [f"✅ <b>Para fazer hoje</b> ({len(rows)})"]
    for _, text, when, *_ in rows[:8]:
        hour = when.split(" ")[-1] if ":" in when else ""
        late = "  (atrasada)" if when.startswith("atrasada") else ""
        lines.append(f"• {hour + '  ' if hour else ''}{html.escape(text)}{late}")
    return lines


def reminders_part(now: datetime) -> list[str]:
    """One-shot reminders (schedule "at") due before the end of today."""
    out = _run("MORNING_REMINDERS_CMD")
    if not out:
        return []
    end = now.replace(hour=23, minute=59, second=59)
    due = []
    for job in json.loads(out).get("jobs", []):
        if not job.get("enabled", True) or (job.get("schedule") or {}).get("kind") != "at":
            continue
        ms = (job.get("state") or {}).get("nextRunAtMs")
        if not ms:
            continue
        at = datetime.fromtimestamp(ms / 1000, tz=now.tzinfo)
        if now - timedelta(hours=1) <= at <= end:
            due.append((at, job.get("displayName") or job.get("name") or "lembrete"))
    if not due:
        return []
    return ["⏰ <b>Lembretes de hoje</b>"] + [f"• {at:%H:%M} {html.escape(label)}" for at, label in sorted(due)]


# ─────────────────────────────────────────────

def brief_blocks(now: datetime = None) -> tuple[str, list[tuple[str, list[str]]]]:
    """(header, [(part, lines)]). The parts run at the same time: the slow ones (Mac, IMAP) do not add up."""
    now = now or datetime.now().astimezone()
    today = now.date()
    header = f"☀️ <b>Bom dia!</b> {WEEKDAYS[today.weekday()]}, {today.day} {MONTHS[today.month - 1]}"

    parts = []
    if calendar_feed.ics_urls():
        parts.append(("agenda", lambda: agenda_part(calendar_feed.fetch_events(*calendar_feed.day_bounds(today)))))
    parts += [("weather", weather_part), ("todos", todos_part), ("reminders", lambda: reminders_part(now)),
              ("currency", currency_part), ("email", email_part), ("prs", prs_part),
              ("jobs", lambda: jobs_part(now))]

    def run(name, build):
        try:
            return build()
        except Exception as e:  # one broken part must not stop the brief
            log.warning("Part %s failed: %s", name, e)
            return [f"⚠️ {name}: falhou ({html.escape(type(e).__name__)})"]

    with ThreadPoolExecutor(max_workers=len(parts)) as pool:
        results = list(pool.map(lambda p: run(*p), parts))
    return header, [(name, lines) for (name, _), lines in zip(parts, results) if lines]


def build_brief(now: datetime = None) -> str:
    header, blocks = brief_blocks(now)
    return "\n\n".join([header] + ["\n".join(lines) for _, lines in blocks])


_TITLE = re.compile(r"^(\S+)\s+<b>(.*?)</b>\s*(?:\((\d+)\))?\s*(.*)$")
_LINK = re.compile(r'<a href="([^"]+)">')


def _plain(line: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", line)).strip()


def brief_card(header: str, blocks: list[tuple[str, list[str]]], now: datetime = None) -> dict:
    """The brief as data for the app: one section per title line, one item per line under it."""
    sections = []
    for name, lines in blocks:
        for line in lines:
            m = _TITLE.match(line) if not line.startswith("•") else None
            if m or not sections or sections[-1]["parte"] != name:
                if m:
                    sections.append({"parte": name, "emoji": m.group(1), "titulo": _plain(m.group(2)),
                                     "total": int(m.group(3)) if m.group(3) else None,
                                     "detalhe": _plain(m.group(4)).lstrip("· ").strip(), "itens": []})
                    continue
                sections.append({"parte": name, "emoji": "⚠️" if line.startswith("⚠️") else "•",
                                 "titulo": name, "total": None, "detalhe": "", "itens": []})
            link = _LINK.search(line)
            sections[-1]["itens"].append({"texto": _plain(line).lstrip("• ").strip(),
                                          "link": html.unescape(link.group(1)) if link else None,
                                          "falhou": "falhou" in line and line.startswith("⚠️")})
    return {"titulo": _plain(header), "hora": (now or datetime.now().astimezone()).isoformat(timespec="seconds"),
            "secoes": sections}


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Daily morning brief on Telegram")
    parser.add_argument("--dry-run", action="store_true", help="Print the brief, send nothing")
    parser.add_argument("--get-chat-id", action="store_true", help="Print your chat ID for this bot")
    parser.add_argument("--card", metavar="PATH", help="Also write the brief as JSON cards here (or MORNING_CARD)")
    parser.add_argument("--part", choices=["agenda", "email", "weather", "reminders", "prs", "jobs", "todos"],
                        help="Print only this part (plain text), send nothing")
    args = parser.parse_args()

    if args.part:
        now = datetime.now().astimezone()
        build = {"agenda": lambda: agenda_part(calendar_feed.fetch_events(*calendar_feed.day_bounds(now.date()))),
                 "email": email_part, "weather": weather_part, "prs": prs_part,
                 "reminders": lambda: reminders_part(now), "jobs": lambda: jobs_part(now), "todos": todos_part}[args.part]
        lines = build()
        print(mike.plain("\n".join(lines))[0] if lines else "Nada.")
        return

    token = _env("MORNING_BOT_TOKEN")
    if args.get_chat_id:
        telegram.print_chat_ids(token=token)
        return
    now = datetime.now().astimezone()
    header, blocks = brief_blocks(now)
    text = "\n\n".join([header] + ["\n".join(lines) for _, lines in blocks])
    card = args.card or _env("MORNING_CARD")
    if card:
        tmp = Path(card).with_suffix(".tmp")
        tmp.write_text(json.dumps(brief_card(header, blocks, now), ensure_ascii=False), encoding="utf-8")
        tmp.replace(card)
    if args.dry_run:
        print(text)
        return
    if not token and not mike.telegram_off():
        sys.exit("Set MORNING_BOT_TOKEN in .env (a new bot from @BotFather).")
    telegram.send_message(text, token=token)
    log.info("Morning brief sent.")


if __name__ == "__main__":
    main()
