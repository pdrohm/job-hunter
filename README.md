# job-hunter

## Telegram alerts for new jobs

1. On Telegram, talk to [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token.
2. Send any message to your new bot.
3. `cp .env.example .env` and put the token in `TELEGRAM_BOT_TOKEN`.
4. `python notifier.py --get-chat-id` and put the number in `TELEGRAM_CHAT_ID`.
5. `python notifier.py --test` — you should get a message.
6. `docker compose up -d watcher` — checks every 2 hours and sends only new jobs.

Try it without sending: `python watcher.py --dry-run`. One run only: `python watcher.py --once`.

### Focus: remote, no sponsorship, contractor

By default the watcher:
- searches LinkedIn jobs in `Worldwide`, `Latin America` and `Brazil` (`WATCH_LOCATIONS`);
- drops jobs that need US/UK/EU work authorization, citizenship, a clearance or visa sponsorship (rules in `focus.py`; turn off with `WATCH_ALLOW_SPONSORSHIP=true`);
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
2. `.venv/bin/python linkedin_posts.py --login` and log in to LinkedIn in the Chrome that opens (once).
3. Test: `WATCH_ENGINES=linkedin_posts .venv/bin/python watcher.py --dry-run`
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

1. `cp apply/profile.example.md apply/profile.md` and fill it in (Claude uses only this).
2. Put your CV at `apply/resume.pdf`. Recruiters see the file name: to use another one
   (e.g. `apply/YourName-resume.pdf`), set `APPLY_RESUME=apply/YourName-resume.pdf` in `.env`.
3. Test it: `.venv/bin/python apply_bot.py`, then send `/candidatar <link>` on Telegram.
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

- **Morning brief** (`morning_brief.py`), every day at 08:00: today's calendar (interviews marked 🎯),
  weather, dollar rate, unread important Gmail, and applications sent in the last 24 h.
  Each part is optional: no config, no part.
- **Interview prep** (`interview_prep.py`), checks every 10 minutes: about 60 minutes before an
  interview, Claude Code searches the company on the web and sends a prep note (company, role,
  which stories from `apply/profile.md` to tell, likely questions, questions to ask).
  Two Claude runs, so an invite with hidden instructions cannot leak your data: the research run
  has only WebSearch/WebFetch and never sees your profile; the run that writes the note sees your
  profile but has no tools. An event is an interview when its title or description has a word
  from `PREP_KEYWORDS`.

Setup:

1. Make two bots with @BotFather. Send any message to each one.
2. Fill the "Daily bots" part of `.env` (see `.env.example`). The calendar link is the
   Google Calendar "Secret address in iCal format". Keep it secret.
3. Try them: `python morning_brief.py --dry-run` and `python interview_prep.py --next --dry-run`.
4. Install: `sh scripts/install_daily_bots_mac.sh` (change the time with `MORNING_HOUR=7 MORNING_MINUTE=30`).
