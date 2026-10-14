#!/usr/bin/env python3
"""
Search LinkedIn POSTS with LinkedIn's own search (needs a logged-in account).

Search engines only index a few, mostly old, LinkedIn posts. LinkedIn's own
content search shows every post from the last 24 hours, but only to a
logged-in user. So this drives a dedicated Chrome profile (separate from your
normal Chrome and from the apply bot) where you log in once.

Runs on your Mac only (not on GitHub: a cloud IP with your session would get
the account flagged).

Usage:
    python linkedin_posts.py --login           # open Chrome, log in once
    python linkedin_posts.py "react native hiring"   # test one search

Config (environment variables or .env):
    LINKEDIN_PROFILE_DIR   Chrome profile dir   (default: ~/.job-hunter/linkedin-profile)
    LINKEDIN_HEADLESS      false = show Chrome  (default: true)
    LINKEDIN_CHROME_BIN    Chrome binary        (default: /Applications/Google Chrome.app/...)

Gentle on the account: one Chrome, a few searches per run, human-like pauses,
read-only actions (the only click is "Copy link to post" in each post's menu,
because the new LinkedIn page does not put the post link in the HTML).
"""

import logging
import os
import random
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger("linkedin_posts")

SEARCH_URL = "https://www.linkedin.com/search/results/content/"
DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

PAUSE_BETWEEN_SEARCHES = (8.0, 15.0)
PAUSE_BETWEEN_POSTS = (0.8, 2.0)
MAX_SCROLLS_PER_SEARCH = 12  # the list keeps only ~6 posts in the page at a time

# The page has no post links; capture what "Copy link to post" writes.
_CLIPBOARD_HOOK = """
window.__copied = [];
const _hook = () => {
  if (!navigator.clipboard) return;
  navigator.clipboard.writeText = (t) => { window.__copied.push(t); return Promise.resolve(); };
};
_hook();
document.addEventListener('DOMContentLoaded', _hook);
"""

# Post cards: role=listitem with a post control menu. Text sits in
# data-testid="expandable-text-box" (full text, the "more" button only unhides it).
_READ_CARDS_JS = """
() => [...document.querySelectorAll('[role="listitem"]')]
  .filter(c => c.querySelector('button[aria-label*="control menu" i], button[aria-label*="menu de controle" i], button[aria-label*="menú de control" i]'))
  .map((c, i) => {
    c.setAttribute('data-jh-idx', String(i));
    const box = c.querySelector('[data-testid="expandable-text-box"]');
    const authorLink = c.querySelector('a[href*="/in/"], a[href*="/company/"]');
    const nameLink = [...c.querySelectorAll('a[href*="/in/"], a[href*="/company/"]')]
      .find(a => (a.innerText || '').trim());
    const lines = (c.innerText || '').split('\\n').map(s => s.trim()).filter(s => s && s !== 'Feed post');
    return {
      idx: i,
      text: (box ? box.textContent : c.innerText || '').trim(),
      author: (nameLink ? nameLink.innerText.trim().split('\\n')[0] : '') || lines[0] || '',
      author_url: authorLink ? authorLink.href.split('?')[0] : '',
    };
  })
"""

_COPY_LINK_JS = """
async (idx) => {
  const card = document.querySelector(`[data-jh-idx="${idx}"]`);
  if (!card) return '';
  const btn = card.querySelector('button[aria-label*="control menu" i], button[aria-label*="menu de controle" i], button[aria-label*="menú de control" i]');
  if (!btn) return '';
  window.__copied = [];
  btn.click();
  for (let i = 0; i < 20; i++) {
    await new Promise(r => setTimeout(r, 100));
    const item = [...document.querySelectorAll('[role="menuitem"]')]
      .find(e => /copy link|copiar link|copiar enlace/i.test(e.textContent || ''));
    if (item) { item.click(); break; }
  }
  for (let i = 0; i < 20 && !window.__copied.length; i++) await new Promise(r => setTimeout(r, 100));
  document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  document.body.click();
  return window.__copied[0] || '';
}
"""


# Scroll the LAST post into view (the list scrolls inside its own container,
# so a window scroll does nothing), then press "Show more results" if shown.
_LOAD_MORE_JS = """
() => {
  const cards = document.querySelectorAll('[role="listitem"]');
  if (cards.length) cards[cards.length - 1].scrollIntoView({block: 'end'});
  const more = [...document.querySelectorAll('button')]
    .find(b => /^(show more results|load more|ver mais resultados|mostrar más resultados)$/i.test((b.innerText || '').trim()));
  if (more) { more.click(); return true; }
  return false;
}
"""


class NotLoggedIn(RuntimeError):
    pass


class ProfileInUse(RuntimeError):
    pass


def _env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def profile_dir() -> Path:
    return Path(_env("LINKEDIN_PROFILE_DIR", str(Path.home() / ".job-hunter" / "linkedin-profile"))).expanduser()


def chrome_bin() -> str:
    return _env("LINKEDIN_CHROME_BIN", DEFAULT_CHROME)


def is_available() -> tuple[bool, str]:
    """(ok, reason). False on GitHub/Docker: no Playwright, Chrome or login."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False, "playwright not installed (pip install -r requirements-posts.txt)"
    if not Path(chrome_bin()).exists():
        return False, f"Chrome not found at {chrome_bin()}"
    if not (profile_dir() / "Default").exists():
        return False, "not logged in yet (run: python linkedin_posts.py --login)"
    return True, ""


def build_search_url(query: str, date_posted: str = "past-week") -> str:
    params = {
        "keywords": query,
        "datePosted": f'"{date_posted}"',
        "sortBy": '"date_posted"',
    }
    return SEARCH_URL + "?" + urllib.parse.urlencode(params)


def resolve_short_link(url: str, session: Optional[requests.Session] = None) -> str:
    """lnkd.in/p/xyz → https://www.linkedin.com/posts/...-activity-123.../
    The full URL carries the post ID, which encodes the post date."""
    if "lnkd.in/" not in url:
        return url.split("?")[0]
    s = session or requests
    try:
        resp = s.head(url, allow_redirects=False, timeout=10,
                      headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        loc = resp.headers.get("location", "")
        if "linkedin.com/" in loc:
            return loc.split("?")[0]
    except requests.RequestException as e:
        log.debug("Could not resolve %s: %s", url, e)
    return url


def _pause(bounds: tuple[float, float]):
    time.sleep(random.uniform(*bounds))


class LinkedInPostSearch:
    """One Chrome for a whole run. Use as a context manager."""

    def __init__(self, headless: Optional[bool] = None):
        if headless is None:
            headless = _env("LINKEDIN_HEADLESS", "true").lower() not in ("0", "false", "no", "off")
        self.headless = headless
        self._pw = None
        self._ctx = None
        self.page = None
        self.http = requests.Session()

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        profile_dir().mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(
                str(profile_dir()),
                executable_path=chrome_bin(),
                headless=self.headless,
                viewport={"width": 1280, "height": 900},
                args=["--no-first-run", "--no-default-browser-check"],
            )
        except Exception as e:
            self._pw.stop()
            if "ProcessSingleton" in str(e) or "SingletonLock" in str(e):
                raise ProfileInUse(
                    "The LinkedIn Chrome is already open (the --login window, or another run). "
                    "Close that Chrome window and try again.") from None
            raise
        self._ctx.add_init_script(_CLIPBOARD_HOOK)
        self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self

    def __exit__(self, *exc):
        try:
            if self._ctx:
                self._ctx.close()
        finally:
            if self._pw:
                self._pw.stop()

    def _check_login(self):
        url = self.page.url
        if any(p in url for p in ("/login", "/checkpoint", "/authwall", "/uas/", "/signup")):
            raise NotLoggedIn(f"LinkedIn asks to log in ({url.split('?')[0]}). Run: python linkedin_posts.py --login")

    def search(self, query: str, date_posted: str = "past-week", max_posts: int = 25) -> list[dict]:
        """Posts for one query: [{url, text, author, author_url}], newest first."""
        page = self.page
        page.goto(build_search_url(query, date_posted), wait_until="domcontentloaded", timeout=45000)
        self._check_login()
        try:
            page.wait_for_selector('[role="listitem"]', timeout=20000)
        except Exception:
            self._check_login()
            log.info("No posts for %r", query)
            return []

        # The list is virtual: posts leave the page as you scroll. So read
        # the posts on screen, scroll, and repeat until nothing new shows up.
        posts = []
        seen = set()
        idle_rounds = 0
        for _ in range(MAX_SCROLLS_PER_SEARCH):
            new = 0
            for card in page.evaluate(_READ_CARDS_JS):
                key = card["text"][:150]
                if len(card["text"]) < 40 or key in seen:
                    continue
                seen.add(key)
                new += 1
                link = page.evaluate(_COPY_LINK_JS, card["idx"])
                if not link:
                    log.debug("No link for post by %s", card["author"])
                    continue
                card["url"] = resolve_short_link(link, self.http)
                posts.append(card)
                _pause(PAUSE_BETWEEN_POSTS)
            if len(posts) >= max_posts:
                break
            idle_rounds = 0 if new else idle_rounds + 1
            if idle_rounds >= 2:
                break
            page.evaluate(_LOAD_MORE_JS)
            page.mouse.wheel(0, random.randint(600, 1200))
            _pause((2.0, 3.5))
        log.info("LinkedIn posts [%s]: %d posts", query, len(posts))
        return posts[:max_posts]

    def pause_between_searches(self):
        _pause(PAUSE_BETWEEN_SEARCHES)


def login():
    """Open the dedicated Chrome on the LinkedIn login page and wait.
    Logged in = the li_at session cookie exists (LinkedIn may land on any
    page after login, not always /feed)."""
    print(f"Opening Chrome (profile: {profile_dir()}). Log in to LinkedIn there.")
    with LinkedInPostSearch(headless=False) as s:
        s.page.goto("https://www.linkedin.com/login")
        for _ in range(600):  # 10 minutes
            time.sleep(1)
            try:
                cookies = s._ctx.cookies("https://www.linkedin.com")
            except Exception:  # window closed by hand
                print("Chrome was closed. If you logged in, you are done.")
                return
            if any(c["name"] == "li_at" for c in cookies):
                print("Logged in. Chrome closes in 3 seconds.")
                time.sleep(3)
                return
        print("Timed out waiting for login. Run --login again.")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    args = sys.argv[1:]
    if args[:1] == ["--login"]:
        login()
        return
    query = " ".join(args) or '"react native" hiring'
    with LinkedInPostSearch() as s:
        for p in s.search(query):
            print(f"- {p['author']} | {p['url']}\n  {p['text'][:200]!r}")


if __name__ == "__main__":
    main()
