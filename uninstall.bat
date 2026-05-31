@echo off
REM Remove the autostart shortcut and stop any running server.
setlocal

set "STARTUP_LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\remote-pc-mcp.lnk"
if "%REMOTE_PC_MCP_PORT%"=="" set REMOTE_PC_MCP_PORT=8765

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

REM Also kill any orphaned daemon supervisor that lost its child.
for /f "tokens=2 delims=," %%a in ('wmic process where "name='pythonw.exe' and commandline like '%%daemon.py%%'" get processid /format:csv 2^>nul ^| findstr /R "[0-9]"') do (
    echo Stopping daemon supervisor ^(PID %%a^)...
    taskkill /F /PID %%a >nul 2>&1
)

endlocal & exit /b 0
