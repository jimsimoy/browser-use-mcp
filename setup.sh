#!/bin/zsh
# ---------------------------------------------------------------------------
# browser-use-mcp — first-time setup.
#
# Creates a virtualenv and installs the pinned dependencies.
#
# By default the venv is created at ./.venv. Set BROWSER_USE_MCP_VENV to put it
# elsewhere — useful when the checkout lives on a synced or network-backed
# volume, where a venv's thousands of files and machine-specific absolute paths
# are better kept on local disk.
# ---------------------------------------------------------------------------

set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${BROWSER_USE_MCP_VENV:-$HERE/.venv}"

echo "source : $HERE"
echo "venv   : $VENV"
echo

mkdir -p "$(dirname "$VENV")"
[ -d "$VENV" ] || python3 -m venv "$VENV"

"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$HERE/requirements.txt"

# No `playwright install` by default. The server launches with channel="chrome"
# and drives the system Google Chrome, so there is no ~150MB browser download to
# manage and testing happens in the browser real visitors use. It falls back to
# bundled Chromium if Chrome is absent — which does need the download below.
if [ ! -d "/Applications/Google Chrome.app" ] && ! command -v google-chrome >/dev/null 2>&1; then
  echo "Google Chrome not found — installing bundled Chromium instead."
  "$VENV/bin/playwright" install chromium
fi

echo "installed:"
"$VENV/bin/pip" list 2>/dev/null | grep -iE "^(mcp|playwright) " | sed 's/^/  /'
echo
echo "Verify:  $VENV/bin/python $HERE/selftest.py"
echo "Register: claude mcp add browser-use --scope user -- $HERE/run.sh"
