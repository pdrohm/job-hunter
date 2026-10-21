#!/usr/bin/env python3
"""
Job alerts on Telegram: format a job (salary, age, tags, Candidatar button)
and send new jobs. The Telegram client itself is shared/telegram.py.

    python -m job_hunter.notifier --get-chat-id   print your chat ID
    python -m job_hunter.notifier --test          send a test message
"""

import html
import os
from typing import Optional

from job_hunter import focus
from job_hunter.rn_linkedin_scraper import Opportunity, _age_days_from_iso, extract_linkedin_job_id
from shared import telegram

# Label of a post's apply link in the alert. The apply bot finds the link by
# this label when you tap Candidatar (callback_data is too small for a URL).
APPLY_LINK_LABEL = "Link para candidatar"


MIN_MONTHLY_USD = float(os.environ.get("WATCH_MIN_MONTHLY_USD", "") or 6000)
ABOUT_CHARS = 220


def apply_button(opp: Opportunity) -> Optional[dict]:
    """Candidatar button for one job. callback_data is capped at 64 bytes by
    Telegram, so it carries only the LinkedIn job ID. A post has no ID: its
    button says "applypost" and the bot reads the link from the alert itself
    (the apply link, else the post, where Claude looks for one)."""
    job_id = opp.job_id or extract_linkedin_job_id(opp.apply_url)
    if job_id:
        return telegram.buttons([[("📝 Candidatar", f"apply:{job_id}")]])
    if opp.result_type == "post":
        return telegram.buttons([[("📝 Candidatar", "applypost")]])
    return None


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

    if opp.apply_url:
        lines.append(f'🔗 <a href="{e(opp.apply_url, quote=True)}">{APPLY_LINK_LABEL}</a>')
    if opp.apply_email:
        lines.append(f"📧 {e(opp.apply_email)}")

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
    telegram.send_message(f"<b>{html.escape(header)}</b>")
    for i, opp in enumerate(opportunities, 1):
        telegram.send_message(format_opportunity(opp, i), reply_markup=apply_button(opp))


if __name__ == "__main__":
    telegram.main()
