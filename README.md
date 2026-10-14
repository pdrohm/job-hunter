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
plus the answers it wrote. **Nothing is sent until you tap ✅ Enviar.**

1. `cp apply/profile.example.md apply/profile.md` and fill it in (Claude uses only this).
2. Put your CV at `apply/resume.pdf`.
3. Test it: `.venv/bin/python apply_bot.py`, then send `/candidatar <link>` on Telegram.
4. Start it at login: `sh scripts/install_apply_bot_mac.sh`

Safety: only your chat ID is accepted; Claude gets only browser tools (no shell, no
files, no code execution, no cookies); the browser is a separate Chrome profile; the
only file it can upload is your CV. History: `~/.job-hunter/applications.jsonl`.
