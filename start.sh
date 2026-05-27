#!/usr/bin/env bash
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
pkill -9 -f "python.* server\.py" 2>/dev/null
sleep 1
python server.py
