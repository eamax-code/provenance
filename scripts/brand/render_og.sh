#!/bin/sh
# Render scripts/brand/og.html to site/img/og.png (1200×630) with headless Chrome. Run from the repo root.
set -e
CHROME="${CHROME_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
PROFILE="$(mktemp -d)"
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$PROFILE" --window-size=1200,630 \
  --virtual-time-budget=3000 --screenshot="$PWD/site/img/og.png" "file://$PWD/scripts/brand/og.html" 2>/dev/null
rm -rf "$PROFILE"
echo "wrote site/img/og.png"
