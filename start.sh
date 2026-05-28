#!/usr/bin/env bash
set -u

trap 'echo "Stopping."; exit 0' INT TERM

python -m pip install --quiet --disable-pip-version-check -r requirements.txt
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
    echo "Server exited with code $code. Restarting in 5 seconds..."
    sleep 5
done
