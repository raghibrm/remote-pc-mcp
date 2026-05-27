@echo off
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765 " ^| findstr "LISTENING"') do (
    echo Stopping existing server on port 8765, PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
python server.py
