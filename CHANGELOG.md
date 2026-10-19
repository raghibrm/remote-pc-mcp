# Changelog

All notable changes to this project will be documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project follows semver from 0.2.0 onward.

## [0.6.2] — 2026-10-18

Found by a stress test on a real Windows 11 host (3840x2160 at 225%, Parsec
running) under load.

### Fixed
- A slow tool froze the whole server. FastMCP runs a plain function tool on
  the event loop, so a 1 s CPU sample, a 4K screenshot or a kill wait blocked
  every other request: five concurrent `system_info` calls took 7.8 s and held
  `/health` for 7.4 s. Blocking tools now run in a worker thread (the same five
  calls take 2.1 s, `/health` stays under 0.1 s), and the mouse and keyboard
  tools share a lock so two clients' input cannot mix.
- `kill_process` on a `start_process` job ended only the shell and answered
  `killed: true` while what it launched kept running; a 12-worker job kept
  every core busy. It now ends the whole job and reports how many processes it
  ended. Any other PID is still ended alone.
- `type_text` garbled text: pyautogui sends each key event on its own, other
  input landed between them, so "Line 2" came out "LINE @", Shift went missing
  from `)_+{}:`, and whole runs were lost. It also dropped every non-ASCII
  character. On Windows text now goes in as Unicode key events, so no Shift is
  involved and accents, dashes and emoji come through. `interval` now defaults
  to 10 ms between characters, because Windows 11 Notepad drops a fast burst;
  `interval=0` still sends one burst.
- `press_key` combos could lose their modifier (`ctrl+s` typed "s"). On
  Windows each combo now goes in as one SendInput batch, with the extended-key
  flag for arrows and navigation keys.
- `scroll` on Windows moved by raw wheel units, 120 to a notch, so `scroll(-5)`
  barely moved a page. `amount` is now notches on every platform.

### Added
- `take_screenshot(delay=...)` waits up to 10 s before capturing, because a
  screenshot taken straight after a click can still show the old screen.

### Changed
- The agent skill now points to the server's own tool descriptions and this
  README instead of copying them, so it no longer goes stale with each release.

## [0.6.1] — 2026-10-18

### Fixed
- The daemon exited when it found a server already running, which left a
  server started any other way (an older autostart that runs `server.py`
  directly at logon, or a manual run) with nothing to restart it after a
  crash. The daemon now watches that server's health every 30 seconds and,
  after three missed checks in a row, starts its own and supervises it.
- A lock file under `.state/` lets only one daemon run at a time, so a second
  sign-in that fires the Startup shortcut again exits instead of competing.

## [0.6.0] — 2026-10-18

### Changed (breaking)
- `take_screenshot` returns a JPEG image sized for a vision model, plus a
  JSON block with the image size, the scale, the desktop's geometry, and the
  path of the full-resolution PNG on the host. It no longer returns
  `image_base64`. The image is at most 1568 px on its long edge and
  1,150,000 px in total, the Claude API's standard limits, so the client does
  not shrink it again. `REMOTE_PC_MCP_SCREEN_MAX_EDGE` and
  `REMOTE_PC_MCP_SCREEN_MAX_PIXELS` change the limits.
- `click`, `move_mouse`, and `scroll` take `(x, y)` in that image's pixels,
  and the server maps them to the desktop. A caller that sent desktop
  coordinates must switch. With both limits set to `0`, one image pixel is
  one desktop pixel, counted from the image's top-left corner.

### Fixed
- On Windows with monitors at different scales, screenshots and clicks
  disagreed on every monitor whose scale differs from the system's, even
  after 0.5.1. The server now runs per-monitor DPI-aware and captures with
  Pillow in-process, so both use physical pixels on every monitor.
- On Windows with a monitor left of or above the primary one, screenshot
  pixels were offset from click coordinates. The mapping now includes the
  offset.

## [0.5.1] — 2026-10-18

### Fixed
- `take_screenshot` captured only the top-left part of the screen on a
  Windows display scaled above 100%. A 3840x2160 display at 225% came back
  as its top-left 1707x960. The capture now runs DPI-aware, so the image is
  the whole desktop in physical pixels, the same space `click` uses.
- README and the tool description said `take_screenshot` captures the
  primary display. It captures the whole desktop, every monitor.

### Added
- `get_process_output` returns `exit_code` once a job ends. It is `None`
  while the job runs, and for a job that outlived a server restart.
- `skills/remote-pc/`, an agent skill that tells an agent when and how to use
  this server.

## [0.3.2] — 2026-05-30 (superseded by 0.4.0)

### Added (later removed in 0.4.0)
- `setup-auto-logon.bat` — downloaded Microsoft Sysinternals Autologon
  and ran its GUI to enable Windows auto-logon, so a rebooted machine
  would boot to the desktop and trigger the Startup-folder shortcut
  without anyone touching the keyboard. **Removed in 0.4.0** because
  the security cost (anyone with physical access gets a logged-in
  desktop, every boot) is not the right default for a remote-control
  tool, even as opt-in.

### Changed
- Neutralized AI-client framing: README and tests describe the project
  as an MCP server usable by any compliant client (Claude Desktop,
  Claude Code, Cursor, Cline, Continue, Windsurf, custom agents)
  rather than hard-coding Claude Code.

## [0.5.0] — 2026-10-06

### Added
- Packaged for PyPI as `remote-pc-mcp`, with console entry points
  `remote-pc-mcp` (server) and `remote-pc-mcp-daemon` (supervisor), and
  `server.json` for the official MCP registry
  (`io.github.raghibrm/remote-pc-mcp`).

### Changed
- Modules moved into a `remote_pc_mcp/` package. Root `server.py` and
  `daemon.py` are now shims, so existing clones, Startup shortcuts, and
  systemd units keep working across a pull.
- `.env`, logs, and `.state/` resolve via `REMOTE_PC_MCP_HOME` (the shims pin
  it to the repo root; default elsewhere is the working directory) instead of
  the module's own directory.
- The daemon spawns the server as `python -m remote_pc_mcp.server` instead of
  by file path.

## [0.4.1] — 2026-05-31

### Fixed
- **`install.bat` now actually starts the daemon** after registering the
  Startup shortcut, and polls `/health` until it responds (exits non-zero
  if it doesn't within ~15s). Previously it only registered the
  future-logon shortcut — README claimed "starts it now" but the script
  didn't, so users running `install.bat` on a fresh PC saw nothing
  listening on :8765 until they signed out and back in. Same `/health`
  probe added to `install.sh`.
- **`install.bat` creates the Windows Firewall inbound rule** for TCP
  `REMOTE_PC_MCP_PORT` automatically (warns if not Administrator and
  prints the exact command to run as admin). Previously the rule had to
  be created by hand per the onboarding docs; forgetting it meant the
  server was unreachable from other devices even when running locally.
- **`install.bat` verifies `daemon.py` exists** before touching anything,
  so a partial / corrupted checkout fails loudly instead of writing a
  shortcut to a non-existent file.
- **`install.bat --uninstal` (typo) now exits 2**, not 0 — caller scripts
  that check `%errorlevel%` no longer see false success on misspellings.
- **`install.sh --help`** now includes the `--help` line itself (sed
  range was `'2,8p'`, should have been `'2,9p'`).
- **`install.sh --linger`** no longer aborts the whole script when sudo
  fails; prints a recoverable warning so the unit install is preserved.

## [0.4.0] — 2026-05-31

### Breaking
- **Collapsed five Windows .bat files into one.** `start.bat`,
  `uninstall.bat`, and `setup-auto-logon.bat` are gone. `install.bat`
  is now the single entry point and takes flags:
  - `install.bat` — default install (deps + autostart)
  - `install.bat --uninstall` — remove autostart, stop running server
  - `install.bat --help` — show usage
- **Same on Linux.** `start.sh` and `uninstall.sh` are gone.
  `install.sh` takes `--uninstall` and `--linger` (the latter runs
  `sudo loginctl enable-linger $USER` so the user unit runs across
  reboots without any login).
- **Foreground / dev run is now just `python server.py`.** No more
  `start.bat` wrapper. If you wanted the visible-console behavior,
  invoke Python directly.
- **Auto-logon support removed entirely.** Auto-logon traded the
  Windows lock screen for unattended-reboot convenience, but it lets
  anyone with physical access get a logged-in desktop. That is the
  wrong trade-off for a remote-control tool, even as an opt-in. If
  you want reboot recovery without walking to the PC, sign in via
  Remote Desktop or Tailscale SSH.
- Test `tests/test_start_idempotency.py` removed — it pinned
  behaviour of the deleted `start.bat` / `start.sh`. The equivalent
  probe-and-yield logic now lives in `daemon.py` and is exercised by
  the rest of the suite.

### Changed
- README rewritten around the single-entry-point flow. Replaced the
  "Foreground dev run" subsection with a one-liner pointing to
  `python server.py`. "After a reboot" section now explains the
  honest trade-off (lock screen stays; sign in remotely if needed)
  instead of recommending auto-logon.

### Removed
- `start.bat`, `start.sh`, `uninstall.bat`, `uninstall.sh`,
  `setup-auto-logon.bat`.

## [0.3.1] — 2026-05-30

### Fixed
- **`shell_exec` no longer blocks the asyncio event loop.** The synchronous
  `subprocess.Popen` body now runs in a worker thread via `asyncio.to_thread`,
  so `/health` and other tool calls keep being served while a long shell
  command is in flight. Previously a 60s shell command starved `/health` for
  60s; the supervising daemon would interpret that as a dead server and kill
  it mid-command.
- **`start_process` no longer leaks temp files forever.** When the spawned
  process is observed to be dead — either by the next `get_process_output`
  call or by the startup reaper `_gc_dead_procs()` — its registry entry is
  dropped and its `.out.txt` / `.err.txt` files in `%TEMP%` are removed.
  Previously every background process that the user did not explicitly kill
  left orphan files that nothing cleaned up.
- **`_save_procs` writes atomically** (write to `.tmp`, then `os.replace`).
  A power loss between the write and the replace now leaves the previous
  registry intact instead of half-written JSON that `_load_procs` discards
  on the next start.
- **Rebind loop exponential backoff.** A permanent `OSError` on `accept()`
  no longer spins at 2 seconds forever flooding the log; the schedule walks
  2→5→10→30→60 seconds and resets after 5 minutes of uptime, matching
  `daemon.py`.
- **Replaced `datetime.utcnow()`** with `datetime.now(timezone.utc)`.
  `utcnow()` is deprecated in Python 3.12 and scheduled for removal; with
  the old code the server would have stopped starting after a Python
  upgrade somewhere in the 3.14/3.15 window.
- **Replaced `wmic`** in `uninstall.bat` with a PowerShell `Get-CimInstance`
  query. `wmic` is deprecated in Windows 11 and is being phased out of
  optional features; the new form survives that removal.
- **`install.sh` systemd unit hardened:**
  - Removed `After=network-online.target` (user units do not reliably trigger
    that target; the server already self-heals network changes via the
    rebind loop, so the dependency was wrong and caused boot delays).
  - Added `StartLimitIntervalSec=60` / `StartLimitBurst=10` so a brief
    failure storm during boot does not put the unit into a permanent
    failed state.
  - Added `SyslogIdentifier=remote-pc-mcp` for cleaner `journalctl` output.

## [0.3.0] — 2026-05-30

### Breaking
- **Launcher split into single-purpose scripts.** `start.bat` / `start.sh` are
  now run-only — no autostart side effects, no restart loop. To install
  autostart, run the new `install.bat` (Windows) or `install.sh` (Linux); to
  remove, run `uninstall.bat` / `uninstall.sh`. Existing Startup-folder
  shortcuts from earlier 0.2.x setups (pointing at `bg.vbs` → `start.bat`)
  should be removed and replaced with `install.bat`.

### Added
- `daemon.py` — Python supervisor. Probes `/health` and exits cleanly if the
  server is already up; otherwise spawns `server.py` and restarts on crash
  with exponential backoff (5/10/20/40/60s, capped, resets after 5 minutes of
  uptime). Logs to its own `daemon.log` so it never contends with `server.log`
  for write locks.
- `install.bat` / `install.sh` — idempotent installer. Windows drops a Startup
  shortcut to `pythonw daemon.py` (natively windowless — no VBS wrapper).
  Linux writes a systemd user unit at
  `~/.config/systemd/user/remote-pc-mcp.service` and enables it. Rerunning
  refreshes the install after moving the repo (self-healing for the stale
  shortcut / unit problem).
- `uninstall.bat` / `uninstall.sh` — clean removal of the autostart entry
  plus stop of any running server/daemon.
- `_logging.py` — one `dictConfig` wires `remote-pc-mcp`, `uvicorn`,
  `uvicorn.error`, and `uvicorn.access` through a single `RotatingFileHandler`
  on `server.log`. Replaces the brittle `sys.stdout = open(...)` redirect and
  the `pythonw.exe` string-match in `server.py`.

### Removed
- `bg.vbs` — pythonw is natively windowless, so the VBS wrapper that hid the
  cmd window is no longer needed.
- The `if sys.stdout is None …` redirect block from `server.py`. Logging is
  now configured up front via `_logging.configure()`.

## [0.2.3] — 2026-05-28

### Fixed
- Server listener becoming permanently unresponsive after a Tailscale interface
  flap. With `REMOTE_PC_MCP_HOST` set to a specific Tailscale IP, a brief loss
  of that IP from the interface (WiFi roam, NAT renegotiation, idle reconnect
  on laptops) orphans the bound socket. `accept()` then raises `OSError`,
  which previously killed the listener while the process kept running.
  Existing TCP connections survived, but no new clients could connect until
  manual restart. Now the uvicorn `Server` runs inside a `while True:
  try/except OSError` loop that logs the error, sleeps 2 seconds, and
  re-binds. The process self-heals when the interface IP returns, with no
  human in the loop.

## [0.2.2] — 2026-05-27

### Fixed
- `start.bat` / `start.sh` were not idempotent: launching one while another
  was already running (e.g. Task Scheduler at login + a manual double-click)
  killed the existing healthy server and spawned a duplicate, which then
  dueled with the original inside the auto-restart loop. The scripts now
  probe `/health` first and exit cleanly with "already running" when an
  instance is up. After a crash inside the loop, they re-probe and yield to
  any other instance that grabbed the port.

### Changed
- `start.bat` / `start.sh` honour `REMOTE_PC_MCP_PORT` instead of hardcoding
  `8765`, matching what `server.py` already reads. This also lets the new
  `tests/test_start_idempotency.py` exercise the scripts on a high port
  without touching whatever production server is running.

## [0.2.1] — 2026-05-27

### Fixed
- DNS-rebinding protection in the MCP SDK was rejecting any Host header that
  wasn't on its allowlist, which broke legitimate access via Tailscale IPs and
  LAN hostnames (`Invalid Host header` / HTTP 400 from `/mcp`). The server is
  already protected by a 256-bit bearer token compared in constant time, and
  it lives on a tailnet or LAN — DNS rebinding isn't a meaningful threat in
  that topology — so the protection is now OFF by default. Operators who want
  it can set `REMOTE_PC_MCP_ALLOWED_HOSTS` to a comma-separated allowlist and
  it will turn back on for the listed hosts.

### Added
- Regression test (`tests/test_host_header.py`) that posts to `/mcp` with a
  non-localhost Host header.

## [0.2.0] — 2026-05-27

### Breaking
- **Transport switched from SSE to streamable HTTP** (`mcp.streamable_http_app`,
  `stateless_http=True`, `json_response=True`). The client URL is now
  `http://HOST:8765/mcp` instead of `http://HOST:8765/sse`. In `.mcp.json`, set
  `"type": "http"` (not `"sse"`). This removes the entire class of
  "stale session_id" / "request before initialization complete" failures that
  hit clients after a server restart.

### Added
- `WindowsSelectorEventLoopPolicy` is set before any asyncio import so uvicorn
  no longer dies on transient Windows socket errors.
- Resource caps on every tool that touches the host: shell timeout, read/write
  size, download size. Defaults are conservative; all overridable via env
  (`REMOTE_PC_MCP_MAX_SHELL_TIMEOUT`, `…_MAX_READ_BYTES`,
  `…_MAX_WRITE_BYTES`, `…_MAX_DOWNLOAD_BYTES`).
- Rotating log file (`server.log`, 10 MB × 5 backups).
- Persistent process registry (`.state/procs.json`) so PIDs survive restarts.
- `start.bat` and `start.sh` auto-restart on non-zero exit.
- Audit log entries for `shell_exec`, `start_process`, `kill_process` (command
  truncated to 200 chars; never the token).
- `take_screenshot` and the pyautogui-driven tools now document the interactive
  desktop session requirement.
- `__version__` and a `/health` payload that includes it.
- Test suite under `tests/` covering health, auth, every tool, and survival of
  a server restart.

### Changed
- Token comparison uses `secrets.compare_digest` (constant-time, was `!=`).
- Tool error messages are run through `_safe_error` to strip absolute paths,
  the home directory, and the token before being returned to the client.
- README rewritten around the new transport and the resource-cap env vars.

### Removed
- The short-lived SSE session-resilience middleware. It was a workaround for
  the transport choice, and the transport switch removes the need for it.
