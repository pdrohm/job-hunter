#!/bin/sh
# Start apply_bot.py automatically when you log in to your Mac (launchd).
# Uninstall: launchctl unload ~/Library/LaunchAgents/com.jobhunter.applybot.plist && rm that file
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.jobhunter.applybot.plist"
LOG="$HOME/.job-hunter/apply_bot.log"

[ -x "$PY" ] || { echo "Missing $PY. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1; }
[ -f "$REPO/apply/profile.md" ] || { echo "Missing apply/profile.md (copy apply/profile.example.md)"; exit 1; }
[ -f "$REPO/apply/resume.pdf" ] || { echo "Missing apply/resume.pdf"; exit 1; }
mkdir -p "$HOME/.job-hunter" "$HOME/Library/LaunchAgents"

# launchd has a minimal PATH; claude and npx need theirs
PATH_VALUE="$(dirname "$(command -v claude)"):$(dirname "$(command -v npx)"):/usr/bin:/bin:/usr/sbin:/sbin"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.jobhunter.applybot</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$REPO/apply_bot.py</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$PATH_VALUE</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <!-- Low impact: macOS may throttle it, it yields CPU and disk to your apps,
       and a crash loop restarts at most every 30 s -->
  <key>ProcessType</key><string>Background</string>
  <key>Nice</key><integer>10</integer>
  <key>LowPriorityIO</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Apply bot installed and running. Log: $LOG"
