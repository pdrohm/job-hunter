#!/usr/bin/env python3
"""
Read WhatsApp Web chats in a dedicated Chrome profile (read-only).

The Chrome profile is separate from your normal Chrome: link it once with
`python -m whatsapp_summary.summary --login` (scan the QR code with your phone,
WhatsApp → Linked devices). The bot never types or sends anything.

Side effects you will see on the phone: a chat the bot opens is marked as read,
and a voice message it reads is marked as played (it plays muted to get the audio).

Config (environment variables or .env):
    WA_PROFILE_DIR   Chrome profile dir   (default: ~/.job-hunter/whatsapp-profile)
    WA_HEADLESS      false = show Chrome  (default: true)
    WA_CHROME_BIN    Chrome binary        (default: /Applications/Google Chrome.app/...)
    WA_DATE_ORDER    dmy or mdy           (default: dmy; the date order of your WhatsApp language)
"""

import base64
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("whatsapp_web")

URL = "https://web.whatsapp.com/"
DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
LOAD_TIMEOUT_S = 90
MAX_HISTORY_LOADS = 80  # each loads one page of older messages
MAX_SCROLL_STEPS = 600  # half a screen each

# Plays every <audio> muted and keeps its blob URL, so the bot can read a voice
# message without sound on the Mac.
_AUDIO_HOOK = """
window.__waAudio = [];
const _play = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function () {
  this.muted = true;
  window.__waAudio.push(this.src || this.currentSrc);
  const p = _play.call(this);
  setTimeout(() => this.pause(), 300);
  return p;
};
"""

# One snapshot of the rendered message rows, in screen order. WhatsApp only
# renders the rows near the screen (and drops the far ones), so the caller
# scrolls step by step and merges overlapping snapshots (merge_rows).
# - `pre` ("[20:54, 15/10/2026] Name: ") is only on text messages; voice
#   messages get their time from `meta` and their date from the message before.
# - `out` (sent by me): the bubble is on the right half (no language-specific text).
EXTRACT_ROWS_JS = """
() => {
  const panel = document.querySelector('[data-testid="conversation-panel-messages"]');
  if (!panel) return [];
  const pr = panel.getBoundingClientRect();
  const rows = [];
  for (const r of document.querySelectorAll('#main [role="row"]')) {
    const idEl = r.querySelector('[data-id]');
    const box = r.querySelector('[data-testid="msg-container"]');
    if (!idEl || !box) continue;
    const quote = box.querySelector('[data-testid="quoted-message"]');
    const outside = (el) => !quote || !quote.contains(el);
    const author = [...box.querySelectorAll('[data-testid="author"]')].find(outside);
    // Outer text only: a @mention is a .selectable-text inside another one
    const texts = [...box.querySelectorAll('.selectable-text')]
      .filter(e => outside(e) && !e.parentElement.closest('.selectable-text'))
      .map(e => e.innerText.trim()).filter(Boolean);
    const pre = r.querySelector('[data-pre-plain-text]');
    const meta = box.querySelector('[data-testid="msg-meta"]');
    const b = box.getBoundingClientRect();
    rows.push({
      id: idEl.getAttribute('data-id'),
      pre: pre ? pre.getAttribute('data-pre-plain-text') : '',
      author: author ? author.innerText.trim() : '',
      body: texts.join('\\n'),
      quote: quote ? quote.innerText.trim() : '',
      meta: meta ? meta.innerText.trim() : '',
      out: (b.left + b.right) / 2 > (pr.left + pr.right) / 2,
      audio: !!box.querySelector('[data-testid="ptt-status"], [data-icon="ptt-status"], [data-icon="audio-play"]'),
    });
  }
  return rows;
}
"""

# Chat list rows with an unread badge (any WhatsApp language: the badge is a number,
# and the muted icon is named by its SVG title).
UNREAD_CHATS_JS = """
() => {
  const out = [];
  for (const row of document.querySelectorAll('#pane-side [role="row"], #pane-side [role="listitem"]')) {
    const title = row.querySelector('span[title]');
    if (!title) continue;
    const badge = [...row.querySelectorAll('span[aria-label]')].find(s => /^\\d+$/.test(s.innerText.trim()));
    const muted = [...row.querySelectorAll('svg title')].some(t => /notifications-off|muted/.test(t.textContent));
    if (badge) out.push({name: title.getAttribute('title'), unread: parseInt(badge.innerText.trim(), 10), muted});
  }
  return out;
}
"""


class NotLoggedIn(RuntimeError):
    pass


class ProfileInUse(RuntimeError):
    pass


def _env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def profile_dir() -> Path:
    return Path(_env("WA_PROFILE_DIR", str(Path.home() / ".job-hunter" / "whatsapp-profile"))).expanduser()


def chrome_bin() -> str:
    return _env("WA_CHROME_BIN", DEFAULT_CHROME)


@dataclass
class Message:
    id: str
    author: str
    when: Optional[datetime]
    text: str
    out: bool = False  # sent by me
    audio: bool = False
    quote: str = ""  # the message this one replies to
    transcript: str = ""

    def body(self) -> str:
        if self.audio:
            return f"🎤 {self.transcript}" if self.transcript else "🎤 (áudio sem transcrição)"
        return self.text

    def line(self) -> str:
        """One transcript line, as the summary prompt shows it."""
        stamp = self.when.strftime("%d/%m %H:%M") if self.when else "--/-- --:--"
        reply = f"(respondendo a: {' / '.join(self.quote.splitlines())[:200]}) " if self.quote else ""
        return f"[{stamp}] {self.author}: {reply}{self.body()}"


_PRE_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:\s*([AaPp])\.?\s*[Mm]\.?)?,\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\]\s*(.*?):\s*$")
_META_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})(?:\s*([AaPp])\.?\s*[Mm]\.?)?\s*$")


def parse_pre(pre: str, date_order: str = "dmy") -> tuple[Optional[datetime], str]:
    """'[20:54, 15/10/2026] Bruno: ' → (datetime, 'Bruno'). Also '[8:54 PM, 10/15/2026] Bruno: '."""
    m = _PRE_RE.match(pre.strip())
    if not m:
        return None, ""
    hour, minute, ampm, a, b, year, author = m.groups()
    hour, minute, a, b, year = int(hour), int(minute), int(a), int(b), int(year)
    if year < 100:
        year += 2000
    if ampm:
        hour = hour % 12 + (12 if ampm.lower() == "p" else 0)
    day, month = (b, a) if date_order == "mdy" else (a, b)
    try:
        return datetime(year, month, day, hour, minute), author.strip()
    except ValueError:
        return None, author.strip()


def merge_rows(acc: list[dict], snap: list[dict]) -> list[dict]:
    """Merge a screen-ordered snapshot into the rows read so far (also in
    order), by message id. New rows go next to the rows they touch on screen.
    The caller scrolls down, so a snapshot with no overlap goes last."""
    out = list(acc)
    index = {r["id"]: i for i, r in enumerate(out)}
    first = next((i for i, r in enumerate(snap) if r["id"] in index), None)
    if first is None:
        if out and snap:
            log.warning("Scroll skipped some messages (no overlap between two screens)")
        return out + snap
    at = index[snap[first]["id"]]
    out[at:at] = [r for r in snap[:first] if r["id"] not in index]
    last = at - 1
    for r in snap[first:]:
        i = next((j for j, x in enumerate(out) if x["id"] == r["id"]), None)
        if i is None:
            last += 1
            out.insert(last, r)
        else:
            out[i] = r
            last = i
    return out


def meta_time(meta: str) -> Optional[tuple[int, int]]:
    """'Editada08:55' → (8, 55); '9:13 PM' → (21, 13)."""
    m = _META_TIME_RE.search(meta or "")
    if not m:
        return None
    hour, minute = int(m[1]), int(m[2])
    if m[3]:
        hour = hour % 12 + (12 if m[3].lower() == "p" else 0)
    return hour, minute


def _at(day, hm: tuple[int, int]) -> datetime:
    return datetime(day.year, day.month, day.day, *hm)


def guess_time(hm: Optional[tuple[int, int]], prev: Optional[datetime], nxt: Optional[datetime]) -> Optional[datetime]:
    """A voice message shows only HH:MM. Its date is the one of the message
    before it, or the day after when the clock went past midnight; it can't be
    later than the message after it."""
    if not hm or not (prev or nxt):
        return None
    if not prev:
        return _at(nxt.date(), hm)
    when = _at(prev.date(), hm)
    if when < prev:
        when += timedelta(days=1)
    if nxt and when > nxt:
        when = _at(nxt.date(), hm)
    return when


def build_messages(rows: list[dict], me: str = "Você", date_order: str = "dmy") -> list[Message]:
    """Turn merged row snapshots (oldest first) into messages. Rows without the
    WhatsApp header (voice messages) take the time from their meta and the date
    from the messages around them. In a group, a run of messages from one
    person shows the author only on the first one."""
    msgs: list[Message] = []
    last_author = ""
    for r in rows:
        when, author = parse_pre(r.get("pre", ""), date_order)
        if r.get("out"):
            author = me
        author = author or r.get("author", "") or last_author or "?"
        text = "" if r.get("audio") else (r.get("body", "").strip() or "[mídia]")
        msgs.append(Message(id=r["id"], author=author, when=when, text=text, out=bool(r.get("out")),
                            audio=bool(r.get("audio")), quote=r.get("quote", "").strip()))
        last_author = author
    prev = None
    for i, m in enumerate(msgs):
        if m.when is None:
            nxt = next((n.when for n in msgs[i + 1:] if n.when), None)
            m.when = guess_time(meta_time(rows[i].get("meta", "")), prev, nxt)
        prev = m.when or prev
    return msgs


def parse_since(value: str, now: Optional[datetime] = None) -> datetime:
    """'12h', '2d', '20:54' (today, or yesterday if that is in the future),
    '2026-10-15 20:54', '15/10 20:54' or 'ontem 20:54'."""
    now = now or datetime.now()
    v = value.strip().lower()
    m = re.fullmatch(r"(\d+)\s*([hd])", v)
    if m:
        n = int(m[1])
        return now - (timedelta(hours=n) if m[2] == "h" else timedelta(days=n))
    m = re.fullmatch(r"(ontem|yesterday)\s+(\d{1,2}):(\d{2})", v)
    if m:
        return (now - timedelta(days=1)).replace(hour=int(m[2]), minute=int(m[3]), second=0, microsecond=0)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", v)
    if m:
        t = now.replace(hour=int(m[1]), minute=int(m[2]), second=0, microsecond=0)
        return t if t <= now else t - timedelta(days=1)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})", v)
    if m:
        t = datetime(now.year, int(m[2]), int(m[1]), int(m[3]), int(m[4]))
        return t if t <= now else t.replace(year=now.year - 1)
    raise ValueError(f"não entendi a data: {value!r} (use 12h, 2d, 20:54, 'ontem 20:54' ou '2026-10-15 20:54')")


class WhatsAppWeb:
    """One Chrome for a whole run. Use as a context manager."""

    def __init__(self, headless: Optional[bool] = None):
        if headless is None:
            headless = _env("WA_HEADLESS", "true").lower() not in ("0", "false", "no", "off")
        self.headless = headless
        self.date_order = _env("WA_DATE_ORDER", "dmy")
        self._pw = None
        self._ctx = None
        self.page = None

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
                args=["--no-first-run", "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required"],
            )
        except Exception as e:
            self._pw.stop()
            if "ProcessSingleton" in str(e) or "SingletonLock" in str(e):
                raise ProfileInUse("The WhatsApp Chrome is already open (the --login window, or another run). "
                                   "Close that Chrome window and try again.") from None
            raise
        self._ctx.add_init_script(_AUDIO_HOOK)
        self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self

    def __exit__(self, *exc):
        try:
            self._ctx.close()
        finally:
            self._pw.stop()

    # ── session ──────────────────────────────

    def open(self, timeout_s: int = LOAD_TIMEOUT_S) -> bool:
        """Load WhatsApp Web. True when the chat list shows (logged in),
        False when it shows the QR code."""
        self.page.goto(URL)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.page.locator("#pane-side").count():
                return True
            if self.page.locator("canvas[aria-label], [data-ref] canvas").count():
                return False
            time.sleep(1)
        raise TimeoutError("WhatsApp Web did not load")

    def wait_for_login(self, timeout_s: int = 600) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.page.locator("#pane-side").count():
                return True
            time.sleep(1)
        return False

    # ── chats ────────────────────────────────

    def unread_chats(self, limit: int = 15, include_muted: bool = False) -> list[dict]:
        """Chats with an unread badge, scrolling the chat list a few times.
        Muted chats are skipped unless `include_muted`."""
        seen: dict[str, dict] = {}
        pane = self.page.locator("#pane-side")
        for _ in range(8):
            for c in self.page.evaluate(UNREAD_CHATS_JS):
                if include_muted or not c["muted"]:
                    seen.setdefault(c["name"], c)
            if len(seen) >= limit:
                break
            pane.evaluate("el => el.scrollBy(0, el.clientHeight)")
            time.sleep(0.8)
        pane.evaluate("el => el.scrollTo(0, 0)")
        return list(seen.values())[:limit]

    def open_chat(self, name: str):
        """Open a chat by its exact name with the search box (read-only)."""
        box = self.page.locator('#side [contenteditable="true"], #side input[type="text"]').first
        box.click()
        box.fill(name)
        time.sleep(1.5)
        hit = self.page.locator(f'#pane-side span[title="{_css_quote(name)}"]').first
        try:
            hit.wait_for(timeout=10_000)
        except Exception:
            raise LookupError(f"conversa não encontrada: {name!r}") from None
        hit.click()
        self.page.locator('[data-testid="conversation-panel-messages"]').wait_for(timeout=15_000)
        time.sleep(1.5)
        box.fill("")  # clear the search; the chat stays open

    def _rows(self) -> list[dict]:
        return self.page.evaluate(EXTRACT_ROWS_JS)

    def read_messages(self, since: datetime, me: str = "Você") -> list[Message]:
        """Messages in the open chat from `since` until now, oldest first.
        1. Scroll to the top until WhatsApp has loaded a message older than
           `since` (or the start of the chat).
        2. Scroll down half a screen at a time to the end, merging what each
           screen shows (WhatsApp drops the rows far from the screen)."""
        panel = self.page.locator('[data-testid="conversation-panel-messages"]')
        older_loaded = False
        for _ in range(MAX_HISTORY_LOADS):
            dated = [w for w in (parse_pre(r["pre"], self.date_order)[0] for r in self._rows()) if w]
            if dated and min(dated) < since:
                older_loaded = True
                break
            if not self._load_older(panel):
                break  # the start of the chat
        rows: list[dict] = []
        for _ in range(MAX_SCROLL_STEPS):
            rows = merge_rows(rows, self._rows())
            at_end = panel.evaluate("el => el.scrollTop + el.clientHeight >= el.scrollHeight - 4")
            if at_end:
                break
            panel.evaluate("el => el.scrollBy(0, Math.max(200, el.clientHeight / 2))")
            time.sleep(0.5)
        msgs = build_messages(rows, me=me, date_order=self.date_order)
        if not older_loaded and not any(m.when and m.when < since for m in msgs):
            log.warning("Read back to the start of the chat (or WhatsApp stopped loading older messages)")
        return [m for m in msgs if m.when is None or m.when >= since]

    def _load_older(self, panel, timeout_s: float = 8) -> bool:
        """Scroll to the top and wait until WhatsApp adds older messages.
        False when nothing more loads (the start of the chat). WhatsApp can be
        slow here, so it waits for the height to change, not a fixed time."""
        before = panel.evaluate("el => el.scrollHeight")
        panel.evaluate("el => el.scrollTo(0, 0)")
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(0.4)
            if panel.evaluate("el => el.scrollHeight") != before:
                time.sleep(0.6)  # let the new rows render
                return True
            panel.evaluate("el => el.scrollTo(0, 0)")
        return False

    def fetch_audio(self, msg_id: str) -> bytes:
        """Play one voice message muted and return its audio file (ogg/opus)."""
        before = self.page.evaluate("window.__waAudio.length")
        clicked = self.page.evaluate("""(id) => {
            const el = document.querySelector(`[data-id="${CSS.escape(id)}"]`);
            if (!el) return false;
            el.scrollIntoView({block: 'center'});
            // The play button: by its label (pt/en), its icon, or the first button of the bubble
            const box = el.closest('[role="row"]') || el;
            const hit = box.querySelector('button[aria-label*="eproduzir"], button[aria-label*="Play"], button[aria-label*="play"]')
                || box.querySelector('[data-icon="audio-play"]');
            const btn = (hit && hit.closest('button')) || box.querySelector('[data-testid="msg-container"] button');
            if (!btn) return false;
            btn.click();
            return true;
        }""", msg_id)
        if not clicked:
            raise LookupError("botão de play não encontrado")
        for _ in range(40):
            if self.page.evaluate("window.__waAudio.length") > before:
                break
            time.sleep(0.25)
        else:
            raise TimeoutError("o áudio não carregou")
        b64 = self.page.evaluate("""async () => {
            const blob = await fetch(window.__waAudio[window.__waAudio.length - 1]).then(r => r.blob());
            return await new Promise(ok => {
                const fr = new FileReader();
                fr.onload = () => ok(fr.result.split(',')[1]);
                fr.readAsDataURL(blob);
            });
        }""")
        return base64.b64decode(b64)


def _css_quote(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')
