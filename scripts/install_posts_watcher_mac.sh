#!/bin/sh
# Search LinkedIn POSTS every 2 hours on this Mac and send new ones to Telegram.
# Jobs keep coming from GitHub Actions; this only does posts (it needs the
# logged-in Chrome from `python -m job_hunter.linkedin_posts --login`).
# Uninstall: launchctl unload ~/Library/LaunchAgents/com.jobhunter.posts.plist && rm that file
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.jobhunter.posts.plist"
LOG="$HOME/.job-hunter/posts_watcher.log"
DATA="$HOME/.job-hunter/posts-data"

[ -x "$PY" ] || { echo "Missing $PY. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-posts.txt"; exit 1; }
"$PY" -c "import playwright" 2>/dev/null || { echo "Run: .venv/bin/pip install -r requirements-posts.txt"; exit 1; }
[ -d "$HOME/.job-hunter/linkedin-profile/Default" ] || { echo "Log in first: .venv/bin/python -m job_hunter.linkedin_posts --login"; exit 1; }
[ -f "$REPO/.env" ] || { echo "Missing .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)"; exit 1; }
mkdir -p "$HOME/.job-hunter" "$DATA" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.jobhunter.posts</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>-m</string><string>job_hunter.watcher</string><string>--once</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key><dict>
    <key>WATCH_ENGINES</key><string>linkedin_posts</string>
    <key>DATA_DIR</key><string>$DATA</string>
  </dict>
  <!-- Every 2 hours, one run each time (Chrome closes after the run) -->
  <key>StartInterval</key><integer>7200</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>Nice</key><integer>10</integer>
  <key>LowPriorityIO</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Posts watcher installed: runs now and every 2 hours. Log: $LOG"
