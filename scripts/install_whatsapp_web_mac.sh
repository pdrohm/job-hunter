#!/bin/sh
# Keep the WhatsApp summary page running on your Mac: http://127.0.0.1:8765
# Uninstall:
#   launchctl unload ~/Library/LaunchAgents/com.jobhunter.whatsappweb.plist
#   rm ~/Library/LaunchAgents/com.jobhunter.whatsappweb.plist
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LABEL=com.jobhunter.whatsappweb
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

[ -x "$PY" ] || { echo "Missing $PY. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-posts.txt"; exit 1; }
mkdir -p "$HOME/.job-hunter" "$HOME/Library/LaunchAgents"

# launchd has a minimal PATH; a run needs claude, whisper-cli and ffmpeg
PATH_VALUE="$(dirname "$(command -v claude)"):/usr/bin:/bin:/usr/sbin:/sbin"
for tool in whisper-cli ffmpeg; do
  if command -v "$tool" >/dev/null; then PATH_VALUE="$(dirname "$(command -v "$tool")"):$PATH_VALUE"; fi
done

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>-m</string><string>whatsapp_summary.web</string><string>--no-open</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$PATH_VALUE</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>Nice</key><integer>10</integer>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$HOME/.job-hunter/whatsapp_web.log</string>
  <key>StandardErrorPath</key><string>$HOME/.job-hunter/whatsapp_web.log</string>
</dict>
</plist>
PLIST
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "WhatsApp summary page running: http://127.0.0.1:8765  (log: ~/.job-hunter/whatsapp_web.log)"
