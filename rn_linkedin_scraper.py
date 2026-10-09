#!/usr/bin/env python3
"""
React Native LinkedIn Opportunity Scraper
==========================================
Discovers React Native jobs and hiring posts from LinkedIn's public pages.
Applies strict geographic filtering to exclude India-related results.
Returns a curated, ranked feed of opportunities.

Usage:
    python rn_linkedin_scraper.py                    # Run with defaults
    python rn_linkedin_scraper.py --output results.json  # Save to file
    python rn_linkedin_scraper.py --format html      # Generate HTML report
    python rn_linkedin_scraper.py --max-results 50   # Limit results
"""

import argparse
import hashlib
import json
import logging
import random
import re
import threading
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from functools import lru_cache
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import focus

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rn_scraper")


class ResultType(str, Enum):
    JOB = "job"
    POST = "post"


@dataclass
class Opportunity:
    title: str
    result_type: str  # "job" or "post"
    company_or_author: str
    location: str
    url: str
    snippet: str
    relevance_score: float = 0.0
    source_query: str = ""
    source: str = ""  # "linkedin_jobs", "google", "duckduckgo", "bing"
    scraped_at: str = field(default_factory=lambda: _utcnow().isoformat())
    posted_at: str = ""  # ISO date the job/post was published, when known
    job_id: str = ""  # LinkedIn job posting ID, when known
    seniority: str = ""
    employment_type: str = ""
    applicants: str = ""
    description: str = ""  # Truncated job description (LinkedIn detail page)
    # Checked on the FULL description at enrich time: the "no sponsorship"
    # clause usually sits at the very end, past the stored truncation.
    work_auth_blocker: str = ""
    contractor: bool = False

    @property
    def uid(self) -> str:
        return hashlib.md5(self.url.encode()).hexdigest()[:12]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────
# India / Location Filter
# ─────────────────────────────────────────────

INDIA_KEYWORDS = [
    # Country
    "india",
    # Major cities & tech hubs
    "bangalore",
    "bengaluru",
    "mumbai",
    "bombay",
    "delhi",
    "new delhi",
    "hyderabad",
    "pune",
    "chennai",
    "madras",
    "gurgaon",
    "gurugram",
    "noida",
    "kolkata",
    "calcutta",
    "ahmedabad",
    "jaipur",
    "lucknow",
    "chandigarh",
    "indore",
    "kochi",
    "cochin",
    "thiruvananthapuram",
    "trivandrum",
    "coimbatore",
    "nagpur",
    "vizag",
    "visakhapatnam",
    "bhubaneswar",
    "mangalore",
    "mangaluru",
    "mysore",
    "mysuru",
    "surat",
    "vadodara",
    "thane",
    "navi mumbai",
    "faridabad",
    "ghaziabad",
    "mohali",
    # States commonly referenced
    "karnataka",
    "maharashtra",
    "telangana",
    "tamil nadu",
    "uttar pradesh",
    "haryana",
    "kerala",
    "andhra pradesh",
    "west bengal",
    "rajasthan",
    "gujarat",
    # Region patterns
    "apac (india)",
    "asia pacific (india)",
]

# Pre-compile patterns for speed
_india_patterns = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in INDIA_KEYWORDS
]

# Additional regex for tricky cases
_india_remote_patterns = [
    re.compile(r"remote\s*[-–—/,]\s*india", re.IGNORECASE),
    re.compile(r"india\s*[-–—/,]\s*remote", re.IGNORECASE),
    re.compile(r"remote\s*\(india\)", re.IGNORECASE),
    re.compile(r"wfh\s*[-–—/,]?\s*india", re.IGNORECASE),
    re.compile(r"hiring\s+in\s+india", re.IGNORECASE),
    re.compile(r"based\s+in\s+india", re.IGNORECASE),
    re.compile(r"location:\s*india", re.IGNORECASE),
    re.compile(r"(?:IN|IND)\s*[-–—/,]\s*remote", re.IGNORECASE),
]

PREFERRED_REGIONS = [
    "united states",
    "usa",
    "us",
    "canada",
    "europe",
    "european union",
    "eu",
    "uk",
    "united kingdom",
    "germany",
    "france",
    "netherlands",
    "spain",
    "portugal",
    "italy",
    "sweden",
    "denmark",
    "norway",
    "finland",
    "switzerland",
    "ireland",
    "austria",
    "belgium",
    "poland",
    "czech",
    "brazil",
    "brasil",
    "latam",
    "latin america",
    "australia",
    "new zealand",
    "remote",
    "worldwide",
    "global",
    "anywhere",
]


def is_india_related(text: str) -> bool:
    """Check if text contains India-related references."""
    if not text:
        return False
    text_lower = text.lower()

    # Quick check: if "india" substring is present, verify it's not "indiana" etc.
    if "india" in text_lower:
        # Use word boundary to avoid false positives like "Indiana"
        if re.search(r"\bindia\b", text_lower) and not re.search(r"\bindian[a-z]", text_lower):
            return True

    # Check city/state patterns
    for pat in _india_patterns:
        if pat.search(text):
            return True

    # Check remote-india combos
    for pat in _india_remote_patterns:
        if pat.search(text):
            return True

    return False


@lru_cache(maxsize=4096)
def _word_pattern(keyword: str) -> re.Pattern:
    """Whole-word, case-insensitive pattern so 'us' doesn't match 'business'
    and 'expo' doesn't match 'exposure'."""
    return re.compile(r"(?<!\w)" + re.escape(keyword.lower()) + r"(?!\w)", re.IGNORECASE)


def _contains_word(text: str, keyword: str) -> bool:
    return bool(_word_pattern(keyword).search(text))


def has_preferred_region(text: str) -> bool:
    """Check if text mentions a preferred region."""
    if not text:
        return False
    return any(_contains_word(text, region) for region in PREFERRED_REGIONS)


# ─────────────────────────────────────────────
# Relevance Scoring
# ─────────────────────────────────────────────

HIRING_SIGNALS = {
    # Strong hiring intent
    "we are hiring": 10,
    "we're hiring": 10,
    "now hiring": 10,
    "hiring now": 10,
    "join our team": 8,
    "join us": 6,
    "looking for": 7,
    "seeking": 6,
    "open position": 9,
    "open role": 9,
    "job opening": 9,
    "apply now": 8,
    "apply here": 8,
    "apply today": 8,
    "send your resume": 7,
    "send your cv": 7,
    "dm me": 5,
    "reach out": 4,
    "opportunity": 5,
    "career": 4,
    "remote position": 7,
    "fully remote": 8,
    "100% remote": 8,
    "work from anywhere": 7,
    "work from home": 5,
    "full-time": 5,
    "full time": 5,
    "part-time": 4,
    "part time": 4,
    "contract": 4,
    "freelance": 4,
    "contractor": 4,
    # Mobile / React Native signals (heavily weighted)
    "react native": 15,
    "react-native": 15,
    "reactnative": 15,
    "expo": 12,
    "mobile developer": 10,
    "mobile engineer": 10,
    "mobile development": 8,
    "mobile app": 8,
    "cross-platform": 6,
    "cross platform": 6,
    "ios and android": 6,
    "android and ios": 6,
    "ios/android": 6,
    "android/ios": 6,
    # Secondary tech (lower weight)
    "typescript": 2,
    "javascript": 1,
    "ios": 2,
    "android": 2,
}


def _recency_bonus(posted_at: str) -> float:
    """Fresh listings get more replies — early applicants win."""
    age = _age_days_from_iso(posted_at)
    if age is None:
        return 0.0
    if age <= 1:
        return 10.0
    if age <= 3:
        return 6.0
    if age <= 7:
        return 3.0
    return 0.0


def _applicants_bonus(applicants: str) -> float:
    """'Be among the first 25 applicants' / '12 applicants' → boost low competition."""
    m = re.search(r"(\d+)", applicants or "")
    if not m:
        return 0.0
    n = int(m.group(1))
    if n <= 25:
        return 5.0
    if n <= 50:
        return 2.0
    return 0.0


def compute_relevance(
    title: str,
    snippet: str,
    result_type: str,
    extra_signals: dict = None,
    posted_at: str = "",
    applicants: str = "",
) -> float:
    """Score 0-100 based on hiring intent, tech relevance and freshness."""
    combined = f"{title} {snippet}"
    score = 0.0

    # Merge so a signal present in both maps is only counted once
    signals = dict(HIRING_SIGNALS)
    if extra_signals:
        signals.update({k.lower(): v for k, v in extra_signals.items()})

    for signal, weight in signals.items():
        if _contains_word(combined, signal):
            score += weight

    # Title matches are the strongest signal of a real fit
    if extra_signals:
        if any(_contains_word(title, s) for s, w in extra_signals.items() if w >= 10):
            score += 10

    # Boost actual job listings
    if result_type == ResultType.JOB:
        score += 15

    # Boost if location is in preferred region
    if has_preferred_region(combined):
        score += 5

    score += _recency_bonus(posted_at)
    score += _applicants_bonus(applicants)

    # Normalize to 0-100
    return min(round(score, 1), 100.0)


# ─────────────────────────────────────────────
# HTTP Client
# ─────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
]

HEADERS = {
    "User-Agent": USER_AGENTS[0],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}

# Rate limiting — tracked per host, so slow engines don't delay the others
MIN_REQUEST_INTERVAL = 2.0  # seconds between requests to the same host
MAX_JITTER = 1.5  # random extra delay; fixed intervals look like a bot
_last_request_by_host: dict[str, float] = {}
_throttle_lock = threading.Lock()

# Hosts that answered with a block page. Skip them for the rest of the run
# instead of hammering them (which only makes the block last longer).
_blocked_hosts: set[str] = set()


def make_session() -> requests.Session:
    """Session with connection pooling and retries with exponential backoff.
    Retry honours the server's Retry-After header on 429/503."""
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=3,
        backoff_factor=2,  # 2s, 4s, 8s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _wait_for_host(host: str):
    with _throttle_lock:
        now = time.time()
        next_allowed = _last_request_by_host.get(host, 0.0) + MIN_REQUEST_INTERVAL
        wait = max(0.0, next_allowed - now) + random.uniform(0, MAX_JITTER)
        # Reserve the slot before sleeping so concurrent callers queue up
        _last_request_by_host[host] = now + wait
    if wait:
        time.sleep(wait)


def reset_blocked_hosts():
    _blocked_hosts.clear()


def throttled_get(url: str, session: requests.Session, timeout: int = 15) -> Optional[requests.Response]:
    """GET with per-host rate limiting, UA rotation, retries and block detection."""
    host = urllib.parse.urlparse(url).netloc
    if host in _blocked_hosts:
        log.debug("Skipping %s (host blocked us earlier this run)", url)
        return None

    _wait_for_host(host)
    headers = {"User-Agent": random.choice(USER_AGENTS)}

    try:
        resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except requests.RequestException as e:
        log.debug("Request failed for %s: %s", url, e)
        return None

    if resp.status_code == 200:
        return resp
    # 202 = DuckDuckGo anomaly page, 999 = LinkedIn bot wall, 403 = forbidden
    if resp.status_code in (202, 403, 999):
        log.warning("Blocked by %s (HTTP %d) – skipping host for this run", host, resp.status_code)
        _blocked_hosts.add(host)
    elif resp.status_code == 429:
        log.warning("Still rate limited on %s after retries", host)
    else:
        log.debug("HTTP %d for %s", resp.status_code, url)
    return None


# ─────────────────────────────────────────────
# LinkedIn Public Scrapers
# ─────────────────────────────────────────────

# Search queries to cover job + post discovery
SEARCH_QUERIES = [
    # Exact-phrase queries — quotes force LinkedIn to match "react native" as a unit
    '"react native" developer remote',
    '"react native" engineer remote',
    '"react native" mobile developer remote',
    '"react native" senior developer remote',
    '"react native" lead remote',
    '"react native" freelance remote',
    '"react native" contract remote',
    # Expo / mobile specific
    'expo "react native" remote',
    '"expo" mobile developer remote',
    '"react native" iOS Android remote',
    '"mobile engineer" "react native" remote',
    '"cross-platform" "react native" remote',
]


# Time range presets: maps label → (linkedin_f_TPR_seconds, max_age_days, ddg_df, google_tbs)
TIME_RANGES = {
    "24h":    (86400,      1,  "d",  "qdr:d"),
    "3d":     (259200,     3,  "w",  "qdr:w"),
    "1w":     (604800,     7,  "w",  "qdr:w"),
    "2w":     (1209600,   14,  "m",  "qdr:m"),
    "1m":     (2592000,   30,  "m",  "qdr:m"),
    "3m":     (7776000,   90,  "m",  "qdr:m"),
}

DEFAULT_TIME_RANGE = "1w"


LINKEDIN_GUEST_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LINKEDIN_GUEST_JOB = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
LINKEDIN_PAGE_SIZE = 10  # cards per page returned by the guest API
LINKEDIN_MAX_PAGES = 4  # pages per query (40 jobs)


def build_linkedin_job_search_url(
    query: str,
    start: int = 0,
    time_range: str = DEFAULT_TIME_RANGE,
    location: str = "Worldwide",
    contract_only: bool = False,
) -> str:
    """Build LinkedIn guest job search API URL (no auth required).

    The guest API returns bare job-card HTML and supports pagination via
    `start`, unlike the full search page which shows only the first page
    and often redirects to a login wall."""
    tpr_seconds = TIME_RANGES.get(time_range, TIME_RANGES[DEFAULT_TIME_RANGE])[0]
    params = {
        "keywords": query,
        "location": location,
        "f_TPR": f"r{tpr_seconds}",
        "f_WT": "2",  # remote only
        "sortBy": "DD",  # newest first
        "start": start,
    }
    if contract_only:
        params["f_JT"] = "C"  # job type: contract
    return LINKEDIN_GUEST_SEARCH + "?" + urllib.parse.urlencode(params)


_linkedin_job_id_re = re.compile(r"/jobs/view/(?:[^/?#]*-)?(\d{8,})")


def extract_linkedin_job_id(url: str) -> str:
    """Pull the numeric job ID out of any LinkedIn job URL
    (www./br./uk. subdomains, with or without the title slug)."""
    m = _linkedin_job_id_re.search(url or "")
    return m.group(1) if m else ""


def canonical_job_url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{job_id}/"


def build_google_linkedin_search_url(query: str, search_type: str = "jobs", time_range: str = DEFAULT_TIME_RANGE) -> str:
    """Build Google search URL targeting LinkedIn content."""
    if search_type == "jobs":
        site_query = f'site:linkedin.com/jobs "{query}" remote'
    else:
        site_query = f'site:linkedin.com/posts "{query}" remote (hiring OR "looking for" OR opportunity OR "open role")'
    google_tbs = TIME_RANGES.get(time_range, TIME_RANGES[DEFAULT_TIME_RANGE])[3]
    params = {
        "q": site_query,
        "num": 20,
        "tbs": google_tbs,
    }
    return "https://www.google.com/search?" + urllib.parse.urlencode(params)


def build_google_search_url(query: str) -> str:
    """Build a generic Google search URL for LinkedIn React Native results."""
    params = {
        "q": f'site:linkedin.com "{query}"',
        "num": 15,
    }
    return "https://www.google.com/search?" + urllib.parse.urlencode(params)


def scrape_linkedin_jobs_page(
    session: requests.Session,
    query: str,
    time_range: str = DEFAULT_TIME_RANGE,
    max_pages: int = LINKEDIN_MAX_PAGES,
    location: str = "Worldwide",
    contract_only: bool = False,
) -> list[Opportunity]:
    """Scrape LinkedIn's guest job search API, following pagination."""
    results = []
    log.info("Scraping LinkedIn jobs [%s, %s]: %s", time_range, location, query)

    for page in range(max_pages):
        url = build_linkedin_job_search_url(
            query, start=page * LINKEDIN_PAGE_SIZE, time_range=time_range,
            location=location, contract_only=contract_only,
        )
        resp = throttled_get(url, session)
        if not resp:
            break
        page_results = _parse_linkedin_job_cards(resp.text, query)
        results.extend(page_results)
        # A short page means we reached the end of the result list
        if len(page_results) < LINKEDIN_PAGE_SIZE:
            break

    log.info("  Found %d jobs for '%s'", len(results), query)
    return results


def _parse_linkedin_job_cards(html: str, query: str) -> list[Opportunity]:
    results = []
    soup = BeautifulSoup(html, "html.parser")

    # LinkedIn public job cards
    job_cards = soup.select(
        "div.base-card, "
        "li.jobs-search__result-card, "
        "div.job-search-card, "
        "li.result-card"
    )

    for card in job_cards:
        try:
            # Title
            title_el = card.select_one(
                "h3.base-search-card__title, "
                "h3.job-search-card__title, "
                "span.screen-reader-text, "
                "h3.base-card__title, "
                "a.base-card__full-link"
            )
            title = title_el.get_text(strip=True) if title_el else ""

            # Company
            company_el = card.select_one(
                "h4.base-search-card__subtitle, "
                "a.job-search-card__subtitle-link, "
                "h4.base-card__subtitle"
            )
            company = company_el.get_text(strip=True) if company_el else "Unknown"

            # Location
            loc_el = card.select_one(
                "span.job-search-card__location, "
                "span.base-search-card__metadata"
            )
            location = loc_el.get_text(strip=True) if loc_el else "Not specified"

            # URL
            link_el = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
            job_url = link_el["href"].split("?")[0] if link_el and link_el.get("href") else ""
            if not job_url:
                link_el = card.find("a", href=True)
                job_url = link_el["href"].split("?")[0] if link_el else ""

            if not title or not job_url:
                continue

            # Job ID: prefer the card's URN, fall back to the URL
            urn = card.get("data-entity-urn", "")
            job_id = urn.rsplit(":", 1)[-1] if urn.startswith("urn:li:jobPosting:") else ""
            job_id = job_id or extract_linkedin_job_id(job_url)
            if job_id:
                job_url = canonical_job_url(job_id)

            # Posted date: <time datetime="2026-10-05">
            time_el = card.select_one("time[datetime]")
            posted_at = time_el["datetime"] if time_el else ""

            # Build snippet
            snippet = f"{title} at {company}"
            if location and location != "Not specified":
                snippet += f" — {location}"

            results.append(
                Opportunity(
                    title=title,
                    result_type=ResultType.JOB,
                    company_or_author=company,
                    location=location,
                    url=job_url if job_url.startswith("http") else f"https://www.linkedin.com{job_url}",
                    snippet=snippet,
                    source_query=query,
                    source="linkedin_jobs",
                    posted_at=posted_at,
                    job_id=job_id,
                )
            )
        except Exception as e:
            log.debug("Error parsing job card: %s", e)
            continue

    return results


def _criteria_value(soup: BeautifulSoup, label: str) -> str:
    for item in soup.select("li.description__job-criteria-item"):
        header = item.select_one(".description__job-criteria-subheader")
        value = item.select_one(".description__job-criteria-text")
        if header and value and label.lower() in header.get_text(strip=True).lower():
            return value.get_text(strip=True)
    return ""


DESCRIPTION_MAX_CHARS = 1500


def enrich_linkedin_job(session: requests.Session, opp: Opportunity) -> bool:
    """Fetch the job's detail page and fill description, seniority,
    employment type and applicant count. Returns True on success."""
    if not opp.job_id:
        return False
    resp = throttled_get(LINKEDIN_GUEST_JOB.format(job_id=opp.job_id), session)
    if not resp:
        return False
    soup = BeautifulSoup(resp.text, "html.parser")

    desc_el = soup.select_one("div.description__text, div.show-more-less-html__markup")
    full_text = desc_el.get_text(" ", strip=True) if desc_el else ""
    opp.description = full_text[:DESCRIPTION_MAX_CHARS]
    opp.seniority = _criteria_value(soup, "Seniority level")
    opp.employment_type = _criteria_value(soup, "Employment type")
    opp.work_auth_blocker = focus.sponsorship_blocker(full_text)
    opp.contractor = focus.is_contractor(f"{opp.title} {full_text}", opp.employment_type)

    applicants_el = soup.select_one(".num-applicants__caption, .num-applicants__figure")
    if applicants_el:
        opp.applicants = applicants_el.get_text(" ", strip=True)

    if opp.location in ("", "Not specified"):
        loc_el = soup.select_one(".topcard__flavor--bullet")
        if loc_el:
            opp.location = loc_el.get_text(strip=True)
    return True


def enrich_linkedin_jobs(session: requests.Session, opportunities: list[Opportunity], limit: int) -> int:
    """Enrich up to `limit` LinkedIn job results. Returns how many succeeded."""
    done = 0
    for opp in [o for o in opportunities if o.job_id][:limit]:
        if enrich_linkedin_job(session, opp):
            done += 1
    return done


def scrape_google_for_linkedin(session: requests.Session, query: str, search_type: str = "jobs", time_range: str = DEFAULT_TIME_RANGE) -> list[Opportunity]:
    """Use Google to find LinkedIn job/post URLs."""
    results = []
    url = build_google_linkedin_search_url(query, search_type, time_range=time_range)
    log.info("Google search [%s]: %s", search_type, query)

    resp = throttled_get(url, session, timeout=10)
    if not resp:
        return results

    soup = BeautifulSoup(resp.text, "html.parser")

    # Google result links
    for g_result in soup.select("div.g, div[data-sokoban-container]"):
        try:
            link_el = g_result.select_one("a[href]")
            if not link_el:
                continue
            href = link_el["href"]

            # Filter for LinkedIn URLs
            if "linkedin.com" not in href:
                continue

            # Determine type
            if "/jobs/" in href or "/job/" in href:
                rtype = ResultType.JOB
            elif "/posts/" in href or "/pulse/" in href or "/feed/" in href:
                rtype = ResultType.POST
            else:
                rtype = ResultType.POST if search_type == "posts" else ResultType.JOB

            # Title from Google result
            title_el = g_result.select_one("h3")
            title = title_el.get_text(strip=True) if title_el else "LinkedIn Result"

            # Snippet from Google
            snippet_el = g_result.select_one(
                "div.VwiC3b, span.aCOpRe, div[data-sncf], div[style*='line-clamp']"
            )
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            # Extract company/author from title patterns
            company = "Unknown"
            if " - " in title:
                parts = title.split(" - ")
                if len(parts) >= 2:
                    company = parts[1].strip()
            elif " | " in title:
                parts = title.split(" | ")
                if len(parts) >= 2:
                    company = parts[1].strip()
            elif " at " in title.lower():
                idx = title.lower().index(" at ")
                company = title[idx + 4 :].strip().split(" - ")[0].strip()

            # Extract location hints from snippet
            location = "Not specified"
            loc_patterns = [
                r"(?:Location|Based in|Located in)[:\s]+([A-Za-z\s,]+?)(?:\.|;|\n|$)",
                r"(?:Remote|Hybrid|On-?site)\s*[-–—/,]\s*([A-Za-z\s,]+?)(?:\.|;|\n|$)",
            ]
            for pat in loc_patterns:
                m = re.search(pat, snippet, re.IGNORECASE)
                if m:
                    location = m.group(1).strip()[:60]
                    break

            # Clean URL
            clean_url = href.split("?")[0].split("&")[0]
            if not clean_url.startswith("http"):
                continue
            job_id = extract_linkedin_job_id(clean_url)
            if job_id:
                clean_url = canonical_job_url(job_id)

            results.append(
                Opportunity(
                    title=title[:200],
                    result_type=rtype,
                    company_or_author=company[:100],
                    location=location,
                    url=clean_url,
                    snippet=snippet[:300] if snippet else title,
                    source_query=query,
                    source="google",
                    job_id=job_id,
                )
            )
        except Exception as e:
            log.debug("Error parsing Google result: %s", e)
            continue

    log.info("  Found %d results for '%s' [%s]", len(results), query, search_type)
    return results


def scrape_linkedin_posts_via_google(session: requests.Session, query: str, time_range: str = DEFAULT_TIME_RANGE) -> list[Opportunity]:
    """Search Google for LinkedIn posts about React Native hiring."""
    return scrape_google_for_linkedin(session, query, search_type="posts", time_range=time_range)


def _parse_search_engine_results(soup: BeautifulSoup, query: str, engine: str) -> list[Opportunity]:
    """Parse LinkedIn post results from a search engine results page (DuckDuckGo or Bing)."""
    results = []

    # Selectors for both DuckDuckGo and Bing
    result_cards = soup.select(
        "article, "                 # DDG organic results
        "div.result, "              # DDG classic
        "div.results_links, "       # DDG alternate
        "li.b_algo, "              # Bing
        "div.b_algo"               # Bing alternate
    )

    # Fallback: also grab all links to linkedin.com posts directly
    if not result_cards:
        result_cards = soup.find_all("a", href=re.compile(r"linkedin\.com/(posts|pulse|feed)"))

    for card in result_cards:
        try:
            # Find the main link
            link_el = None
            if card.name == "a":
                link_el = card
            else:
                link_el = card.select_one(
                    "a[href*='linkedin.com/posts'], "
                    "a[href*='linkedin.com/pulse'], "
                    "a[href*='linkedin.com/feed'], "
                    "h2 a[href*='linkedin.com'], "
                    "a[data-testid='result-title-a'], "
                    "a.result__a"
                )
            if not link_el:
                # Try any linkedin link in the card
                link_el = card.find("a", href=re.compile(r"linkedin\.com"))
            if not link_el:
                continue

            href = link_el.get("href", "")

            # DDG uses redirect URLs — extract the actual URL
            if "duckduckgo.com" in href and "uddg=" in href:
                parsed = urllib.parse.urlparse(href)
                qs = urllib.parse.parse_qs(parsed.query)
                href = qs.get("uddg", [href])[0]

            if "linkedin.com" not in href:
                continue

            # Determine type from URL
            if "/posts/" in href or "/pulse/" in href or "/feed/" in href:
                rtype = ResultType.POST
            elif "/jobs/" in href or "/job/" in href:
                continue  # Skip jobs — we only want posts here
            else:
                rtype = ResultType.POST

            # Title
            title_el = card.select_one("h2, h3, a[data-testid='result-title-a']")
            title = title_el.get_text(strip=True) if title_el else link_el.get_text(strip=True)
            if not title or title == href:
                title = "LinkedIn Post"

            # Snippet
            snippet_el = card.select_one(
                "span[data-testid='result-snippet'], "
                "div.result__snippet, "
                "p, "
                "div.b_caption p, "
                "span.b_lineclamp2"
            )
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            # Extract author from title patterns like "Author on LinkedIn: ..."
            author = "Unknown"
            if " on LinkedIn" in title:
                author = title.split(" on LinkedIn")[0].strip()
            elif " - " in title:
                author = title.split(" - ")[0].strip()
            elif " | " in title:
                author = title.split(" | ")[0].strip()

            clean_url = href.split("?")[0]
            if not clean_url.startswith("http"):
                continue

            results.append(
                Opportunity(
                    title=title[:200],
                    result_type=rtype,
                    company_or_author=author[:100],
                    location="Not specified",
                    url=clean_url,
                    snippet=snippet[:300] if snippet else title,
                    source_query=query,
                    source=engine,
                    posted_at=_linkedin_post_date_iso(clean_url),
                )
            )
        except Exception as e:
            log.debug("Error parsing %s result: %s", engine, e)
            continue

    log.info("  Found %d results for '%s' [%s]", len(results), query, engine)
    return results


def scrape_duckduckgo_for_linkedin_posts(session: requests.Session, query: str, time_range: str = DEFAULT_TIME_RANGE) -> list[Opportunity]:
    """Use DuckDuckGo to find LinkedIn posts (does not block scrapers like Google does)."""
    ddg_df = TIME_RANGES.get(time_range, TIME_RANGES[DEFAULT_TIME_RANGE])[2]
    search_query = f'site:linkedin.com/posts "{query}" remote hiring'
    params = {"q": search_query, "df": ddg_df}
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode(params)
    log.info("DuckDuckGo search [posts]: %s", query)

    resp = throttled_get(url, session, timeout=15)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    return _parse_search_engine_results(soup, query, "duckduckgo")


def scrape_bing_for_linkedin_posts(session: requests.Session, query: str, time_range: str = DEFAULT_TIME_RANGE) -> list[Opportunity]:
    """Use Bing as fallback for LinkedIn posts."""
    search_query = f'site:linkedin.com/posts "{query}" remote (hiring OR "looking for" OR "open role")'
    # Bing doesn't have a clean time param for HTML scraping, rely on post-filter
    params = {"q": search_query, "count": 20}  # past month
    url = "https://www.bing.com/search?" + urllib.parse.urlencode(params)
    log.info("Bing search [posts]: %s", query)

    resp = throttled_get(url, session, timeout=10)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    return _parse_search_engine_results(soup, query, "bing")


def scrape_yahoo_for_linkedin_posts(session: requests.Session, query: str, time_range: str = DEFAULT_TIME_RANGE) -> list[Opportunity]:
    """Find LinkedIn posts via Yahoo (Bing-powered), using the `ddgs` library.

    ddgs impersonates a real browser's TLS fingerprint, which plain `requests`
    can't do — Yahoo blocks requests. Quotes and time filters make Yahoo return
    nothing for site: queries, so we drop them and filter by the date encoded
    in each post URL instead (filter_stale)."""
    try:
        from ddgs import DDGS
        from ddgs.exceptions import DDGSException
    except ImportError:
        log.warning("ddgs not installed – skipping Yahoo")
        return []

    search_query = f"site:linkedin.com/posts {query.replace(chr(34), '')}"
    log.info("Yahoo search [posts]: %s", query)
    _wait_for_host("search.yahoo.com")
    try:
        hits = DDGS(timeout=15).text(search_query, max_results=20, backend="yahoo")
    except DDGSException as e:
        log.debug("Yahoo returned nothing for %s: %s", query, e)
        return []
    except Exception as e:
        log.warning("Yahoo search failed: %s", e)
        return []

    results = []
    for hit in hits:
        href = (hit.get("href") or "").split("?")[0]
        if "linkedin.com/posts/" not in href and "linkedin.com/feed/" not in href:
            continue
        title = (hit.get("title") or "LinkedIn Post")[:200]
        author = title.split(" on LinkedIn")[0].split(" | ")[0].split(" - ")[0].strip() or "Unknown"
        results.append(Opportunity(
            title=title,
            result_type=ResultType.POST,
            company_or_author=author[:100],
            location="Not specified",
            url=href,
            snippet=(hit.get("body") or title)[:300],
            source_query=query,
            source="yahoo",
            posted_at=_linkedin_post_date_iso(href),
        ))
    log.info("  Found %d results for '%s' [yahoo]", len(results), query)
    return results


def enrich_linkedin_post(session: requests.Session, opp: Opportunity) -> bool:
    """Public post pages show the full text without login. Search snippets
    are ~150 chars, so reading the post is what makes filtering possible."""
    resp = throttled_get(opp.url, session)
    if not resp:
        return False
    soup = BeautifulSoup(resp.text, "html.parser")
    body = soup.select_one(
        '[data-test-id="main-feed-activity-card__commentary"], .attributed-text-segment-list__content'
    )
    text = body.get_text(" ", strip=True) if body else ""
    if not text:
        meta = soup.select_one('meta[property="og:description"]')
        text = meta.get("content", "") if meta else ""
    if not text:
        return False
    opp.description = text[:DESCRIPTION_MAX_CHARS]
    opp.work_auth_blocker = focus.sponsorship_blocker(text)
    opp.contractor = focus.is_contractor(text)

    author_el = soup.select_one('[data-tracking-control-name="public_post_feed-actor-name"]')
    if author_el and opp.company_or_author in ("", "Unknown"):
        opp.company_or_author = author_el.get_text(strip=True)[:100]
    return True


def enrich_linkedin_posts(session: requests.Session, opportunities: list[Opportunity], limit: int) -> int:
    done = 0
    for opp in [o for o in opportunities if o.result_type == ResultType.POST][:limit]:
        if enrich_linkedin_post(session, opp):
            done += 1
    return done


# ─────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────


def dedup_key(opp: Opportunity) -> str:
    """Same job can appear as br.linkedin.com/jobs/view/slug-123 and
    www.linkedin.com/jobs/view/123 — the job ID is the real identity."""
    job_id = opp.job_id or extract_linkedin_job_id(opp.url)
    if job_id:
        return f"job:{job_id}"
    parsed = urllib.parse.urlparse(opp.url.lower())
    host = re.sub(r"^[a-z]{2}\.linkedin\.com$", "www.linkedin.com", parsed.netloc)
    host = "www.linkedin.com" if host == "linkedin.com" else host
    return f"url:{host}{parsed.path.rstrip('/')}"


def _title_company_key(opp: Opportunity) -> str:
    """Companies often repost the same job under several IDs."""
    norm = lambda t: re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
    return f"{norm(opp.title)}|{norm(opp.company_or_author)}"


def deduplicate(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Remove duplicates by job ID / normalized URL, then reposted jobs
    (same title + company). Keeps the first occurrence."""
    seen = set()
    seen_jobs = set()
    unique = []
    for opp in opportunities:
        key = dedup_key(opp)
        if key in seen:
            continue
        seen.add(key)
        if key.startswith("job:") and opp.company_or_author not in ("", "Unknown"):
            tc = _title_company_key(opp)
            if tc in seen_jobs:
                continue
            seen_jobs.add(tc)
        unique.append(opp)
    return unique


REMOTE_KEYWORDS = [
    "remote",
    "work from home",
    "wfh",
    "work from anywhere",
    "worldwide",
    "distributed",
    "anywhere",
    "fully remote",
    "100% remote",
    "telecommute",
    "home office",
]

_remote_patterns = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in REMOTE_KEYWORDS
]


def is_remote(text: str) -> bool:
    """Check if text signals a remote opportunity."""
    if not text:
        return False
    for pat in _remote_patterns:
        if pat.search(text):
            return True
    return False


ONSITE_KEYWORDS = [
    "on-site",
    "onsite",
    "on site",
    "in-office",
    "in office",
    "office-based",
    "office based",
]

_onsite_patterns = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in ONSITE_KEYWORDS
]

# "hybrid" alone is ambiguous but we exclude it — user wants fully remote
_hybrid_pattern = re.compile(r"\bhybrid\b", re.IGNORECASE)


def is_onsite_or_hybrid(text: str) -> bool:
    """Check if text signals an onsite or hybrid role."""
    if not text:
        return False
    for pat in _onsite_patterns:
        if pat.search(text):
            return True
    if _hybrid_pattern.search(text):
        return True
    return False


def filter_non_remote(opportunities: list[Opportunity], defer_posts: bool = False) -> list[Opportunity]:
    """Keep only remote opportunities.

    For results from LinkedIn's job search (source=linkedin_jobs), the URL
    already includes f_WT=2 (remote filter), so we trust that and only
    reject if the listing is explicitly onsite/hybrid.

    For results from search engines (posts, Google, DDG, Bing), we require
    an explicit remote signal in the text."""
    filtered = []
    excluded_count = 0
    for opp in opportunities:
        combined_text = " ".join(
            [opp.title, opp.company_or_author, opp.location, opp.snippet]
        )

        # Always reject if explicitly onsite/hybrid
        if is_onsite_or_hybrid(combined_text):
            excluded_count += 1
            log.debug("Excluded (onsite/hybrid): %s | %s", opp.title[:60], opp.location)
            continue

        # LinkedIn direct job results already filtered by f_WT=2 — trust them.
        # Posts get checked later on their full text (filter_posts_not_remote).
        if opp.source == "linkedin_jobs" or (defer_posts and opp.result_type == ResultType.POST):
            filtered.append(opp)
            continue

        # For search engine results, require an explicit remote keyword
        if is_remote(combined_text):
            filtered.append(opp)
        else:
            excluded_count += 1
            log.debug("Excluded (no remote signal): %s | %s", opp.title[:60], opp.location)

    if excluded_count:
        log.info("Filtered out %d non-remote results", excluded_count)
    return filtered


def filter_india(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Apply India exclusion filter."""
    filtered = []
    excluded_count = 0
    for opp in opportunities:
        # Check all text fields for India references
        combined_text = " ".join(
            [opp.title, opp.company_or_author, opp.location, opp.snippet, opp.source_query]
        )
        if is_india_related(combined_text):
            excluded_count += 1
            log.debug("Excluded (India): %s | %s", opp.title[:60], opp.location)
            continue
        filtered.append(opp)

    if excluded_count:
        log.info("Filtered out %d India-related results", excluded_count)
    return filtered


def _build_tech_patterns(keywords: list[str]):
    """Compile regex patterns for a list of tech keywords."""
    return [re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE) for kw in keywords]


def _text_matches_patterns(text: str, patterns) -> bool:
    """Check if text matches any of the compiled patterns."""
    if not text:
        return False
    for pat in patterns:
        if pat.search(text):
            return True
    return False


def filter_tech_relevance(opportunities: list[Opportunity], tech_keywords: list[str]) -> list[Opportunity]:
    """Keep only opportunities matching the selected tech keywords.

    Checks the job description when it was fetched. For LinkedIn direct
    results, also checks source_query since scraped HTML often truncates titles."""
    patterns = _build_tech_patterns(tech_keywords)
    filtered = []
    excluded_count = 0
    for opp in opportunities:
        combined_text = " ".join([opp.title, opp.company_or_author, opp.snippet, opp.description])
        if _text_matches_patterns(combined_text, patterns):
            filtered.append(opp)
            continue

        # Trust LinkedIn's search relevance for direct results
        if opp.source == "linkedin_jobs" and _text_matches_patterns(opp.source_query, patterns):
            filtered.append(opp)
            continue

        excluded_count += 1
        log.debug("Excluded (tech mismatch): %s", opp.title[:60])

    if excluded_count:
        log.info("Filtered out %d tech-mismatched results", excluded_count)
    return filtered


# LinkedIn activity IDs encode a timestamp: (activity_id >> 22) gives ms since epoch
_linkedin_activity_re = re.compile(r"activity[:-](\d{19})")
# Also match ugcPost IDs in URLs
_linkedin_ugc_re = re.compile(r"ugcPost[:-](\d{19})")

def _linkedin_post_datetime(url: str) -> Optional[datetime]:
    """Decode the publish time from a LinkedIn post URL activity/ugcPost ID."""
    for pattern in (_linkedin_activity_re, _linkedin_ugc_re):
        m = pattern.search(url)
        if m:
            try:
                activity_id = int(m.group(1))
                # LinkedIn uses Twitter snowflake-style IDs: timestamp = id >> 22
                timestamp_ms = activity_id >> 22
                return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                return None
    return None


def _linkedin_post_date_iso(url: str) -> str:
    dt = _linkedin_post_datetime(url)
    return dt.date().isoformat() if dt else ""


def _extract_linkedin_post_age_days(url: str) -> Optional[float]:
    """Extract post age in days from LinkedIn post URL activity/ugcPost ID.
    Returns None if no timestamp can be extracted."""
    dt = _linkedin_post_datetime(url)
    if dt is None:
        return None
    return (_utcnow() - dt).total_seconds() / 86400


def _age_days_from_iso(value: str) -> Optional[float]:
    """Age in days of an ISO date ('2026-10-05') or datetime string."""
    if not value:
        return None
    try:
        if len(value) == 10:
            return float((_utcnow().date() - date.fromisoformat(value)).days)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (_utcnow() - dt).total_seconds() / 86400
    except ValueError:
        return None


def filter_stale(
    opportunities: list[Opportunity],
    max_age_days: int = 30,
    post_max_age_days: Optional[int] = None,
) -> list[Opportunity]:
    """Remove results older than max_age_days, using the posted date
    (job card <time> tag) or the timestamp encoded in post URLs.
    Posts may get a longer window: search engines index them days late."""
    filtered = []
    excluded_count = 0
    for opp in opportunities:
        limit = max_age_days
        if post_max_age_days is not None and opp.result_type == ResultType.POST:
            limit = max(max_age_days, post_max_age_days)
        age = _age_days_from_iso(opp.posted_at)
        if age is None:
            age = _extract_linkedin_post_age_days(opp.url)
        if age is not None and age > limit:
            excluded_count += 1
            log.debug("Excluded (%.0f days old): %s", age, opp.title[:60])
            continue
        filtered.append(opp)

    if excluded_count:
        log.info("Filtered out %d stale results (>%d days old)", excluded_count, max_age_days)
    return filtered


# Recruiter phrases that almost only appear in India-based hiring posts
_INDIA_HIRING_PHRASES = re.compile(
    r"\b(?:immediate\s+joiners?|notice\s+period|lpa|ctc|lakhs?|serving\s+notice)\b", re.IGNORECASE
)


def filter_india_posts(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Second India pass for posts, on the full post text."""
    filtered = []
    excluded = 0
    for opp in opportunities:
        if opp.result_type == ResultType.POST and opp.description and (
            is_india_related(opp.description) or _INDIA_HIRING_PHRASES.search(opp.description)
        ):
            excluded += 1
            continue
        filtered.append(opp)
    if excluded:
        log.info("Filtered out %d India-related posts (full text)", excluded)
    return filtered


def filter_posts_not_remote(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Posts: with the full text, require a remote signal and no onsite/hybrid."""
    filtered = []
    for opp in opportunities:
        if opp.result_type == ResultType.POST:
            text = " ".join([opp.title, opp.snippet, opp.description])
            if is_onsite_or_hybrid(text) or not is_remote(text):
                continue
        filtered.append(opp)
    return filtered


def filter_sponsorship(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Drop jobs that need local work authorization, citizenship, clearance
    or visa sponsorship (see focus.py)."""
    filtered = []
    excluded = 0
    for opp in opportunities:
        text = " ".join([opp.title, opp.location, opp.snippet, opp.description])
        reason = opp.work_auth_blocker or focus.sponsorship_blocker(text)
        if reason:
            excluded += 1
            log.debug("Excluded (needs work authorization: %r): %s", reason, opp.title[:60])
            continue
        filtered.append(opp)
    if excluded:
        log.info("Filtered out %d results needing work authorization/sponsorship", excluded)
    return filtered


def filter_contract(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Keep only contractor / freelance / B2B work."""
    filtered = [
        o for o in opportunities
        if o.contractor or focus.is_contractor(" ".join([o.title, o.snippet, o.description]), o.employment_type)
    ]
    log.info("Contract filter kept %d of %d", len(filtered), len(opportunities))
    return filtered


def _focus_adjustment(opp: Opportunity) -> float:
    """Boost roles open to people abroad, penalise country-only remote roles."""
    text = " ".join([opp.title, opp.location, opp.snippet, opp.description])
    bonus = sum(w for s, w in focus.OPEN_TO_ABROAD_SIGNALS.items() if _contains_word(text, s))
    bonus = min(bonus, 25)  # many weak signals shouldn't beat tech fit
    if focus.looks_country_only(opp.location, f"{opp.snippet} {opp.description}"):
        bonus -= focus.COUNTRY_ONLY_PENALTY
    return bonus


def rank_opportunities(opportunities: list[Opportunity], extra_signals: dict = None) -> list[Opportunity]:
    """Score and sort by relevance."""
    for opp in opportunities:
        text = f"{opp.snippet} {opp.description}".strip()
        opp.relevance_score = compute_relevance(
            opp.title, text, opp.result_type, extra_signals,
            posted_at=opp.posted_at, applicants=opp.applicants,
        )
        opp.relevance_score = max(0.0, min(100.0, round(opp.relevance_score + _focus_adjustment(opp), 1)))
    return sorted(opportunities, key=lambda o: (o.relevance_score, o.posted_at), reverse=True)


def run_scraper(
    max_results: int = 100,
    queries: Optional[list[str]] = None,
    verbose: bool = False,
    time_range: str = DEFAULT_TIME_RANGE,
    techs: Optional[list[str]] = None,
    engines: Optional[list[str]] = None,
    enrich: bool = True,
    locations: Optional[list[str]] = None,
    contract_only: bool = False,
    exclude_sponsorship: bool = True,
) -> list[Opportunity]:
    """CLI entry point. Same pipeline as the web app, with log output.

    Args:
        time_range: One of "24h", "3d", "1w", "2w", "1m", "3m".
        queries: Optional custom job-search queries (override the tech profiles).
    """
    if verbose:
        log.setLevel(logging.DEBUG)

    def log_progress(event: dict):
        if "log_line" in event:
            log.info(event["log_line"])

    return run_scraper_with_progress(
        max_results=max_results,
        time_range=time_range,
        on_progress=log_progress,
        techs=techs,
        engines=engines,
        custom_queries=queries,
        enrich=enrich,
        locations=locations,
        contract_only=contract_only,
        exclude_sponsorship=exclude_sponsorship,
    )


POST_MIN_WINDOW_DAYS = 7  # search engines index LinkedIn posts days late

ALL_ENGINES = ["linkedin", "yahoo", "duckduckgo", "bing", "google"]


def run_scraper_with_progress(
    max_results: int = 100,
    time_range: str = DEFAULT_TIME_RANGE,
    on_progress=None,
    techs: list[str] = None,
    engines: list[str] = None,
    custom_queries: Optional[list[str]] = None,
    enrich: bool = True,
    enrich_limit: int = 40,
    post_enrich_limit: int = 30,
    locations: Optional[list[str]] = None,
    contract_only: bool = False,
    exclude_sponsorship: bool = True,
) -> list[Opportunity]:
    """Multi-tech, multi-engine scraper with live progress callbacks.

    Args:
        techs: list of tech profile IDs (e.g. ["react_native", "python"]).
               Defaults to ["react_native"].
        engines: list of engine IDs to use (e.g. ["linkedin", "duckduckgo"]).
                 Defaults to all engines.
        enrich: fetch each LinkedIn job's detail page (description, seniority,
                applicants) and each post's full text, for better filtering.
        locations: LinkedIn job search locations, e.g. ["Worldwide", "Brazil"].
                   Searching your own region finds remote jobs that hire there.
        contract_only: keep only contractor / freelance / B2B work.
        exclude_sponsorship: drop jobs that need local work authorization,
                   citizenship, clearance or visa sponsorship.
    """
    from tech_profiles import TECH_PROFILES

    cb = on_progress or (lambda e: None)

    if time_range not in TIME_RANGES:
        time_range = DEFAULT_TIME_RANGE
    max_age_days = TIME_RANGES[time_range][1]

    # Resolve tech profiles
    selected_techs = techs or ["react_native"]
    selected_engines = engines or ALL_ENGINES

    # Merge queries and keywords from all selected profiles
    all_job_queries = []
    all_post_queries = []
    all_filter_keywords = []
    all_scoring_signals = {}
    tech_labels = []

    for tech_id in selected_techs:
        profile = TECH_PROFILES.get(tech_id)
        if not profile:
            continue
        tech_labels.append(profile["label"])
        all_job_queries.extend(profile["job_queries"])
        all_post_queries.extend(profile["post_queries"])
        all_filter_keywords.extend(profile["filter_keywords"])
        all_scoring_signals.update(profile["scoring_signals"])

    if custom_queries:
        all_job_queries = list(custom_queries)

    # Deduplicate queries while preserving order. Job and post queries go to
    # different engines, so the same text may appear in both lists.
    job_queries = list(dict.fromkeys(all_job_queries))
    post_queries = list(dict.fromkeys(all_post_queries))
    search_locations = locations or ["Worldwide"]

    # Deduplicate filter keywords
    all_filter_keywords = list(dict.fromkeys(all_filter_keywords))

    # Build phases based on selected engines
    phases = []
    if "linkedin" in selected_engines:
        for loc in search_locations:
            phases.append((f"LinkedIn Jobs · {loc}", job_queries[:10],
                           lambda s, q, loc=loc: scrape_linkedin_jobs_page(
                               s, q, time_range=time_range, location=loc, contract_only=contract_only)))
    if "yahoo" in selected_engines:
        phases.append(("Yahoo Posts", post_queries,
                        lambda s, q: scrape_yahoo_for_linkedin_posts(s, q, time_range=time_range)))
    if "google" in selected_engines:
        phases.append(("Google Jobs", job_queries[:6],
                        lambda s, q: scrape_google_for_linkedin(s, q, "jobs", time_range=time_range)))
    if "duckduckgo" in selected_engines:
        phases.append(("DuckDuckGo Posts", post_queries,
                        lambda s, q: scrape_duckduckgo_for_linkedin_posts(s, q, time_range=time_range)))
    if "bing" in selected_engines:
        phases.append(("Bing Posts", post_queries[:5],
                        lambda s, q: scrape_bing_for_linkedin_posts(s, q, time_range=time_range)))
    if "google" in selected_engines:
        phases.append(("Google Posts", post_queries[:3],
                        lambda s, q: scrape_linkedin_posts_via_google(s, q, time_range=time_range)))

    total_phases = len(phases)
    all_results: list[Opportunity] = []

    session = make_session()
    reset_blocked_hosts()

    tech_str = ", ".join(tech_labels) or "Unknown"
    engine_str = ", ".join(selected_engines)
    focus_str = " | Contract only" if contract_only else ""
    focus_str += " | No sponsorship needed" if exclude_sponsorship else ""
    cb({"step": "Scraping", "total_phases": total_phases,
        "log_line": f"Starting scraper: {tech_str} | Engines: {engine_str} | Range: {time_range}{focus_str}"})

    for phase_idx, (phase_name, queries, scrape_fn) in enumerate(phases, 1):
        cb({
            "phase": phase_name,
            "phase_num": phase_idx,
            "total_queries": len(queries),
            "query_num": 0,
            "phase_found": 0,
            "log_line": f"--- Phase {phase_idx}/{total_phases}: {phase_name} ({len(queries)} queries) ---",
        })

        phase_found = 0
        for q_idx, q in enumerate(queries, 1):
            display_q = q.replace('"', '')
            cb({
                "query": display_q,
                "query_num": q_idx,
                "log_line": f"  [{q_idx}/{len(queries)}] {display_q}",
            })

            results = scrape_fn(session, q)
            all_results.extend(results)
            phase_found += len(results)

            cb({
                "found_so_far": len(all_results),
                "phase_found": phase_found,
                "log_line": f"    Found {len(results)} results (total: {len(all_results)})",
            })

        cb({"log_line": f"  Phase complete: {phase_found} results"})

    # Filtering pipeline
    cb({"step": "Filtering", "phase": "Filtering", "phase_num": total_phases + 1,
        "total_phases": total_phases + 1,
        "log_line": f"Raw total: {len(all_results)} — running filters..."})

    pipeline = all_results

    pipeline = deduplicate(pipeline)
    cb({"log_line": f"  After dedup: {len(pipeline)}"})

    pipeline = filter_india(pipeline)
    cb({"log_line": f"  After India filter: {len(pipeline)}"})

    pipeline = filter_non_remote(pipeline, defer_posts=enrich)
    cb({"log_line": f"  After remote filter: {len(pipeline)}"})

    pipeline = filter_stale(pipeline, max_age_days=max_age_days, post_max_age_days=POST_MIN_WINDOW_DAYS)
    cb({"log_line": f"  After stale filter ({max_age_days}d, posts {max(max_age_days, POST_MIN_WINDOW_DAYS)}d): {len(pipeline)}"})

    if exclude_sponsorship:
        pipeline = filter_sponsorship(pipeline)
        cb({"log_line": f"  After sponsorship filter (cards): {len(pipeline)}"})

    # Enrich only the survivors of the cheap filters, best first:
    # one request per job/post, so spend them on the likely matches.
    if enrich:
        pipeline = rank_opportunities(pipeline, extra_signals=all_scoring_signals)
        n_jobs = min(enrich_limit, sum(1 for o in pipeline if o.job_id))
        if n_jobs:
            cb({"step": "Enriching", "phase": "Fetching job details",
                "log_line": f"Fetching details for {n_jobs} LinkedIn jobs..."})
            done = enrich_linkedin_jobs(session, pipeline, enrich_limit)
            cb({"log_line": f"  Enriched {done}/{n_jobs} jobs"})
        n_posts = min(post_enrich_limit, sum(1 for o in pipeline if o.result_type == ResultType.POST))
        if n_posts:
            cb({"step": "Enriching", "phase": "Reading posts",
                "log_line": f"Reading full text of {n_posts} posts..."})
            done = enrich_linkedin_posts(session, pipeline, post_enrich_limit)
            cb({"log_line": f"  Read {done}/{n_posts} posts"})

        pipeline = filter_posts_not_remote(pipeline)
        pipeline = filter_india_posts(pipeline)
        cb({"log_line": f"  After post checks (full text): {len(pipeline)}"})

    pipeline = filter_tech_relevance(pipeline, all_filter_keywords)
    cb({"log_line": f"  After tech filter: {len(pipeline)}"})

    if exclude_sponsorship:
        pipeline = filter_sponsorship(pipeline)
        cb({"log_line": f"  After sponsorship filter (full text): {len(pipeline)}"})

    if contract_only:
        pipeline = filter_contract(pipeline)
        cb({"log_line": f"  After contract filter: {len(pipeline)}"})

    cb({"step": "Ranking", "phase": "Ranking & saving",
        "log_line": f"Ranking {len(pipeline)} results..."})

    pipeline = rank_opportunities(pipeline, extra_signals=all_scoring_signals)

    if max_results and len(pipeline) > max_results:
        pipeline = pipeline[:max_results]

    cb({"found_so_far": len(pipeline),
        "log_line": f"Final results: {len(pipeline)}"})

    return pipeline


# ─────────────────────────────────────────────
# Output Formatters
# ─────────────────────────────────────────────


def to_json(opportunities: list[Opportunity]) -> str:
    """Serialize to JSON."""
    return json.dumps(
        {
            "metadata": {
                "generated_at": _utcnow().isoformat(),
                "total_results": len(opportunities),
                "tool": "React Native LinkedIn Scraper",
            },
            "results": [asdict(o) for o in opportunities],
        },
        indent=2,
        ensure_ascii=False,
    )


def to_table(opportunities: list[Opportunity]) -> str:
    """Plain text table output."""
    if not opportunities:
        return "No results found."

    lines = [
        f"{'#':>3}  {'Score':>5}  {'Type':<4}  {'Title':<50}  {'Company/Author':<30}  {'Location':<25}  URL",
        "─" * 160,
    ]
    for i, o in enumerate(opportunities, 1):
        lines.append(
            f"{i:>3}  {o.relevance_score:>5.1f}  {ResultType(o.result_type).value:<4}  "
            f"{o.title[:50]:<50}  {o.company_or_author[:30]:<30}  "
            f"{o.location[:25]:<25}  {o.url}"
        )
    return "\n".join(lines)


def to_html(opportunities: list[Opportunity]) -> str:
    """Generate a styled HTML report."""
    rows = ""
    for i, o in enumerate(opportunities, 1):
        badge_class = "job-badge" if o.result_type == "job" else "post-badge"
        rows += f"""
        <tr>
            <td>{i}</td>
            <td><span class="score">{o.relevance_score:.0f}</span></td>
            <td><span class="{badge_class}">{ResultType(o.result_type).value.upper()}</span></td>
            <td>
                <a href="{o.url}" target="_blank" rel="noopener">{o.title[:80]}</a>
                <div class="snippet">{o.snippet[:150]}</div>
            </td>
            <td>{o.company_or_author}</td>
            <td>{o.location}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>React Native Opportunities</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: 'SF Pro Text', -apple-system, BlinkMacSystemFont, sans-serif;
        background: #0a0a0f;
        color: #e0e0e6;
        padding: 2rem;
    }}
    h1 {{
        font-size: 1.8rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
        background: linear-gradient(135deg, #61dafb, #a78bfa);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }}
    .meta {{ color: #888; font-size: 0.85rem; margin-bottom: 2rem; }}
    table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.9rem;
    }}
    th {{
        text-align: left;
        padding: 0.75rem;
        background: #15151f;
        color: #aaa;
        font-weight: 500;
        text-transform: uppercase;
        font-size: 0.75rem;
        letter-spacing: 0.05em;
        border-bottom: 1px solid #222;
    }}
    td {{
        padding: 0.75rem;
        border-bottom: 1px solid #1a1a25;
        vertical-align: top;
    }}
    tr:hover {{ background: #12121c; }}
    a {{ color: #61dafb; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .snippet {{ color: #777; font-size: 0.8rem; margin-top: 0.25rem; }}
    .score {{
        display: inline-block;
        background: #1a1a2e;
        color: #61dafb;
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        font-weight: 600;
        font-size: 0.8rem;
    }}
    .job-badge {{
        background: #1a3a1a;
        color: #4ade80;
        padding: 0.15rem 0.5rem;
        border-radius: 3px;
        font-size: 0.7rem;
        font-weight: 600;
    }}
    .post-badge {{
        background: #1a1a3a;
        color: #818cf8;
        padding: 0.15rem 0.5rem;
        border-radius: 3px;
        font-size: 0.7rem;
        font-weight: 600;
    }}
</style>
</head>
<body>
    <h1>React Native Opportunities</h1>
    <p class="meta">Generated {_utcnow().strftime('%Y-%m-%d %H:%M UTC')} · {len(opportunities)} results · India excluded</p>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Score</th>
                <th>Type</th>
                <th>Title / Snippet</th>
                <th>Company</th>
                <th>Location</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
</body>
</html>"""


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Scrape LinkedIn for React Native opportunities (excluding India)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "table", "html"],
        default="table",
        help="Output format (default: table)",
    )
    parser.add_argument(
        "--max-results", "-n",
        type=int,
        default=100,
        help="Maximum results to return (default: 100)",
    )
    parser.add_argument(
        "--time-range", "-t",
        choices=list(TIME_RANGES),
        default=DEFAULT_TIME_RANGE,
        help=f"How far back to search (default: {DEFAULT_TIME_RANGE})",
    )
    parser.add_argument(
        "--techs",
        default="react_native",
        help="Comma-separated tech profile IDs (default: react_native)",
    )
    parser.add_argument(
        "--engines",
        default=",".join(ALL_ENGINES),
        help=f"Comma-separated engines (default: {','.join(ALL_ENGINES)})",
    )
    parser.add_argument(
        "--locations",
        default="Worldwide,Latin America,Brazil",
        help="Comma-separated LinkedIn search locations (default: Worldwide,Latin America,Brazil)",
    )
    parser.add_argument(
        "--contract-only",
        action="store_true",
        help="Keep only contractor / freelance / B2B work",
    )
    parser.add_argument(
        "--allow-sponsorship",
        action="store_true",
        help="Keep jobs that need local work authorization or visa sponsorship",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip fetching job detail pages (faster, less accurate)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    results = run_scraper(
        max_results=args.max_results,
        verbose=args.verbose,
        time_range=args.time_range,
        techs=[t.strip() for t in args.techs.split(",") if t.strip()],
        engines=[e.strip() for e in args.engines.split(",") if e.strip()],
        enrich=not args.no_enrich,
        locations=[x.strip() for x in args.locations.split(",") if x.strip()],
        contract_only=args.contract_only,
        exclude_sponsorship=not args.allow_sponsorship,
    )

    # Format output
    if args.format == "json":
        output = to_json(results)
    elif args.format == "html":
        output = to_html(results)
    else:
        output = to_table(results)

    # Write
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        log.info("Results written to %s", args.output)
    else:
        print(output)


if __name__ == "__main__":
    main()
