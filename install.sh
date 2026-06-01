#!/usr/bin/env bash
# Single entry point for setup on Linux.
#
# Usage:
#   ./install.sh              Install deps and register a systemd user unit (default)
#   ./install.sh --linger     Same, plus `sudo loginctl enable-linger $USER` so
#                             the unit runs even before any user logs in
#   ./install.sh --uninstall  Disable & remove the unit, stop the running server
#   ./install.sh --help       Show this help
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_FILE="$UNIT_DIR/remote-pc-mcp.service"

mode="install"
linger=0
while [ $# -gt 0 ]; do
    case "$1" in
        --uninstall) mode="uninstall"; shift ;;
        --linger)    linger=1; shift ;;
        --help|-h)
            sed -n '2,9p' "$0" | sed 's/^# //;s/^#//'
            exit 0
            ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

do_install() {
    local PY
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
StartLimitIntervalSec=60
StartLimitBurst=10

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
EnvironmentFile=-$SCRIPT_DIR/.env
ExecStart=$PY $SCRIPT_DIR/daemon.py
Restart=on-failure
RestartSec=5
SyslogIdentifier=remote-pc-mcp

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable --now remote-pc-mcp.service

    if [ "$linger" -eq 1 ]; then
        echo "Enabling user lingering (server runs even when nobody is logged in)..."
        if ! sudo loginctl enable-linger "$USER"; then
            echo "WARNING: loginctl enable-linger failed. The unit is installed but linger is not enabled."
            echo "Re-run \`sudo loginctl enable-linger \$USER\` once you have sudo to finish."
        fi
    fi

    local port="${REMOTE_PC_MCP_PORT:-8765}"
    echo "Waiting for /health to respond on port $port..."
    local up=0
    for i in $(seq 1 25); do
        if curl -fsS --max-time 1 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
            up=1
            break
        fi
        sleep 0.6
    done
    if [ "$up" -ne 1 ]; then
        echo "ERROR: daemon did not respond on :$port within ~15s." >&2
        echo "Most likely cause: .env missing or REMOTE_PC_MCP_TOKEN not set." >&2
        echo "Check: systemctl --user status remote-pc-mcp ; tail server.log daemon.log" >&2
        exit 1
    fi
    echo "Daemon is up."

    echo
    echo "Installed and running. Future logins will start it automatically."
    echo "  - Status:    systemctl --user status remote-pc-mcp"
    echo "  - Logs:      server.log (app), daemon.log (supervisor)"
    echo "               journalctl --user -u remote-pc-mcp -f"
    echo "  - Restart:   systemctl --user restart remote-pc-mcp"
    echo "  - Remove:    ./install.sh --uninstall"
    if [ "$linger" -ne 1 ]; then
        echo
        echo "For boot-time start (server runs even before any user logs in):"
        echo "  ./install.sh --linger     (one-shot; runs \`sudo loginctl enable-linger \$USER\`)"
    fi
}

do_uninstall() {
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
}

case "$mode" in
    install)   do_install ;;
    uninstall) do_uninstall ;;
esac
