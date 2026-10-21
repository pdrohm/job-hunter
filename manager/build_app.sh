#!/bin/sh
# Builds "Bots Manager.app" (menu bar only) into ~/Applications and starts it.
# Usage: sh manager/build_app.sh            (DEST=/some/dir to put the app elsewhere)
set -e
cd "$(dirname "$0")"

DEST="${DEST:-$HOME/Applications}"
APP="$DEST/Bots Manager.app"
BIN_DIR="$(swift build -c release --show-bin-path)"

swift build -c release

# Quit the running copy so the new binary can replace it.
pkill -x BotsManager 2>/dev/null && sleep 1 || true

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN_DIR/BotsManager" "$APP/Contents/MacOS/BotsManager"
# The CLI goes inside the app too: "$APP/Contents/MacOS/bots-manager status"
cp "$BIN_DIR/bots-manager" "$APP/Contents/MacOS/bots-manager"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Bots Manager</string>
  <key>CFBundleDisplayName</key><string>Bots Manager</string>
  <key>CFBundleIdentifier</key><string>local.bots-manager</string>
  <key>CFBundleExecutable</key><string>BotsManager</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
</dict>
</plist>
PLIST

codesign --force --deep --sign - "$APP"
echo "OK: $APP"

if [ "${NO_OPEN:-}" != "1" ]; then
  open "$APP"
fi
