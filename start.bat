@echo off
setlocal

if "%REMOTE_PC_MCP_PORT%"=="" set REMOTE_PC_MCP_PORT=8765

call :install_autostart

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
start /WAIT /B "" pythonw server.py
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

:install_autostart
set "STARTUP_LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\remote-pc-mcp.lnk"
if exist "%STARTUP_LNK%" exit /b 0
echo Registering autostart (hidden, runs at every sign-in)...
set "INSTALL_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=$env:INSTALL_DIR.TrimEnd('\'); $sh=New-Object -ComObject WScript.Shell; $s=$sh.CreateShortcut($env:STARTUP_LNK); $s.TargetPath='wscript.exe'; $s.Arguments='\"' + $d + '\bg.vbs\"'; $s.WorkingDirectory=$d; $s.Save()" >nul 2>&1
if exist "%STARTUP_LNK%" (
    echo Autostart registered. Future logons will launch the server in the background.
) else (
    echo Warning: failed to register autostart. Server will still run now, but won't auto-start at logon.
)
exit /b 0
