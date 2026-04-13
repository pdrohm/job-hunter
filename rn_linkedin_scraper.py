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
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import requests
from bs4 import BeautifulSoup

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
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @property
    def uid(self) -> str:
        return hashlib.md5(self.url.encode()).hexdigest()[:12]


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


def has_preferred_region(text: str) -> bool:
    """Check if text mentions a preferred region."""
    if not text:
        return False
    text_lower = text.lower()
    return any(region in text_lower for region in PREFERRED_REGIONS)


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


def compute_relevance(title: str, snippet: str, result_type: str, extra_signals: dict = None) -> float:
    """Score 0-100 based on hiring intent and tech relevance."""
    combined = f"{title} {snippet}".lower()
    score = 0.0

    for signal, weight in HIRING_SIGNALS.items():
        if signal in combined:
            score += weight

    # Add tech-specific scoring signals
    if extra_signals:
        for signal, weight in extra_signals.items():
            if signal.lower() in combined:
                score += weight

    # Boost actual job listings
    if result_type == ResultType.JOB:
        score += 15

    # Boost if location is in preferred region
    if has_preferred_region(combined):
        score += 5

    # Normalize to 0-100
    return min(round(score, 1), 100.0)


# ─────────────────────────────────────────────
# HTTP Client
# ─────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}

# Rate limiting
_last_request_time = 0.0
MIN_REQUEST_INTERVAL = 2.0  # seconds between requests


def throttled_get(url: str, session: requests.Session, timeout: int = 15) -> Optional[requests.Response]:
    """GET with rate limiting and error handling."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)

    try:
        resp = session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        _last_request_time = time.time()
        if resp.status_code == 200:
            return resp
        elif resp.status_code == 429:
            log.warning("Rate limited on %s – backing off 10s", url)
            time.sleep(10)
            return None
        else:
            log.debug("HTTP %d for %s", resp.status_code, url)
            return None
    except requests.RequestException as e:
        log.debug("Request failed for %s: %s", url, e)
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


def build_linkedin_job_search_url(query: str, start: int = 0, time_range: str = DEFAULT_TIME_RANGE) -> str:
    """Build LinkedIn public job search URL (no auth required)."""
    tpr_seconds = TIME_RANGES.get(time_range, TIME_RANGES[DEFAULT_TIME_RANGE])[0]
    params = {
        "keywords": query,
        "location": "",  # worldwide
        "f_TPR": f"r{tpr_seconds}",
        "f_WT": "2",  # remote only
        "position": 1,
        "pageNum": 0,
        "start": start,
    }
    return "https://www.linkedin.com/jobs/search/?" + urllib.parse.urlencode(params)


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


def scrape_linkedin_jobs_page(session: requests.Session, query: str, time_range: str = DEFAULT_TIME_RANGE) -> list[Opportunity]:
    """Scrape LinkedIn's public job search results page."""
    results = []
    url = build_linkedin_job_search_url(query, time_range=time_range)
    log.info("Scraping LinkedIn jobs [%s]: %s", time_range, query)

    resp = throttled_get(url, session)
    if not resp:
        return results

    soup = BeautifulSoup(resp.text, "html.parser")

    # LinkedIn public job cards
    job_cards = soup.select(
        "div.base-card, "
        "li.jobs-search__result-card, "
        "div.job-search-card, "
        "li.result-card, "
        "div.base-search-card"
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
                )
            )
        except Exception as e:
            log.debug("Error parsing job card: %s", e)
            continue

    log.info("  Found %d jobs for '%s'", len(results), query)
    return results


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

            results.append(
                Opportunity(
                    title=title[:200],
                    result_type=rtype,
                    company_or_author=company[:100],
                    location=location,
                    url=clean_url,
                    snippet=snippet[:300] if snippet else title,
                    source_query=query,
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


# ─────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────


def deduplicate(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Remove duplicates by URL."""
    seen = set()
    unique = []
    for opp in opportunities:
        # Normalize URL for dedup
        norm_url = opp.url.rstrip("/").lower()
        if norm_url not in seen:
            seen.add(norm_url)
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


def filter_non_remote(opportunities: list[Opportunity]) -> list[Opportunity]:
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

        # LinkedIn direct job results already filtered by f_WT=2 — trust them
        if opp.source == "linkedin_jobs":
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

    For LinkedIn direct results, also checks source_query since
    scraped HTML often truncates titles."""
    patterns = _build_tech_patterns(tech_keywords)
    filtered = []
    excluded_count = 0
    for opp in opportunities:
        combined_text = " ".join([opp.title, opp.company_or_author, opp.snippet])
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

def _extract_linkedin_post_age_days(url: str) -> Optional[float]:
    """Extract post age in days from LinkedIn post URL activity/ugcPost ID.
    Returns None if no timestamp can be extracted."""
    for pattern in (_linkedin_activity_re, _linkedin_ugc_re):
        m = pattern.search(url)
        if m:
            try:
                activity_id = int(m.group(1))
                # LinkedIn uses Twitter snowflake-style IDs: timestamp = id >> 22
                timestamp_ms = activity_id >> 22
                post_date = datetime.utcfromtimestamp(timestamp_ms / 1000.0)
                age = (datetime.utcnow() - post_date).total_seconds() / 86400
                return age
            except (ValueError, OSError):
                return None
    return None


def filter_stale(opportunities: list[Opportunity], max_age_days: int = 30) -> list[Opportunity]:
    """Remove posts older than max_age_days.
    Jobs from LinkedIn job search don't have embedded timestamps
    and are already time-filtered by f_TPR param, so they pass through."""
    filtered = []
    excluded_count = 0
    for opp in opportunities:
        age = _extract_linkedin_post_age_days(opp.url)
        if age is not None and age > max_age_days:
            excluded_count += 1
            log.debug("Excluded (%.0f days old): %s", age, opp.title[:60])
            continue
        filtered.append(opp)

    if excluded_count:
        log.info("Filtered out %d stale results (>%d days old)", excluded_count, max_age_days)
    return filtered


def rank_opportunities(opportunities: list[Opportunity], extra_signals: dict = None) -> list[Opportunity]:
    """Score and sort by relevance."""
    for opp in opportunities:
        opp.relevance_score = compute_relevance(opp.title, opp.snippet, opp.result_type, extra_signals)
    return sorted(opportunities, key=lambda o: o.relevance_score, reverse=True)


def run_scraper(
    max_results: int = 100,
    queries: Optional[list[str]] = None,
    verbose: bool = False,
    time_range: str = DEFAULT_TIME_RANGE,
) -> list[Opportunity]:
    """Main scraper entry point.

    Args:
        time_range: One of "24h", "3d", "1w", "2w", "1m", "3m".
    """
    if verbose:
        log.setLevel(logging.DEBUG)

    if time_range not in TIME_RANGES:
        time_range = DEFAULT_TIME_RANGE

    max_age_days = TIME_RANGES[time_range][1]

    search_queries = queries or SEARCH_QUERIES
    all_results: list[Opportunity] = []

    session = requests.Session()
    session.headers.update(HEADERS)

    log.info("Starting React Native opportunity scraper (time_range=%s, max_age=%dd)", time_range, max_age_days)
    log.info("Searching with %d queries", len(search_queries))

    # Phase 1: LinkedIn direct job search
    log.info("─── Phase 1: LinkedIn Direct Job Search ───")
    for q in search_queries[:8]:  # Limit to avoid rate limits
        results = scrape_linkedin_jobs_page(session, q, time_range=time_range)
        all_results.extend(results)
        time.sleep(MIN_REQUEST_INTERVAL)

    # Phase 2: Google → LinkedIn jobs
    log.info("─── Phase 2: Google → LinkedIn Jobs ───")
    for q in search_queries[:6]:
        results = scrape_google_for_linkedin(session, q, "jobs", time_range=time_range)
        all_results.extend(results)
        time.sleep(MIN_REQUEST_INTERVAL)

    # Phase 3: DuckDuckGo → LinkedIn posts (primary — DDG doesn't block scrapers)
    log.info("─── Phase 3: DuckDuckGo → LinkedIn Posts ───")
    post_queries = [
        '"react native" hiring remote',
        '"react native" we are hiring remote',
        '"react native" developer remote',
        '"react native" looking for developer remote',
        '"react native" join our team remote',
        '"react native" open role remote',
        '"react native" remote opportunity',
        'hiring "react native" engineer remote',
        '"expo" "react native" mobile remote',
    ]
    for q in post_queries:
        results = scrape_duckduckgo_for_linkedin_posts(session, q, time_range=time_range)
        all_results.extend(results)
        time.sleep(MIN_REQUEST_INTERVAL)

    # Phase 4: Bing → LinkedIn posts (fallback)
    log.info("─── Phase 4: Bing → LinkedIn Posts ───")
    for q in post_queries[:5]:
        results = scrape_bing_for_linkedin_posts(session, q, time_range=time_range)
        all_results.extend(results)
        time.sleep(MIN_REQUEST_INTERVAL)

    # Phase 5: Google → LinkedIn posts (often blocked, but try)
    log.info("─── Phase 5: Google → LinkedIn Posts ───")
    for q in post_queries[:3]:
        results = scrape_linkedin_posts_via_google(session, q, time_range=time_range)
        all_results.extend(results)
        time.sleep(MIN_REQUEST_INTERVAL)

    log.info("Total raw results: %d", len(all_results))

    # Pipeline: dedup → filter → rank → trim
    pipeline = all_results
    pipeline = deduplicate(pipeline)
    log.info("After dedup: %d", len(pipeline))

    pipeline = filter_india(pipeline)
    log.info("After India filter: %d", len(pipeline))

    pipeline = filter_non_remote(pipeline)
    log.info("After remote filter: %d", len(pipeline))

    pipeline = filter_non_mobile(pipeline)
    log.info("After mobile filter: %d", len(pipeline))

    pipeline = filter_stale(pipeline, max_age_days=max_age_days)
    log.info("After stale filter: %d", len(pipeline))

    pipeline = rank_opportunities(pipeline)

    if max_results and len(pipeline) > max_results:
        pipeline = pipeline[:max_results]

    log.info("Final results: %d", len(pipeline))
    return pipeline


ALL_ENGINES = ["linkedin", "duckduckgo", "bing", "google"]


def run_scraper_with_progress(
    max_results: int = 100,
    time_range: str = DEFAULT_TIME_RANGE,
    on_progress=None,
    techs: list[str] = None,
    engines: list[str] = None,
) -> list[Opportunity]:
    """Multi-tech, multi-engine scraper with live progress callbacks.

    Args:
        techs: list of tech profile IDs (e.g. ["react_native", "python"]).
               Defaults to ["react_native"].
        engines: list of engine IDs to use (e.g. ["linkedin", "duckduckgo"]).
                 Defaults to all engines.
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

    # Deduplicate queries while preserving order
    seen_q = set()
    job_queries = []
    for q in all_job_queries:
        if q not in seen_q:
            seen_q.add(q)
            job_queries.append(q)
    post_queries = []
    for q in all_post_queries:
        if q not in seen_q:
            seen_q.add(q)
            post_queries.append(q)

    # Deduplicate filter keywords
    all_filter_keywords = list(dict.fromkeys(all_filter_keywords))

    # Build phases based on selected engines
    phases = []
    if "linkedin" in selected_engines:
        phases.append(("LinkedIn Jobs", job_queries[:10],
                        lambda s, q: scrape_linkedin_jobs_page(s, q, time_range=time_range)))
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

    session = requests.Session()
    session.headers.update(HEADERS)

    tech_str = ", ".join(tech_labels) or "Unknown"
    engine_str = ", ".join(selected_engines)
    cb({"step": "Scraping", "total_phases": total_phases,
        "log_line": f"Starting scraper: {tech_str} | Engines: {engine_str} | Range: {time_range}"})

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

            time.sleep(MIN_REQUEST_INTERVAL)

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

    pipeline = filter_non_remote(pipeline)
    cb({"log_line": f"  After remote filter: {len(pipeline)}"})

    pipeline = filter_tech_relevance(pipeline, all_filter_keywords)
    cb({"log_line": f"  After tech filter: {len(pipeline)}"})

    pipeline = filter_stale(pipeline, max_age_days=max_age_days)
    cb({"log_line": f"  After stale filter ({max_age_days}d): {len(pipeline)}"})

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
                "generated_at": datetime.utcnow().isoformat(),
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
            f"{i:>3}  {o.relevance_score:>5.1f}  {o.result_type:<4}  "
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
            <td><span class="{badge_class}">{o.result_type.upper()}</span></td>
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
    <p class="meta">Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} · {len(opportunities)} results · India excluded</p>
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
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    results = run_scraper(
        max_results=args.max_results,
        verbose=args.verbose,
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
