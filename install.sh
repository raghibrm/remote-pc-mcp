#!/usr/bin/env bash
# Install dependencies and register a systemd user unit so daemon.py runs at
# every login and is restarted on failure. Idempotent: rerun any time to
# refresh the unit after moving the repo. To remove, run uninstall.sh.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_FILE="$UNIT_DIR/remote-pc-mcp.service"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
    echo "ERROR: neither python3 nor python is on PATH. Install Python 3.10+." >&2
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    echo "ERROR: systemctl not found. This installer requires systemd." >&2
    echo "On a non-systemd system, run \`$PY $SCRIPT_DIR/daemon.py\` from your" >&2
    echo "init system of choice (cron @reboot, runit, openrc, etc.)." >&2
    exit 1
fi

echo "Installing/updating Python dependencies..."
"$PY" -m pip install --quiet --disable-pip-version-check -r "$SCRIPT_DIR/requirements.txt"

if [ ! -f "$SCRIPT_DIR/.env" ] && [ -f "$SCRIPT_DIR/.env.example" ]; then
    echo "WARNING: no .env file. Copy .env.example to .env and set REMOTE_PC_MCP_TOKEN before starting."
fi

echo "Writing systemd user unit at $UNIT_FILE..."
mkdir -p "$UNIT_DIR"
cat > "$UNIT_FILE" <<EOF
[Unit]
Description=remote-pc-mcp supervisor
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
EnvironmentFile=-$SCRIPT_DIR/.env
ExecStart=$PY $SCRIPT_DIR/daemon.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now remote-pc-mcp.service

echo
echo "Installed. The server will start at every login."
echo "  - Status:   systemctl --user status remote-pc-mcp"
echo "  - Logs:     server.log (app), daemon.log (supervisor)"
echo "              journalctl --user -u remote-pc-mcp -f"
echo "  - Restart:  systemctl --user restart remote-pc-mcp"
echo "  - Remove:   ./uninstall.sh"
echo
echo "To keep the server running even when no user is logged in:"
echo "  sudo loginctl enable-linger \$USER"
