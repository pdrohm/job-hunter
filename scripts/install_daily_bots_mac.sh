#!/bin/sh
# Run the morning brief (every day at 08:00) and the interview prep check
# (every 10 minutes) on your Mac with launchd.
# Morning time: MORNING_HOUR=7 MORNING_MINUTE=30 sh scripts/install_daily_bots_mac.sh
# Uninstall:
#   launchctl unload ~/Library/LaunchAgents/com.jobhunter.morningbrief.plist ~/Library/LaunchAgents/com.jobhunter.interviewprep.plist
#   rm ~/Library/LaunchAgents/com.jobhunter.morningbrief.plist ~/Library/LaunchAgents/com.jobhunter.interviewprep.plist
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
AGENTS="$HOME/Library/LaunchAgents"
HOUR="${MORNING_HOUR:-8}"
MINUTE="${MORNING_MINUTE:-0}"

[ -x "$PY" ] || { echo "Missing $PY. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1; }
grep -q '^MORNING_BOT_TOKEN=.' "$REPO/.env" || { echo "Set MORNING_BOT_TOKEN in .env first"; exit 1; }
grep -q '^PREP_BOT_TOKEN=.' "$REPO/.env" || { echo "Set PREP_BOT_TOKEN in .env first"; exit 1; }
grep -q '^CALENDAR_ICS_URL=.' "$REPO/.env" || { echo "Set CALENDAR_ICS_URL in .env first"; exit 1; }
mkdir -p "$HOME/.job-hunter" "$AGENTS"

# launchd has a minimal PATH; the prep bot runs claude
PATH_VALUE="$(dirname "$(command -v claude)"):/usr/bin:/bin:/usr/sbin:/sbin"

# write_plist <label> <python module> <schedule XML>  (runs: python -m <module> from the repo root)
write_plist() {
  cat > "$AGENTS/$1.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>-m</string><string>$2</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$PATH_VALUE</string></dict>
  $3
  <key>ProcessType</key><string>Background</string>
  <key>Nice</key><integer>10</integer>
  <key>StandardOutPath</key><string>$HOME/.job-hunter/$1.log</string>
  <key>StandardErrorPath</key><string>$HOME/.job-hunter/$1.log</string>
</dict>
</plist>
PLIST
  launchctl unload "$AGENTS/$1.plist" 2>/dev/null || true
  launchctl load "$AGENTS/$1.plist"
}

# If the Mac sleeps at 08:00, launchd runs the brief when it wakes up
write_plist com.jobhunter.morningbrief daily.morning_brief \
  "<key>StartCalendarInterval</key><dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>"
write_plist com.jobhunter.interviewprep daily.interview_prep \
  "<key>StartInterval</key><integer>600</integer><key>RunAtLoad</key><true/>"

echo "Installed. Morning brief at $(printf '%02d:%02d' "$HOUR" "$MINUTE"), interview check every 10 min."
echo "Logs: ~/.job-hunter/com.jobhunter.morningbrief.log and ~/.job-hunter/com.jobhunter.interviewprep.log"
