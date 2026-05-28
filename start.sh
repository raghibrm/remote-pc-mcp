#!/usr/bin/env bash
set -u

: "${REMOTE_PC_MCP_PORT:=8765}"
export REMOTE_PC_MCP_PORT

trap 'echo "Stopping."; exit 0' INT TERM

probe_health() {
    python -c "import os,sys,urllib.request; p=os.environ.get('REMOTE_PC_MCP_PORT','8765'); urllib.request.urlopen('http://127.0.0.1:'+p+'/health', timeout=2).read(); sys.exit(0)" 2>/dev/null
}

python -m pip install --quiet --disable-pip-version-check -r requirements.txt

if probe_health; then
    echo "remote-pc-mcp already running on port $REMOTE_PC_MCP_PORT. Nothing to do."
    exit 0
fi

pkill -9 -f "python.* server\.py" 2>/dev/null
sleep 1

if [ "${1:-}" = "--selftest" ]; then
    echo "Self-test enabled. Running pytest in background after server starts..."
    (
        sleep 2
        if python -m pytest tests/ -q --tb=short > tests/last_run.log 2>&1; then
            echo "SELF-TEST PASSED" >> tests/last_run.log
        else
            echo "SELF-TEST FAILED" >> tests/last_run.log
        fi
    ) &
fi

while true; do
    python server.py
    code=$?
    if [ "$code" -eq 0 ]; then
        echo "Server exited cleanly."
        exit 0
    fi
    if probe_health; then
        echo "Another remote-pc-mcp now serving port $REMOTE_PC_MCP_PORT. Yielding."
        exit 0
    fi
    echo "Server exited with code $code. Restarting in 5 seconds..."
    sleep 5
done
