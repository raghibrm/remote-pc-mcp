@echo off
setlocal

if "%REMOTE_PC_MCP_PORT%"=="" set REMOTE_PC_MCP_PORT=8765

python -m pip install --quiet --disable-pip-version-check -r requirements.txt

call :probe_health
if not errorlevel 1 (
    echo remote-pc-mcp already running on port %REMOTE_PC_MCP_PORT%. Nothing to do.
    endlocal & exit /b 0
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%REMOTE_PC_MCP_PORT% " ^| findstr "LISTENING"') do (
    echo Stopping non-responsive listener on port %REMOTE_PC_MCP_PORT%, PID %%a
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

call :probe_health
if not errorlevel 1 (
    echo Another remote-pc-mcp now serving port %REMOTE_PC_MCP_PORT%. Yielding.
    goto end
)

echo Server exited with code %CODE%. Restarting in 5 seconds... (Ctrl+C twice to abort)
timeout /t 5 /nobreak >nul
goto loop

:end
echo Done.
endlocal & exit /b 0

:probe_health
python -c "import os,sys,urllib.request; p=os.environ.get('REMOTE_PC_MCP_PORT','8765'); urllib.request.urlopen('http://127.0.0.1:'+p+'/health', timeout=2).read(); sys.exit(0)" 2>nul
exit /b %errorlevel%
