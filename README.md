# remote-pc-mcp

Expose any PC's capabilities — shell, filesystem, background processes, system stats, screenshots, UI control, and file transfer — to Claude Code or any MCP client over **streamable HTTP**.

Drop it on any machine you want to drive remotely: a home server, a desktop, a build/CI box, a media server, a workstation, a Raspberry Pi. From a separate machine, Claude can run commands on it, manage files, launch and monitor background jobs, take screenshots, and drive the desktop UI.

The transport is the `mcp` SDK's streamable HTTP (`stateless_http=True`), so a server restart does not break already-connected clients. Each request is self-contained — there is no in-memory session to go stale.

> ⚠️ **`shell_exec` runs arbitrary commands on the host as the user that started the server.** The bearer token is a root-equivalent credential. See [Security](#security) before exposing the server.

## Tools

| Tool | Description |
|------|-------------|
| `shell_exec` | Run any shell command — returns stdout, stderr, exit code |
| `read_file` | Read a file as text or base64 (binary fallback) |
| `write_file` | Write text or binary content to a file |
| `list_directory` | List files and directories, optionally recursive |
| `system_info` | OS, CPU, RAM, and GPU stats (NVIDIA GPUs via `nvidia-smi`; absent on non-GPU hosts) |
| `start_process` | Start a long-running command in the background — returns a PID |
| `get_process_output` | Poll stdout/stderr of a background process by PID |
| `kill_process` | Terminate a process by PID |
| `download_file` | Download a URL directly to this machine |
| `take_screenshot` | Capture the primary display — returns base64-encoded PNG |
| `click` | Click at screen coordinates `(x, y)` — left / right / middle, single or multi-click |
| `move_mouse` | Move cursor to `(x, y)`, optionally animated |
| `type_text` | Type a string into the focused window |
| `press_key` | Press a single key or hotkey combo (e.g. `enter`, `f11`, `ctrl+c`, `win+d`) |
| `scroll` | Scroll the mouse wheel up or down, optionally at a specific point |

## Requirements

- Python 3.10+
- Windows 10/11, or Linux with systemd (for autostart)

## Install

On the machine you want to control:

```bash
git clone https://github.com/raghibrm/remote-pc-mcp
cd remote-pc-mcp
cp .env.example .env
```

Set a strong token in `.env`:

```
REMOTE_PC_MCP_TOKEN=your-long-random-token-here
```

Generate one:

```bash
# Windows
python -c "import secrets; print(secrets.token_hex(32))"

# Linux / macOS
openssl rand -hex 32
```

Then run the installer — **this is what sets the server up for normal use:**

```bash
# Windows
install.bat

# Linux
chmod +x install.sh uninstall.sh start.sh
./install.sh
```

That's it. The installer:

- installs Python dependencies
- registers the server to launch hidden on every login (Startup-folder shortcut on Windows, systemd user unit on Linux)
- starts it now
- supervises it with exponential backoff on crash (5→10→20→40→60 seconds, resets after 5 minutes of uptime)
- survives reboots — set once, runs forever

### Verify it's up

```bash
curl http://localhost:8765/health
# {"status":"ok","server":"remote-pc-mcp","version":"0.3.1"}
```

### When to rerun the installer

`install.bat` / `install.sh` are idempotent and self-healing. Rerun any time after:

- You **move the repo** to a different folder
- You **reinstall or upgrade Python** to a different path
- You **rebuild the machine** and want to restore autostart

For day-to-day operation you never need to think about it.

### Uninstall

```bash
# Windows
uninstall.bat

# Linux
./uninstall.sh
```

Removes the autostart entry and stops the running server + supervisor.

### Foreground dev run

If you want to see the server's output in a console without touching autostart — for debugging or a one-off test:

```bash
# Windows
start.bat

# Linux
./start.sh
```

`start.bat` / `start.sh` are **not** how you set the server up. They only run it in the foreground for a single session and have no restart loop. Use `install.bat` / `install.sh` for normal use.

## Adding to Claude Code

In your MCP client config (`.mcp.json` for Claude Code):

```json
{
  "mcpServers": {
    "remote-pc": {
      "type": "http",
      "url": "http://YOUR_PC_IP_OR_HOSTNAME:8765/mcp",
      "headers": {
        "Authorization": "Bearer your-long-random-token-here"
      }
    }
  }
}
```

For Tailscale users, the magic-DNS hostname works:

```json
"url": "http://your-pc.tail12345.ts.net:8765/mcp"
```

Restart Claude Code. The tools will appear automatically. The `"remote-pc"` key is just a label for Claude Code's UI — pick whatever name you want.

## Security

`shell_exec` runs **any command** on the host as the user that started the server. That is intentional — it is what makes the server useful for remote-driving a PC. It also means:

- **The bearer token is a root-equivalent credential.** Generate a 32-byte hex token, store it only in `.env` (which is git-ignored), and treat it like a password.
- **Never expose the server to the public internet** without TLS and a reverse proxy (nginx, Caddy, Cloudflare Tunnel).
- **Use Tailscale** (strongly recommended): bind to your Tailscale IP (set `REMOTE_PC_MCP_HOST=100.x.x.x` in `.env`) so the listener is only reachable from devices in your tailnet.
- **LAN-only deployments** with `REMOTE_PC_MCP_HOST=0.0.0.0` are reasonable if you trust every device on the LAN and have a strong token. Don't do this on an untrusted network.

The token is compared with `secrets.compare_digest` (constant-time). All error messages pass through a sanitiser that strips absolute paths, the home directory, and the token before being returned to clients.

## Configuration

All env vars are optional except `REMOTE_PC_MCP_TOKEN`.

| Var | Default | Description |
|-----|---------|-------------|
| `REMOTE_PC_MCP_TOKEN` | _(required)_ | Bearer token clients must present |
| `REMOTE_PC_MCP_HOST` | `0.0.0.0` | Bind address. Set to a Tailscale IP to restrict reach |
| `REMOTE_PC_MCP_PORT` | `8765` | Listen port |
| `REMOTE_PC_MCP_ALLOWED_HOSTS` | _(empty)_ | Comma-separated allowlist for DNS-rebinding protection. Empty disables it (default — wrong threat model on a tailnet) |
| `REMOTE_PC_MCP_MAX_SHELL_TIMEOUT` | `600` (s) | Cap on per-call `shell_exec` timeout |
| `REMOTE_PC_MCP_MAX_READ_BYTES` | 50 MB | `read_file` upper limit |
| `REMOTE_PC_MCP_MAX_WRITE_BYTES` | 50 MB | `write_file` upper limit |
| `REMOTE_PC_MCP_MAX_DOWNLOAD_BYTES` | 2 GB | `download_file` upper limit |

After changing `.env`, restart the server so the new value takes effect:

```bash
# Windows: easiest path is just re-run the installer (idempotent)
uninstall.bat && install.bat

# Linux
systemctl --user restart remote-pc-mcp
```

## Logs and troubleshooting

Two log files in the repo root, both rotated automatically:

| File | What's in it | Rotation |
|------|--------------|----------|
| `server.log` | App events + uvicorn startup/access logs | 10 MB × 5 |
| `daemon.log` | Supervisor events (crashes, restarts, backoff) | 2 MB × 3 |

**Server isn't responding?**

```bash
# Is the listener up locally?
curl http://localhost:8765/health

# What's the supervisor seeing?
tail -f daemon.log

# Linux: full journal
journalctl --user -u remote-pc-mcp -f

# Windows: is the autostart registered?
explorer shell:startup    # look for remote-pc-mcp.lnk
```

**MCP client says tools are missing after a server restart?**

The streamable HTTP transport is designed so a restart does not brick clients, but the client still has to issue a request to notice the new server. In Claude Code: invoke any tool (or use `/mcp` to reconnect). If that fails, restart Claude Code on the client side.

**Stuck process / port already in use?**

```bash
# Windows
uninstall.bat && install.bat

# Linux
./uninstall.sh && ./install.sh
```

## UI-driving tools

`take_screenshot`, `click`, `move_mouse`, `type_text`, `press_key`, and `scroll` require an **interactive desktop session**:

- **Windows**: a user must be logged in and the screen unlocked. A service running under Session 0 cannot reach the desktop. The Startup-folder install gives you exactly this — the daemon runs in your user session.
- **Linux**: needs an X11 or Wayland session. For screenshots specifically, install `scrot`, `gnome-screenshot`, or ImageMagick's `import` — `sudo apt install scrot` is the easiest.

## Development

Project layout:

| File | Purpose |
|------|---------|
| `server.py` | The MCP server — tools, auth, transport |
| `daemon.py` | Supervisor — spawns server, restarts on crash with backoff |
| `_logging.py` | Shared logging config — one handler for app + uvicorn loggers |
| `install.{bat,sh}` | Idempotent autostart installer (the normal entry point) |
| `uninstall.{bat,sh}` | Removes autostart + stops the server |
| `start.{bat,sh}` | Foreground dev run only (not used in normal operation) |

### Tests

A self-contained test suite under `tests/` launches its own isolated server on a high port with an ephemeral token, exercises every tool, and verifies that a mid-run server restart does not lock the client out. It does **not** touch the production server you have running.

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## License

MIT
