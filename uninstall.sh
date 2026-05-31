#!/usr/bin/env bash
# Remove the systemd user unit and stop any running server / supervisor.
set -u

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_FILE="$UNIT_DIR/remote-pc-mcp.service"

if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now remote-pc-mcp.service 2>/dev/null || true
fi

if [ -f "$UNIT_FILE" ]; then
    rm -f "$UNIT_FILE"
    echo "Removed systemd user unit."
else
    echo "systemd user unit was not installed."
fi

if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload || true
fi

pkill -f "python.* daemon\.py" 2>/dev/null || true
pkill -f "python.* server\.py" 2>/dev/null || true

echo "Done."
