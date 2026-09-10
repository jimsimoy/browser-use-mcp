#!/bin/zsh
# Launcher used by the MCP client. Resolves the venv and execs the server.
# stdout is the MCP stdio channel, so nothing may be echoed to it here.
HERE="$(cd "$(dirname "$0")" && pwd)"

for candidate in "$BROWSER_USE_MCP_VENV" "$HERE/.venv" "$HOME/.browser-use-mcp/venv"; do
  if [ -n "$candidate" ] && [ -x "$candidate/bin/python" ]; then
    exec "$candidate/bin/python" "$HERE/server.py" "$@"
  fi
done

echo "browser-use-mcp: no virtualenv found. Run $HERE/setup.sh" >&2
exit 1
