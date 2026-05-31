@echo off
REM Foreground run for development: visible console, no autostart side effects.
REM For supervised/hidden background use, run install.bat once (registers
REM `pythonw daemon.py` to launch at every sign-in).
setlocal

if "%REMOTE_PC_MCP_PORT%"=="" set REMOTE_PC_MCP_PORT=8765

call :probe_health
if not errorlevel 1 (
    echo remote-pc-mcp already running on port %REMOTE_PC_MCP_PORT%. Nothing to do.
    endlocal & exit /b 0
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%REMOTE_PC_MCP_PORT% " ^| findstr "LISTENING"') do (
    echo Stopping non-responsive listener on port %REMOTE_PC_MCP_PORT%, PID %%a
    taskkill /F /PID %%a >nul 2>&1
)

python server.py
endlocal & exit /b %errorlevel%

:probe_health
python -c "import os,sys,urllib.request; p=os.environ.get('REMOTE_PC_MCP_PORT','8765'); urllib.request.urlopen('http://127.0.0.1:'+p+'/health', timeout=2).read(); sys.exit(0)" 2>nul
exit /b %errorlevel%
