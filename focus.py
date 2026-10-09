"""
Focus rules for a candidate outside the hiring company's country.

The candidate is remote, abroad (e.g. Brazil), and has no work visa, so:
  - Jobs that need local work authorization, citizenship, a clearance or
    visa sponsorship are useless  →  excluded.
  - Jobs open to anyone (worldwide, LATAM, contractor, B2B, paid via Deel...)
    are the best fit  →  boosted.
  - Remote jobs listed in the US/UK/etc. with no "anywhere" signal are
    usually country-only  →  down-ranked, not excluded (some still hire abroad).

All functions take plain text so they are easy to test.
"""

import re

# ─────────────────────────────────────────────
# Work authorization / sponsorship blockers
# ─────────────────────────────────────────────

_COUNTRIES = (
    r"(?:the\s+)?(?:u\.?s\.?a?|united\s+states|america|uk|u\.k\.|united\s+kingdom|"
    r"canada|eu|e\.u\.|european\s+union|europe|germany|australia|ireland|netherlands|"
    r"country|state|province)"
)

SPONSORSHIP_BLOCKER_PATTERNS = [
    # "We do not / cannot / will not sponsor (visas)"
    r"\b(?:no|not|unable\s+to|cannot|can'?t|will\s+not|won'?t|do\s+not|don'?t|does\s+not|doesn'?t|are\s+not\s+able\s+to)\s+"
    r"(?:currently\s+)?(?:provide\s+|offer\s+|support\s+)?(?:any\s+)?(?:visa\s+|h-?1b\s+|employment\s+)?sponsor",
    r"\bsponsorship\s+(?:is\s+)?(?:not\s+(?:available|offered|provided|possible)|unavailable)",
    r"\bwithout\s+(?:the\s+need\s+for\s+|requiring\s+)?(?:current\s+or\s+future\s+)?(?:visa\s+|employer\s+)?sponsorship",
    r"\bnot\s+eligible\s+for\s+(?:visa\s+)?sponsorship",
    r"\bnow\s+or\s+in\s+the\s+future\b.{0,40}sponsor",
    # "Must be authorized / eligible to work in the US"
    r"\b(?:authori[sz]ed|eligible|legally\s+able|right|permitted)\s+to\s+work\s+(?:in|for|within)\s+" + _COUNTRIES,
    r"\b(?:authori[sz]ed|eligible)\s+to\s+work\s+for\s+any\s+employer\b",
    r"\btake\s+over\s+(?:visa\s+)?sponsorship\b",
    r"\b(?:valid|existing|current)\s+(?:us\s+|uk\s+|eu\s+)?work\s+(?:permit|authori[sz]ation|visa)\b",
    # "open to applicants from anywhere in the U.S." = US only
    r"\banywhere\s+(?:in|within|across)\s+(?:the\s+)?(?:u\.?s\.?a?\b|united\s+states|uk\b|united\s+kingdom|canada)",
    r"\bright\s+to\s+work\b",
    # Citizenship / clearance / residency
    r"\b(?:u\.?s\.?|us|american|canadian|uk|british|eu)\s+citizen(?:ship)?\b",
    r"\bcitizens?\s+(?:only|required)\b",
    r"\bcitizenship\s+(?:is\s+)?required\b",
    r"\bgreen\s+card\b",
    r"\b(?:security|secret|ts/sci|top\s+secret|active|public\s+trust)\s+clearance\b",
    r"\bclearance\s+(?:is\s+)?required\b",
    r"\bmust\s+(?:reside|live|be\s+(?:located|based|living))\s+(?:in|within)\s+" + _COUNTRIES,
    r"\b(?:us|u\.s\.|uk|canada|eu)[\s-]?(?:based|residents?)\s+only\b",
    r"\bonly\s+(?:open\s+to\s+)?(?:candidates|applicants|residents)\s+(?:based\s+|located\s+|residing\s+)?(?:in|within)\s+" + _COUNTRIES,
    # US payroll-only contract types
    r"\bw-?2\s+only\b",
    r"\bno\s+(?:c2c|corp[\s-]+to[\s-]+corp|1099)\b",
]

_sponsorship_blockers = [re.compile(p, re.IGNORECASE) for p in SPONSORSHIP_BLOCKER_PATTERNS]


def sponsorship_blocker(text: str) -> str:
    """Return the matched phrase if the text requires local work authorization,
    citizenship, clearance or visa sponsorship. Empty string if none."""
    if not text:
        return ""
    for pat in _sponsorship_blockers:
        m = pat.search(text)
        if m:
            return m.group(0)
    return ""


# ─────────────────────────────────────────────
# Contractor detection
# ─────────────────────────────────────────────

CONTRACT_EMPLOYMENT_TYPES = {"contract", "temporary", "freelance", "part-time", "other"}

CONTRACTOR_PATTERNS = [
    r"\b(?:independent\s+)?contractors?\b",
    r"\bcontract(?:\s+role|\s+position|\s+basis|[\s-]+to[\s-]+hire)?\b",
    r"\bfreelanc(?:e|er|ing)\b",
    r"\bb2b\b",
    r"\bpj\b",  # Brazilian contractor regime
    r"\bc2c\b",
    r"\bcorp[\s-]+to[\s-]+corp\b",
    r"\bconsultant\b",
    r"\bhourly\s+rate\b",
    r"\bper\s+hour\b",
    r"\b(?:usd|us\$|\$)\s?\d+\s?(?:/|per)\s?h(?:ou)?r\b",
]

_contractor_patterns = [re.compile(p, re.IGNORECASE) for p in CONTRACTOR_PATTERNS]


def is_contractor(text: str, employment_type: str = "") -> bool:
    if employment_type and employment_type.strip().lower() in CONTRACT_EMPLOYMENT_TYPES:
        return True
    if employment_type and employment_type.strip().lower() == "full-time":
        # LinkedIn says full-time employee; only trust an explicit contractor mention
        return bool(re.search(r"\b(?:independent\s+)?contractors?\b|\bb2b\b|\bpj\b", text or "", re.IGNORECASE))
    return any(p.search(text or "") for p in _contractor_patterns)


# ─────────────────────────────────────────────
# "Open to people abroad" signals → score boost
# ─────────────────────────────────────────────

OPEN_TO_ABROAD_SIGNALS = {
    "work from anywhere": 10,
    "remote from anywhere": 10,
    "anywhere in the world": 12,
    "worldwide": 8,
    "globally": 5,
    "global team": 4,
    "any timezone": 6,
    "any time zone": 6,
    "latam": 12,
    "latin america": 12,
    "south america": 10,
    "brazil": 12,
    "brasil": 12,
    "americas": 6,
    "nearshore": 8,
    "international candidates": 10,
    "outside the us": 10,
    "outside the u.s.": 10,
    "deel": 8,
    "remote.com": 6,
    "oyster": 4,
    "paid in usd": 10,
    "usd": 3,
    "contractor": 8,
    "independent contractor": 10,
    "b2b": 8,
    "pj": 8,
    "freelance": 5,
    "contract": 4,
    "vaga": 6,
    "remoto": 6,
}

# Location strings LinkedIn uses for country-restricted remote jobs
_COUNTRY_ONLY_LOCATION = re.compile(
    r"^(?:united states|usa|us|united kingdom|uk|canada|germany|france|australia|ireland|"
    r"netherlands|spain|poland|sweden|switzerland|india)$"
    r"|,\s*(?:[A-Z]{2}|united states|united kingdom|england|canada|germany|australia)$",
    re.IGNORECASE,
)

_OPEN_ABROAD_RE = re.compile(
    r"\b(?:worldwide|anywhere(?!\s+(?:in|within|across)\s+(?:the\s+)?(?:u\.?s|united|uk\b|canada))|latam|latin america|south america|brazil|brasil|global(?:ly)?|"
    r"international|any\s+time\s*zone|outside\s+(?:the\s+)?u\.?s\.?|nearshore|americas)\b",
    re.IGNORECASE,
)

COUNTRY_ONLY_PENALTY = 15


def looks_country_only(location: str, text: str) -> bool:
    """Remote job pinned to a single foreign country, with nothing in the
    text saying people abroad can apply."""
    loc = (location or "").strip()
    if not loc or not _COUNTRY_ONLY_LOCATION.search(loc):
        return False
    return not _OPEN_ABROAD_RE.search(f"{loc} {text or ''}")
