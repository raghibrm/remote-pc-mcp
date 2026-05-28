# Changelog

All notable changes to this project will be documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project follows semver from 0.2.0 onward.

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
