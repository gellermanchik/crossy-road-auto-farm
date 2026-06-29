#!/usr/bin/env bash
#
# Crossy Farm — DMG packager.
# Builds a drag-to-Applications disk image with a custom background from the .app.
# Used for GitHub Releases.
#
# Preferred tool: dmgbuild (pip3 install dmgbuild) — writes the .DS_Store layout
# directly, no Finder/AppleScript needed (reliable & headless). Falls back to
# create-dmg, then a plain hdiutil image.
#
set -euo pipefail

APP_NAME="Crossy Farm"
VERSION="1.1"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="$HERE/dist"
APP="$DIST/$APP_NAME.app"
DMG="$DIST/Crossy-Farm-$VERSION.dmg"

# Make sure the app exists.
[ -d "$APP" ] || "$HERE/build.sh"

cd "$HERE"
rm -f "$DMG"

if command -v dmgbuild >/dev/null 2>&1; then
  echo "==> Building DMG with dmgbuild (custom background + layout)"
  dmgbuild -s packaging/dmg_settings.py "$APP_NAME" "$DMG"

elif command -v create-dmg >/dev/null 2>&1; then
  echo "==> dmgbuild not found — using create-dmg (needs Finder/GUI session)"
  create-dmg \
    --volname "$APP_NAME" \
    --background docs/dmg-background.png \
    --window-pos 200 120 --window-size 640 400 \
    --icon-size 140 --text-size 13 \
    --icon "$APP_NAME.app" 160 185 \
    --app-drop-link 480 185 \
    --no-internet-enable \
    "$DMG" "$APP" || [ -f "$DMG" ]

else
  echo "==> No DMG tool found — plain hdiutil image (no custom background)."
  echo "    For the pretty installer: pip3 install dmgbuild"
  STAGE="$(mktemp -d)"
  cp -R "$APP" "$STAGE/"
  ln -s /Applications "$STAGE/Applications"
  hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
  rm -rf "$STAGE"
fi

echo ""
echo "Done: $DMG"
