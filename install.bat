@echo off
REM Single entry point for setup on Windows.
REM
REM Usage:
REM   install.bat                Install deps and register autostart (default)
REM   install.bat --uninstall    Remove autostart and stop the running server
REM   install.bat --help         Show this help
REM
REM Autostart fires when you sign in to Windows. A reboot that sits at the
REM lock screen will NOT start the daemon until you log in. This is intentional
REM -- enabling Windows auto-logon would let anyone with physical access get a
REM logged-in desktop, which is the wrong trade-off for a remote-control tool.
setlocal

set "MODE=install"

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--uninstall" ( set "MODE=uninstall" & shift & goto parse_args )
if /i "%~1"=="--help"      goto show_help
if /i "%~1"=="-h"          goto show_help
echo Unknown argument: %~1
echo.
call :print_usage
endlocal & exit /b 2
:args_done

set "SCRIPT_DIR=%~dp0"
set "STARTUP_LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\remote-pc-mcp.lnk"
if "%REMOTE_PC_MCP_PORT%"=="" set REMOTE_PC_MCP_PORT=8765

if "%MODE%"=="uninstall" goto do_uninstall
goto do_install


:show_help
call :print_usage
endlocal & exit /b 0

:print_usage
echo Usage:
echo   install.bat                Install deps and register autostart, start now
echo   install.bat --uninstall    Remove autostart, stop the running server
echo   install.bat --help         Show this help
exit /b 0


:do_install
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

if not exist "%SCRIPT_DIR%daemon.py" (
    echo ERROR: daemon.py not found in %SCRIPT_DIR%
    echo This doesn't look like a complete checkout of remote-pc-mcp.
    endlocal & exit /b 1
)

echo Registering autostart shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=$env:SCRIPT_DIR.TrimEnd('\'); $pyw=(Get-Command pythonw).Source; $sh=New-Object -ComObject WScript.Shell; $s=$sh.CreateShortcut($env:STARTUP_LNK); $s.TargetPath=$pyw; $s.Arguments='\"' + $d + '\daemon.py\"'; $s.WorkingDirectory=$d; $s.Description='remote-pc-mcp supervisor'; $s.Save()"
if not exist "%STARTUP_LNK%" (
    echo ERROR: failed to create autostart shortcut at:
    echo   %STARTUP_LNK%
    endlocal & exit /b 1
)

echo Ensuring Windows Firewall rule for TCP port %REMOTE_PC_MCP_PORT%...
powershell -NoProfile -Command "if (-not (Get-NetFirewallRule -DisplayName 'remote-pc-mcp' -ErrorAction SilentlyContinue)) { try { New-NetFirewallRule -DisplayName 'remote-pc-mcp' -Direction Inbound -Protocol TCP -LocalPort $env:REMOTE_PC_MCP_PORT -Action Allow -Profile Any -ErrorAction Stop | Out-Null; Write-Output 'Firewall rule created.' } catch { Write-Output ('WARNING: could not create firewall rule (needs Administrator). Run this once as admin: New-NetFirewallRule -DisplayName ''remote-pc-mcp'' -Direction Inbound -Protocol TCP -LocalPort ' + $env:REMOTE_PC_MCP_PORT + ' -Action Allow') } } else { Write-Output 'Firewall rule already present.' }"

echo Starting daemon in the background...
powershell -NoProfile -Command "$pyw=(Get-Command pythonw).Source; Start-Process -FilePath $pyw -ArgumentList ('\"' + $env:SCRIPT_DIR + 'daemon.py\"') -WorkingDirectory $env:SCRIPT_DIR -WindowStyle Hidden"

echo Waiting for /health to respond...
powershell -NoProfile -Command "for ($i=0; $i -lt 25; $i++) { try { Invoke-WebRequest -Uri ('http://127.0.0.1:' + $env:REMOTE_PC_MCP_PORT + '/health') -TimeoutSec 1 -UseBasicParsing | Out-Null; Write-Output 'Daemon is up.'; exit 0 } catch { Start-Sleep -Milliseconds 600 } }; Write-Output 'ERROR: daemon did not respond within ~15s. Most likely cause: .env missing or REMOTE_PC_MCP_TOKEN not set. Check daemon.log and server.log.'; exit 1"
if errorlevel 1 (
    echo.
    echo Install registered autostart but daemon failed to come up.
    echo Fix the cause above and run install.bat again.
    endlocal & exit /b 1
)

echo.
echo Installed and running. Future sign-ins will start it automatically.
echo   - Logs:      server.log ^(app^), daemon.log ^(supervisor^)
echo   - Health:    curl http://localhost:%REMOTE_PC_MCP_PORT%/health
echo   - Remove:    install.bat --uninstall
echo.
echo After a reboot, the daemon starts when you log in. To bring it up
echo without walking to the PC, sign in via Remote Desktop or Tailscale SSH.
endlocal & exit /b 0


:do_uninstall
if exist "%STARTUP_LNK%" (
    del "%STARTUP_LNK%"
    echo Removed autostart shortcut.
) else (
    echo Autostart shortcut was not installed.
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%REMOTE_PC_MCP_PORT% " ^| findstr "LISTENING"') do (
    echo Stopping server on port %REMOTE_PC_MCP_PORT% ^(PID %%a^)...
    taskkill /F /PID %%a >nul 2>&1
)

REM Kill any orphaned daemon supervisor that lost its child.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*daemon.py*' } | ForEach-Object { Write-Output ('Stopping daemon supervisor (PID ' + $_.ProcessId + ')...'); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

endlocal & exit /b 0
