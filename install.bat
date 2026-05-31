@echo off
REM Install dependencies and register daemon.py to launch hidden at every
REM Windows sign-in. Idempotent: rerun any time to refresh the shortcut after
REM moving the repo. To remove, run uninstall.bat.
setlocal

set "SCRIPT_DIR=%~dp0"
set "STARTUP_LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\remote-pc-mcp.lnk"

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python is not on PATH. Install Python 3.10+ from python.org and reopen this terminal.
    endlocal & exit /b 1
)
where pythonw >nul 2>&1
if errorlevel 1 (
    echo ERROR: pythonw is not on PATH ^(should ship alongside python.exe^). Reinstall Python.
    endlocal & exit /b 1
)

echo Installing/updating Python dependencies...
python -m pip install --quiet --disable-pip-version-check -r "%SCRIPT_DIR%requirements.txt"
if errorlevel 1 (
    echo ERROR: failed to install dependencies from requirements.txt
    endlocal & exit /b 1
)

if not exist "%SCRIPT_DIR%.env" (
    if exist "%SCRIPT_DIR%.env.example" (
        echo WARNING: no .env file. Copy .env.example to .env and set REMOTE_PC_MCP_TOKEN before starting.
    )
)

echo Registering autostart shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=$env:SCRIPT_DIR.TrimEnd('\'); $pyw=(Get-Command pythonw).Source; $sh=New-Object -ComObject WScript.Shell; $s=$sh.CreateShortcut($env:STARTUP_LNK); $s.TargetPath=$pyw; $s.Arguments='\"' + $d + '\daemon.py\"'; $s.WorkingDirectory=$d; $s.Description='remote-pc-mcp supervisor'; $s.Save()"
if not exist "%STARTUP_LNK%" (
    echo ERROR: failed to create autostart shortcut at:
    echo   %STARTUP_LNK%
    endlocal & exit /b 1
)

echo.
echo Installed. The server will start hidden at every sign-in.
echo   - Logs:  server.log ^(app^) and daemon.log ^(supervisor^)
echo   - Start now without rebooting:  pythonw daemon.py
echo   - Remove autostart:             uninstall.bat
endlocal & exit /b 0
