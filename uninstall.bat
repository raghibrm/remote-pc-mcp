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

REM Also kill any orphaned daemon supervisor that lost its child. wmic is
REM deprecated in Windows 11; this uses CIM via PowerShell instead.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*daemon.py*' } | ForEach-Object { Write-Output ('Stopping daemon supervisor (PID ' + $_.ProcessId + ')...'); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

endlocal & exit /b 0
