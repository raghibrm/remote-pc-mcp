#!/usr/bin/env bash
# Foreground run for development: visible console, no autostart side effects.
# For supervised/hidden background use, run install.sh once (registers a
# systemd user unit that runs `python daemon.py` and restarts on failure).
set -u

: "${REMOTE_PC_MCP_PORT:=8765}"
export REMOTE_PC_MCP_PORT

trap 'echo "Stopping."; exit 0' INT TERM

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
    echo "ERROR: neither python3 nor python is on PATH." >&2
    exit 1
fi

probe_health() {
    "$PY" -c "import os,sys,urllib.request; p=os.environ.get('REMOTE_PC_MCP_PORT','8765'); urllib.request.urlopen('http://127.0.0.1:'+p+'/health', timeout=2).read(); sys.exit(0)" 2>/dev/null
}

if probe_health; then
    echo "remote-pc-mcp already running on port $REMOTE_PC_MCP_PORT. Nothing to do."
    exit 0
fi

pkill -9 -f "python.* server\.py" 2>/dev/null || true
sleep 1

exec "$PY" server.py
