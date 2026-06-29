#!/usr/bin/env bash
#
# Crossy Farm — build script.
# Compiles the native launcher and assembles a self-contained macOS .app bundle.
# Requires Xcode Command Line Tools (clang + /usr/bin/python3): xcode-select --install
#
set -euo pipefail

APP_NAME="Crossy Farm"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/src"
DIST="$HERE/dist"
APP="$DIST/$APP_NAME.app"

echo "==> Building \"$APP_NAME.app\""

# 1. Toolchain checks --------------------------------------------------------
if ! command -v clang >/dev/null 2>&1; then
  echo "ERROR: clang not found. Install Xcode Command Line Tools:" >&2
  echo "       xcode-select --install" >&2
  exit 1
fi
if [ ! -x /usr/bin/python3 ]; then
  echo "ERROR: /usr/bin/python3 not found. Install Xcode Command Line Tools:" >&2
  echo "       xcode-select --install" >&2
  exit 1
fi

# 2. Clean previous build ----------------------------------------------------
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# 3. Compile the native launcher (Apple Silicon, arm64) ----------------------
echo "==> Compiling launcher (arm64)"
clang -arch arm64 -O2 -o "$APP/Contents/MacOS/launcher" "$SRC/launcher.c"

# 4. Assemble the bundle -----------------------------------------------------
echo "==> Assembling bundle"
cp "$SRC/Info.plist" "$APP/Contents/Info.plist"
cp "$SRC/crossy_lib.py" "$SRC/crossy_farm.py" "$SRC/crossy_gui.py" "$APP/Contents/Resources/"
cp "$SRC/icon.icns" "$APP/Contents/Resources/icon.icns"

# 5. Ad-hoc code signature (so TCC permissions stick to the app, not python) -
echo "==> Ad-hoc signing"
codesign --force --sign - "$APP"

echo ""
echo "Done: $APP"
echo "Next: move it to /Applications, then right-click -> Open the first time."
