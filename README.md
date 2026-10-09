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
- ranks higher jobs open to people abroad (worldwide, LATAM, contractor, B2B, PJ, Deel) and lower remote jobs pinned to one foreign country.

Set `WATCH_CONTRACT_ONLY=true` to get only contractor / freelance / B2B work.

LinkedIn posts come from Yahoo search (`yahoo` engine), and the bot reads each post's full text before it filters.

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
