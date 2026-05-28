@echo off
setlocal

python -m pip install --quiet --disable-pip-version-check -r requirements.txt
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765 " ^| findstr "LISTENING"') do (
    echo Stopping existing server on port 8765, PID %%a
    taskkill /F /PID %%a >nul 2>&1
)

if "%1"=="--selftest" (
    echo Self-test enabled. Running pytest in background after server starts...
    start "remote-pc-mcp self-test" /b cmd /c "timeout /t 2 /nobreak >nul && python -m pytest tests\ -q --tb=short > tests\last_run.log 2>&1 && echo SELF-TEST PASSED >> tests\last_run.log || echo SELF-TEST FAILED >> tests\last_run.log"
)

:loop
python server.py
set CODE=%errorlevel%
if "%CODE%"=="0" goto end
echo Server exited with code %CODE%. Restarting in 5 seconds... (Ctrl+C twice to abort)
timeout /t 5 /nobreak >nul
goto loop

:end
echo Server exited cleanly.
endlocal
