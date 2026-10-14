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
from typing import Optional

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


# ─────────────────────────────────────────────
# Region: keep only remote jobs open worldwide or to LATAM
# ─────────────────────────────────────────────

LATAM_PLACES = [
    "argentina", "bolivia", "brazil", "brasil", "chile", "colombia", "costa rica", "cuba",
    "dominican republic", "república dominicana", "ecuador", "el salvador", "guatemala",
    "honduras", "mexico", "méxico", "nicaragua", "panama", "panamá", "paraguay", "peru",
    "perú", "puerto rico", "uruguay", "venezuela",
    # Metro areas LinkedIn shows without the country
    "buenos aires", "bogotá", "bogota", "medellín", "medellin", "santiago metropolitan",
    "lima", "montevideo", "guadalajara", "monterrey", "quito", "asunción", "asuncion",
    "belize", "guyana", "suriname", "jamaica", "caribbean",
]
# "New Mexico" is a US state, not Mexico
_LATAM_PLACE_RE = re.compile(
    r"(?<!\w)(?<!new\s)(?:" + "|".join(re.escape(p) for p in LATAM_PLACES) + r")(?!\w)",
    re.IGNORECASE,
)

# LinkedIn locations that are a region, not one country
_OPEN_LOCATION_RE = re.compile(
    r"^(?:worldwide|remote|anywhere|global|earth|emea\s*&?\s*latam|"
    r"latin\s+america|latam|south\s+america|central\s+america|the\s+americas|americas)$",
    re.IGNORECASE,
)

# Text that says people outside the hiring country can apply. Stricter than
# _OPEN_ABROAD_RE: words like "global" or "international" alone are company
# boilerplate ("a global leader"), not a hiring rule.
_OPEN_TO_REGION_RE = re.compile(
    r"\b(?:worldwide|(?:work|remote|hire|hiring|apply|candidates?)\s+from\s+anywhere|"
    r"anywhere\s+in\s+the\s+world|latam|latin\s+america|south\s+america|central\s+america|"
    r"(?:any|all)\s+time\s*zones?|international\s+(?:candidates|applicants|contractors|talent)|"
    r"outside\s+(?:of\s+)?(?:the\s+)?u\.?s\.?a?\b|nearshore|globally\s+remote|remote[\s-]+global|"
    r"fully\s+distributed|the\s+americas)\b",
    re.IGNORECASE,
)


def is_latam_location(location: str) -> bool:
    return bool(_LATAM_PLACE_RE.search(location or ""))


def mentions_open_region(text: str) -> bool:
    """Text says the job hires worldwide or in LATAM."""
    text = text or ""
    return bool(_OPEN_TO_REGION_RE.search(text) or _LATAM_PLACE_RE.search(text))


def region_ok(location: str, text: str) -> bool:
    """Job is in LATAM, listed as worldwide/regional, or its text says
    people abroad (worldwide or LATAM) can apply."""
    loc = (location or "").strip()
    if not loc or loc.lower() == "not specified" or _OPEN_LOCATION_RE.match(loc):
        return True
    if is_latam_location(loc):
        return True
    return mentions_open_region(text)


# ─────────────────────────────────────────────
# Tech: React Native / Expo mobile only
# ─────────────────────────────────────────────

_RN_CORE_RE = re.compile(r"react[\s-]?native|(?<!\w)reactnative(?!\w)|(?<![\w.])expo(?!\w)", re.IGNORECASE)
_MOBILE_TITLE_RE = re.compile(
    r"\b(?:mobile|app)\s+(?:developer|engineer|dev|lead|architect)\b|\bmobile\b", re.IGNORECASE
)
_JS_STACK_RE = re.compile(r"\b(?:react|javascript|typescript)\b", re.IGNORECASE)


def is_rn_match(title: str, text: str, strict: bool = False) -> bool:
    """React Native / Expo role. Also a mobile role on a JS/TS stack
    ("or something similar"); native-only Swift/Kotlin roles don't count.

    strict: React Native / Expo must be the job, not a side note. It is in
    the title, or the title is a mobile role and the text names it, or the
    text names it at least twice ("React Native is a plus" on a web job fails)."""
    if not strict:
        if _RN_CORE_RE.search(f"{title or ''} {text or ''}"):
            return True
        return bool(_MOBILE_TITLE_RE.search(title or "") and _JS_STACK_RE.search(text or ""))
    if _RN_CORE_RE.search(title or ""):
        return True
    hits = len(_RN_CORE_RE.findall(text or ""))
    return hits >= 2 or (hits == 1 and bool(_MOBILE_TITLE_RE.search(title or "")))


# ─────────────────────────────────────────────
# Top markets: a US / Canada / Europe company that hires in LATAM
# ─────────────────────────────────────────────

TOP_MARKET_PLACES = [
    "united states", "usa", "canada", "united kingdom", "england", "scotland", "ireland",
    "germany", "netherlands", "france", "spain", "portugal", "italy", "belgium", "luxembourg",
    "switzerland", "austria", "sweden", "norway", "denmark", "finland", "iceland", "poland",
    "czechia", "czech republic", "estonia", "lithuania", "latvia", "european union", "europe",
    "emea", "north america",
    # Metro areas LinkedIn shows without the country
    "san francisco", "bay area", "new york", "los angeles", "seattle", "boston", "austin",
    "chicago", "miami", "toronto", "vancouver", "montreal", "london", "berlin", "amsterdam",
    "paris", "dublin", "lisbon", "barcelona", "madrid", "stockholm", "zurich", "munich",
]
_TOP_MARKET_PLACE_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(p) for p in TOP_MARKET_PLACES) + r")(?!\w)"
    r"|,\s*(?-i:[A-Z]{2})$",  # "Austin, TX": US state code
    re.IGNORECASE,
)

# Text that shows the company or its clients are in a top market:
# where it is based, its time zones, or the currency it pays in.
_TOP_MARKET_SIGNAL_RE = re.compile(
    r"\b(?:u\.?s\.?|us|american|canadian|european|uk|british|german|dutch|swiss|nordic)[\s-]+"
    r"(?:based|headquartered|company|companies|clients?|customers?|startups?|teams?|hours|time\s*zones?)\b|"
    r"\b(?:based|headquartered|hq|offices?)\s+in\s+(?:the\s+)?(?:u\.?s\.?a?|united\s+states|"
    r"canada|europe|uk|united\s+kingdom|" + "|".join(re.escape(p) for p in TOP_MARKET_PLACES) + r")\b|"
    r"\b(?:north\s+america|silicon\s+valley|y\s?combinator|yc\s?[swfx]\d{2})\b|"
    # Not GMT/UTC: "UTC-3" is Brazil time. Bare ET/PT/CT are too common as words.
    r"\b(?:est|edt|pst|pdt|cst|cdt|mst|cet|cest|bst)\b|\b(?:et|pt|ct)\s+(?:time|hours|overlap)\b|"
    r"\b(?:eastern|pacific|central|mountain)\s+(?:standard\s+)?time\b|"
    r"\b(?:usd|eur|gbp|cad|us\s+dollars?|euros?)\b|[$€£]\s?\d",
    re.IGNORECASE,
)

# Words that only show up in Spanish job posts (a local LATAM company)
_SPANISH_HINTS = re.compile(
    r"\b(?:buscamos|estamos\s+buscando|empresa|experiencia|requisitos|beneficios|"
    r"ofrecemos|desarrollador(?:a)?|conocimientos|trabajo|sueldo|postúlate|postulate|vacante)\b",
    re.IGNORECASE,
)


def is_top_market_location(location: str) -> bool:
    return bool(_TOP_MARKET_PLACE_RE.search((location or "").strip()))


def looks_spanish(text: str, min_hits: int = 3) -> bool:
    return len(_SPANISH_HINTS.findall(text or "")) >= min_hits


def top_market_signal(text: str) -> str:
    """The first words that tie the job to a US / Canada / Europe company, or ''."""
    m = _TOP_MARKET_SIGNAL_RE.search(text or "")
    return m.group(0) if m else ""


def is_top_market_job(location: str, text: str) -> bool:
    """Job from a US / Canada / Europe company (or for its clients).

    A job listed in a top-market country passes (the region filter checks
    that LATAM can apply). A job listed in LATAM or worldwide needs a sign in
    the text: where the company is based, its time zone, or its currency.
    Spanish or Portuguese text means a local company: it fails."""
    if is_top_market_location(location):
        return True
    if looks_spanish(text) or looks_portuguese(text):
        return False
    return bool(top_market_signal(text))


# ─────────────────────────────────────────────
# Posts: a company hiring, not a person looking for work
# ─────────────────────────────────────────────

_JOB_SEEKER_RE = re.compile(
    r"#?open\s?to\s?work\b|#lookingforwork|#jobseeker|#lookingforjob|"
    r"\bi['’]?\s?a?m\s+(?:currently\s+|actively\s+)?(?:exploring|looking\s+for|seeking|open\s+to)\s+"
    r"(?:new\s+)?(?:\w+\s+){0,4}(?:opportunit|roles?\b|jobs?\b|positions?\b|challenge)|"
    r"\b(?:open\s+to\s+new|seeking\s+new|exploring\s+new)\s+(?:opportunities|roles)\b|"
    r"\bavailable\s+for\s+(?:new\s+)?(?:opportunities|hire|work|freelance)",
    re.IGNORECASE,
)

_HIRING_INTENT_RE = re.compile(
    r"\bhiring\b|\bwe['’]?re\s+looking\b|\bwe\s+are\s+(?:looking|searching|seeking|growing)\b|"
    r"\blooking\s+for\s+(?:a|an|two|three|\d+|experienced|senior|talented)\b|\bjoin\s+(?:our|the|us)\b|"
    r"\bopen\s+(?:role|position|vacanc)|\bjob\s+opening|\bposition\s+available|\bapply\b|"
    r"\bsend\s+(?:me\s+)?(?:your\s+)?(?:cv|resume)|\bvagas?\b|\bcontratando\b|\bbuscamos\b|"
    r"\bestamos\s+(?:buscando|procurando|contratando)\b|\bvacantes?\b|\bstiamo\s+cercando\b|"
    r"\brecrutando\b|\bseeking\s+(?:a|an)\b|\bopportunity\b",
    re.IGNORECASE,
)


def is_job_seeker_post(text: str) -> bool:
    """Post by a person looking for work (#opentowork), not a job."""
    return bool(_JOB_SEEKER_RE.search(text or ""))


def has_hiring_intent(text: str) -> bool:
    return bool(_HIRING_INTENT_RE.search(text or ""))


# ─────────────────────────────────────────────
# Excluded countries (e.g. skip local Brazilian jobs for now)
# ─────────────────────────────────────────────

# LinkedIn locations usually end in ", Brazil", but metro areas don't
# ("Greater Porto Alegre", "São Paulo Metropolitan Area"), so list big cities too.
COUNTRY_LOCATION_ALIASES = {
    "brazil": [
        "brazil", "brasil", "são paulo", "sao paulo", "rio de janeiro", "belo horizonte",
        "porto alegre", "curitiba", "florianópolis", "florianopolis", "recife", "campinas",
        "brasília", "brasilia", "salvador", "fortaleza", "goiânia", "goiania", "manaus",
        "joinville", "blumenau", "guarulhos", "santa catarina", "minas gerais",
        "rio grande do sul", "paraná", "pernambuco",
    ],
}

# Words that only show up in Portuguese job posts
_PORTUGUESE_HINTS = re.compile(
    r"\b(?:vaga|vagas|contratação|contratando|estamos|oportunidade|remoto|remota|"
    r"desenvolvedor(?:a)?|você|benefícios|requisitos|salário|clt)\b",
    re.IGNORECASE,
)


def _country_patterns(country: str) -> list[re.Pattern]:
    aliases = COUNTRY_LOCATION_ALIASES.get(country.strip().lower(), [country.strip().lower()])
    return [re.compile(r"(?<!\w)" + re.escape(a) + r"(?!\w)", re.IGNORECASE) for a in aliases]


def located_in(location: str, countries: list[str]) -> str:
    """Return the excluded country the location is in, or ''."""
    if not location or not countries:
        return ""
    for country in countries:
        if any(p.search(location) for p in _country_patterns(country)):
            return country
    return ""


def looks_portuguese(text: str, min_hits: int = 2) -> bool:
    """Posts have no location; a Portuguese post is almost always a Brazil job."""
    return len(_PORTUGUESE_HINTS.findall(text or "")) >= min_hits


# ─────────────────────────────────────────────
# Job summary helpers (for alerts)
# ─────────────────────────────────────────────

_MONEY = r"(?:USD|US\$|\$)\s?\d[\d,]*(?:\.\d+)?\s?[kK]?"
_PERIOD = r"(?:\s?(?:/|per|a)\s?(?:year|yr|annum|month|mo|hour|hr|h)\b)?"
# "$110,400.00/yr - $220,800.00/yr" (LinkedIn) and "$120k - $150k per year" both match
_SALARY_RE = re.compile(
    _MONEY + _PERIOD
    + r"(?:\s?(?:-|–|—|to)\s?(?:" + _MONEY + r"|\d[\d,]*(?:\.\d+)?\s?[kK]?)" + _PERIOD + r")?",
    re.IGNORECASE,
)


def extract_salary(text: str) -> str:
    """First salary-looking amount in a job text, e.g. '$120k - $150k/yr'.
    Ignores tiny amounts (e.g. '$5 coffee') that aren't pay."""
    for m in _SALARY_RE.finditer(text or ""):
        values = _amounts(m.group(0))
        if values and max(values) >= 15:  # $15/hr is the smallest plausible pay
            return " ".join(m.group(0).split())
    return ""


def _amounts(text: str) -> list[float]:
    out = []
    for num, k in re.findall(r"(\d[\d,]*(?:\.\d+)?)\s?([kK]?)", text):
        try:
            value = float(num.replace(",", ""))
        except ValueError:
            continue
        out.append(value * 1000 if k else value)
    return out


def monthly_usd_range(salary: str) -> Optional[tuple[float, float]]:
    """Convert a salary string to a USD/month (low, high) range.
    Hourly → ×160 h, yearly → ÷12. Unknown period: guess by size."""
    values = _amounts(salary)
    if not values:
        return None
    low, high = min(values), max(values)
    s = salary.lower()
    if re.search(r"/\s?h(?:ou)?r\b|per\s+hour|\bhourly\b|/\s?h\b", s):
        factor = 160
    elif re.search(r"year|yr|annum|annual", s):
        factor = 1 / 12
    elif re.search(r"month|/\s?mo\b", s):
        factor = 1
    else:
        factor = 1 / 12 if high >= 20000 else (160 if high < 300 else 1)
    return (low * factor, high * factor)


TECH_TAGS = [
    "React Native", "Expo", "TypeScript", "JavaScript", "React", "Swift", "Kotlin",
    "Objective-C", "Node.js", "NestJS", "GraphQL", "Redux", "Zustand", "Firebase",
    "iOS", "Android", "Flutter", "AWS", "Next.js",
]
_TECH_PATTERNS = [(t, re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.IGNORECASE)) for t in TECH_TAGS]


def tech_tags(text: str, limit: int = 6) -> list[str]:
    found = [t for t, p in _TECH_PATTERNS if p.search(text or "")]
    if "React Native" in found and "React" in found:
        found.remove("React")  # "React Native" already says it
    return found[:limit]


def is_open_abroad(text: str) -> bool:
    return bool(_OPEN_ABROAD_RE.search(text or ""))
