# job-hunter

A home for small personal bots. Each bot lives in its own folder (a Python
package) and runs from the repo root with `python -m <folder>.<module>`.

| Folder | What it does | Run |
|---|---|---|
| `job_hunter/` | LinkedIn job scraper, watcher that sends new jobs to Telegram, LinkedIn posts search, web UI (`app.py`) | `python -m job_hunter.watcher` |
| `apply_bot/` | Telegram → Claude Code bot that fills job applications. Its private data is in `apply_bot/apply/` (git-ignored) | `python -m apply_bot.apply_bot` |
| `daily/` | Morning brief and interview prep bots | `python -m daily.morning_brief`, `python -m daily.interview_prep` |
| `whatsapp_summary/` | Reads WhatsApp Web chats (read-only), transcribes voice messages on the Mac and summarizes each chat with Claude into an HTML page | `python -m whatsapp_summary.web` (page at http://127.0.0.1:8765) |
| `shared/` | Code that all bots use: the Telegram client (`shared/telegram.py`) | — |
| `manager/` | Bots Manager: a macOS menu bar app (Swift) to see, start, stop and restart the bots and other local sites | `sh manager/build_app.sh` |

`scripts/` has the macOS launchd installers. `.env` (one file, at the repo root) holds the settings for all bots.
Runtime data: `data/` (job watcher), `~/.job-hunter/` (apply bot, daily bots, logs).

Tests: `.venv/bin/python -m pytest -q` (each `<folder>/test_*.py` is a script; run one with
`.venv/bin/python -m job_hunter.test_scraper`).

### Add a new bot

1. Make a folder with an empty `__init__.py`, e.g. `my_bot/__init__.py` and `my_bot/my_bot.py`.
2. Import other code by package: `from shared import telegram` (send with `telegram.send_message(text, token=...)`).
   Give the bot its own @BotFather token in `.env` so its messages stay apart.
3. Run it from the repo root: `.venv/bin/python -m my_bot.my_bot`. Load `.env` with `load_dotenv()`.
4. Tests: `my_bot/test_my_bot.py` (same script style; pytest finds it).
5. To run it on the Mac, copy a script in `scripts/` and use `-m my_bot.my_bot` with `WorkingDirectory` = repo root.
6. To see it in Bots Manager, add it to `~/.bots-manager/services.json` (below).

## Bots Manager (menu bar app)

One menu bar icon to see all bots and local sites: status (green running, blue scheduled,
orange paused, red failed), start, stop/pause, restart, open the site, the log and the folder.
Needs Xcode (Swift 6) on macOS 14+.

1. `sh manager/build_app.sh` builds `~/Applications/Bots Manager.app` and opens it.
   Turn on **Abrir ao iniciar o Mac** in its window to start it at login.
2. Your services are in `~/.bots-manager/services.json` (outside the repo; **Editar serviços** opens it).
   Start from `manager/services.example.json`. The app reloads the file when it changes.

Kinds of service:
- `launchd`: a LaunchAgent (`label`). Start = load + run, Pause = unload (the plist stays), Restart = `kickstart -k`.
- `command`: any shell line (`command`, `cwd`, `env`), run with `zsh -lc` apart from the app, so it keeps
  running when you quit the app. PID in `~/.bots-manager/run/`, output in `~/.bots-manager/logs/<id>.log`.
  Optional `stop_command`.
- `docker`: `compose_file` → `docker compose up -d` / `down`.

`url` is the site to open; it is also checked (HTTP 2xx/3xx = up; `health_url` to check another path).
CLI with the same logic: `manager/.build/release/bots-manager status | start <id> | stop <id> | restart <id> | log <id>`
(`--config FILE` for another file). Tests: `cd manager && swift test`.

**Chat with Claude** (the ✨ button): a window where you talk to Claude Code, like in the terminal.
It runs `claude -p` with your Claude login (your subscription, no API key) in `~/.bots-manager/chat`,
with the folders of all services added (`--add-dir`) and in auto permission mode. Each message
resumes the same session; **Nova conversa** starts a new one. History: `~/.bots-manager/chat.json`.
`CLAUDE_BIN` sets another `claude` program. From the shell: `bots-manager ask "<text>"`.

## Telegram alerts for new jobs

1. On Telegram, talk to [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token.
2. Send any message to your new bot.
3. `cp .env.example .env` and put the token in `TELEGRAM_BOT_TOKEN`.
4. `python -m job_hunter.notifier --get-chat-id` and put the number in `TELEGRAM_CHAT_ID`.
5. `python -m job_hunter.notifier --test` — you should get a message.
6. `docker compose up -d watcher` — checks every 2 hours and sends only new jobs.

Try it without sending: `python -m job_hunter.watcher --dry-run`. One run only: `python -m job_hunter.watcher --once`.

### Focus: remote, no sponsorship, contractor

By default the watcher:
- searches LinkedIn jobs in `Worldwide`, `Latin America` and `Brazil` (`WATCH_LOCATIONS`);
- drops jobs that need US/UK/EU work authorization, citizenship, a clearance or visa sponsorship (rules in `job_hunter/focus.py`; turn off with `WATCH_ALLOW_SPONSORSHIP=true`);
- ranks higher jobs open to people abroad (worldwide, LATAM, contractor, B2B, PJ, Deel) and lower remote jobs pinned to one foreign country;
- drops junior, entry level and intern roles (title or LinkedIn seniority; turn off with `WATCH_ALLOW_JUNIOR=true`);
- keeps only React Native / Expo roles: the words must be in the job's title, or be the main stack in its own text (a "React Native is a plus" web job fails);
- keeps only jobs in LATAM, listed as worldwide, or whose text says LATAM / worldwide people can apply (turn off with `WATCH_ANY_REGION=true`);
- keeps only US / Canada / Europe companies (or agencies for their clients): the job is listed there, or its text says where the company is based, its time zone or that it pays in USD/EUR. Spanish / Portuguese jobs from local companies are dropped, and you get at most 1 job per company per run (turn off with `WATCH_TOP_MARKETS_ONLY=false`: then a mobile role on a React/TypeScript stack also counts).

Set `WATCH_CONTRACT_ONLY=true` to get only contractor / freelance / B2B work.

## LinkedIn posts (on your Mac)

Posts come from LinkedIn's own post search (`linkedin_posts` engine): posts from
the last 24 hours, newest first. That search needs a logged-in account, so it runs
in a separate Chrome on your Mac, not on GitHub (GitHub sends jobs only).

1. `.venv/bin/pip install -r requirements-posts.txt`
2. `.venv/bin/python -m job_hunter.linkedin_posts --login` and log in to LinkedIn in the Chrome that opens (once).
3. Test: `WATCH_ENGINES=linkedin_posts .venv/bin/python -m job_hunter.watcher --dry-run`
4. Run it every 2 hours: `sh scripts/install_posts_watcher_mac.sh`

The bot reads each post, drops people looking for work (#opentowork), and keeps
remote React Native / Expo hiring posts with no India. To keep the account safe it
does 6 searches per run with pauses, and only reads (the one click per post is
"Copy link to post", because the page has no post links).
Search engines (`yahoo` engine: Yahoo + Bing) still work, but they find few, old posts.

## Apply bot (Telegram → Claude Code on your Mac)

Send `/candidatar <link>` to your bot, tap **📝 Candidatar** under a job alert, or just
talk normally ("candidata nessa: <link>", "muda o salário para 7k", "como tá?", "cancela").
A small Claude call with no tools reads the message and picks the action; the final
send is always the ✅ button.
Claude opens the job in a separate Chrome, fills the form, and sends you a screenshot
plus the answers it wrote. **Nothing is sent until you tap ✅ Enviar** — except auto-apply below.

1. `cp apply_bot/apply/profile.example.md apply_bot/apply/profile.md` and fill it in (Claude uses only this).
2. Put your CV at `apply_bot/apply/resume.pdf`. Recruiters see the file name: to use another one
   (e.g. `apply_bot/apply/YourName-resume.pdf`), set `APPLY_RESUME=apply_bot/apply/YourName-resume.pdf` in `.env`.
3. Test it: `.venv/bin/python -m apply_bot.apply_bot`, then send `/candidatar <link>` on Telegram.
4. Start it at login: `sh scripts/install_apply_bot_mac.sh`
5. Optional, voice messages: `brew install whisper-cpp ffmpeg`, then download the model:
   `curl -L -o ~/.job-hunter/whisper/ggml-large-v3-turbo-q5_0.bin --create-dirs https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin`.
   Voice is transcribed on your Mac and works like a typed message. The audio is
   deleted right after. Language: `APPLY_WHISPER_LANG` (default `pt`, `auto` detects).

Search on demand: `/procurar` (or "procura vaga", also by voice) searches the last week
now and sends the jobs that match (5–10 min). Jobs you applied to never come back. A job
it already showed comes back only when the match is very high (`APPLY_SEARCH_RESEND_SCORE`,
default 80). Other settings: `APPLY_SEARCH_MIN_SCORE`, `APPLY_SEARCH_MAX`,
`APPLY_SEARCH_TIME_RANGE`. `/aplicadas` lists the jobs you applied to, with 🗑 buttons to
remove one from the history.

Auto-apply: every `APPLY_AUTO_SEARCH_HOURS` (default 2) the bot searches quietly and
applies by itself, one at a time, to jobs at `APPLY_AUTO_SCORE` (default 100 pts; `/procurar`
feeds it too). It sends **without ✅ only when the form is complete** (no empty required
field); otherwise it stops and waits for you, like a normal application. A job is tried
once (sent, cancelled or skipped by a profile rule). `/pausar` stops it;
`APPLY_AUTO_SCORE=0` turns it off. Each job costs up to 2 Claude steps (`$3` cap each).

Safety: only your chat ID is accepted; Claude gets only browser tools (no shell, no
files, no code execution, no cookies); the browser is a separate Chrome profile; the
only file it can upload is your CV. History: `~/.job-hunter/applications.jsonl`.

## Daily bots: morning brief and interview prep (on your Mac)

Two more Telegram bots, each with its own token, so their messages stay out of the job alerts.

- **Morning brief** (`daily/morning_brief.py`), every day at 08:00: today's calendar (interviews marked 🎯),
  weather, dollar rate, unread important Gmail, and applications sent in the last 24 h.
  Each part is optional: no config, no part.
- **Interview prep** (`daily/interview_prep.py`), checks every 10 minutes: about 60 minutes before an
  interview, Claude Code searches the company on the web and sends a prep note (company, role,
  which stories from `apply_bot/apply/profile.md` to tell, likely questions, questions to ask).
  Two Claude runs, so an invite with hidden instructions cannot leak your data: the research run
  has only WebSearch/WebFetch and never sees your profile; the run that writes the note sees your
  profile but has no tools. An event is an interview when its title or description has a word
  from `PREP_KEYWORDS`.

Setup:

1. Make two bots with @BotFather. Send any message to each one.
2. Fill the "Daily bots" part of `.env` (see `.env.example`). The calendar link is the
   Google Calendar "Secret address in iCal format". Keep it secret.
3. Try them: `python -m daily.morning_brief --dry-run` and `python -m daily.interview_prep --next --dry-run`.
4. Install: `sh scripts/install_daily_bots_mac.sh` (change the time with `MORNING_HOUR=7 MORNING_MINUTE=30`).

## WhatsApp summary (on your Mac)

Reads chats on WhatsApp Web in its own Chrome profile, transcribes the voice
messages with whisper.cpp (the audio never leaves the Mac), and asks Claude
(no tools) for a short summary of each chat: what happened, what people ask
of you, and what was decided. The result is one HTML page with a card per
chat: `~/.job-hunter/whatsapp/index.html` (it opens when the run ends).

1. `.venv/bin/pip install -r requirements-posts.txt` (Playwright) and the voice setup of the apply bot (whisper.cpp, ffmpeg, model).
2. `.venv/bin/python -m whatsapp_summary.summary --login` and scan the QR code on your phone
   (WhatsApp → Settings → Linked devices). Once.
3. Use the page: `sh scripts/install_whatsapp_web_mac.sh` keeps it running at <http://127.0.0.1:8765>
   (or run it once: `.venv/bin/python -m whatsapp_summary.web`). Pick a chat or "Todas não lidas", the start
   time and the options, and press **Resumir**: you see the progress, and the summaries show on the same page.
   The page only listens on this Mac and runs one summary at a time. "Conectar (QR code)" links WhatsApp again.
4. Or run it from the terminal:
   - `.venv/bin/python -m whatsapp_summary.summary --chat "Group name" --since "ontem 20:54"`
   - `.venv/bin/python -m whatsapp_summary.summary --chat "A" --chat "B"`: since the last run of each chat (or 24h)
   - `.venv/bin/python -m whatsapp_summary.summary --unread`: every chat with unread messages (muted chats only with `--include-muted`)
   - `--telegram` also sends each summary to Telegram (`WA_BOT_TOKEN`, or the job bot), `--no-audio` skips voice,
     `--transcript-only` skips Claude, `--show` shows Chrome, `--report` only rebuilds the page.

`--since` takes `12h`, `2d`, `20:54`, `ontem 20:54`, `15/10 20:54` or `2026-10-15 20:54`.
It never types or sends. But a chat it opens is marked as read on your phone, and a voice message it
reads is marked as played (it plays muted). Chats, transcripts and summaries stay in `~/.job-hunter/whatsapp/`.
