# Changelog

All notable changes to this project will be documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project follows semver from 0.2.0 onward.

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
