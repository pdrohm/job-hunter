#!/usr/bin/env python3
"""
Read your calendar from its private iCal link (no OAuth, works headless).

Google Calendar: Settings → your calendar → "Secret address in iCal format".
Put it in .env as CALENDAR_ICS_URL. Several calendars: separate with commas.
The link gives read access to the calendar, so keep it only in .env.
"""

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

import icalendar
import recurring_ical_events
import requests

log = logging.getLogger("calendar_feed")


@dataclass
class Event:
    uid: str
    title: str
    start: datetime  # local time, timezone-aware
    end: datetime
    all_day: bool = False
    location: str = ""
    description: str = ""
    url: str = ""  # video call link, if any

    @property
    def key(self) -> str:
        """Unique per occurrence: a recurring event shares one UID."""
        return f"{self.uid}@{self.start.isoformat()}"


def ics_urls() -> list[str]:
    return [u.strip() for u in os.environ.get("CALENDAR_ICS_URL", "").split(",") if u.strip()]


def _local(value) -> tuple[datetime, bool]:
    """iCal DATE or DATE-TIME → (aware local datetime, all_day)."""
    if isinstance(value, datetime):
        # A "floating" time (no tzinfo) is already local; astimezone() keeps it
        return value.astimezone(), False
    return datetime.combine(value, time.min).astimezone(), True


def _video_link(component) -> str:
    """Meet / Zoom / Teams link: Google puts Meet in X-GOOGLE-CONFERENCE."""
    for field in ("X-GOOGLE-CONFERENCE", "URL"):
        value = str(component.get(field, "") or "").strip()
        if value.startswith("http"):
            return value
    text = f"{component.get('LOCATION', '')} {component.get('DESCRIPTION', '')}"
    for word in text.split():
        if word.startswith("https://") and any(h in word for h in ("meet.google", "zoom.us", "teams.microsoft")):
            return word.strip("<>()\"'")
    return ""


def parse_events(ics_text: str, start: datetime, end: datetime) -> list[Event]:
    """Events (recurring ones expanded) that overlap [start, end)."""
    cal = icalendar.Calendar.from_ical(ics_text)
    events = []
    for comp in recurring_ical_events.of(cal).between(start, end):
        if str(comp.get("STATUS", "")).upper() == "CANCELLED":
            continue
        ev_start, all_day = _local(comp.decoded("DTSTART"))
        if comp.get("DTEND") is not None:
            ev_end, _ = _local(comp.decoded("DTEND"))
        else:
            ev_end = ev_start + (timedelta(days=1) if all_day else timedelta(hours=1))
        events.append(Event(
            uid=str(comp.get("UID", "")),
            title=str(comp.get("SUMMARY", "") or "(sem título)").strip(),
            start=ev_start,
            end=ev_end,
            all_day=all_day,
            location=str(comp.get("LOCATION", "") or "").strip(),
            description=str(comp.get("DESCRIPTION", "") or "").strip(),
            url=_video_link(comp),
        ))
    return sorted(events, key=lambda e: (not e.all_day, e.start))


def fetch_events(start: datetime, end: datetime, urls: Optional[list[str]] = None) -> list[Event]:
    """Events from every configured calendar. A calendar that fails is skipped."""
    events = []
    for url in urls if urls is not None else ics_urls():
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            events += parse_events(resp.text, start, end)
        except Exception as e:  # one bad calendar must not stop the others
            # The URL is a secret: never log it
            log.warning("Calendar fetch failed: %s", type(e).__name__)
    return sorted(events, key=lambda e: (not e.all_day, e.start))


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min).astimezone()
    return start, start + timedelta(days=1)
