@echo off
REM Enables Windows auto-logon so the machine boots straight into your desktop
REM session. The desktop logon triggers the Startup-folder shortcut installed
REM by install.bat, which starts the daemon. End result: cold reboot -> server
REM reachable, no keyboard touch required.
REM
REM Without this, install.bat's autostart only fires when you manually log in
REM at the lock screen. On a headless / "always-on remote" PC that's a problem.
REM
REM Uses Sysinternals Autologon (Microsoft tool). Your password is stored
REM LSA-encrypted via the OS's Secrets store -- NOT in plain text and NOT in
REM the registry as cleartext.
REM
REM https://learn.microsoft.com/en-us/sysinternals/downloads/autologon
setlocal

set "AUTOLOGON_EXE=%TEMP%\Autologon64.exe"
set "AUTOLOGON_URL=https://live.sysinternals.com/Autologon64.exe"

if not exist "%AUTOLOGON_EXE%" (
    echo Downloading Sysinternals Autologon from Microsoft...
    powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%AUTOLOGON_URL%' -OutFile '%AUTOLOGON_EXE%' -UseBasicParsing -ErrorAction Stop } catch { Write-Error $_; exit 1 }"
    if errorlevel 1 (
        echo.
        echo ERROR: failed to download Autologon. Download it manually from
        echo   https://learn.microsoft.com/en-us/sysinternals/downloads/autologon
        echo and run Autologon64.exe directly.
        endlocal & exit /b 1
    )
)

echo.
echo Launching Sysinternals Autologon...
echo.
echo   1. Enter your Windows USERNAME (e.g. User)
echo   2. Enter your DOMAIN -- usually your COMPUTER NAME (run `hostname` to see it)
echo   3. Enter your Windows password
echo   4. Click ENABLE
echo   5. Close the window
echo.
echo Your password is stored LSA-encrypted by Windows; it is not written to
echo the registry or any file in plain text.
echo.

"%AUTOLOGON_EXE%" /accepteula

echo.
echo If you clicked Enable: reboot to test. After reboot the machine should
echo log you in automatically, the remote-pc-mcp daemon should come up, and
echo http://localhost:8765/health should respond -- all without typing a
echo password.
echo.
echo To DISABLE auto-logon later: rerun this script and click Disable.
endlocal & exit /b 0
