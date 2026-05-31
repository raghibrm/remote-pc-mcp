# remote-pc-mcp

An MCP server that exposes a PC's capabilities — shell execution, filesystem, background processes, GPU stats, screenshots, UI control, and file transfer — to Claude Code or any MCP client over **streamable HTTP**.

Use it to give Claude Code full control over a remote machine: a gaming PC with a GPU, a home server, or any box on your network. Once installed, Claude can run commands, manage files, launch training jobs, check GPU utilisation, take screenshots, and drive the desktop — all from your main workstation.

The transport is the `mcp` SDK's streamable HTTP (`stateless_http=True`), so a server restart does not break already-connected clients. Each request is self-contained — there is no in-memory session that can go stale.

> ⚠️ **`shell_exec` runs arbitrary commands on the host as the user that started the server.** Treat the bearer token like a root password. See [Security](#security) before exposing the server.

## Tools

| Tool | Description |
|------|-------------|
| `shell_exec` | Run any shell command synchronously — returns stdout, stderr, exit code |
| `read_file` | Read a file as text or base64 (binary fallback) |
| `write_file` | Write text or binary content to a file |
| `list_directory` | List files and directories, optionally recursive |
| `system_info` | OS, CPU, RAM, and GPU stats (via `nvidia-smi`) |
| `start_process` | Start a long-running command in the background — returns a PID |
| `get_process_output` | Poll stdout/stderr of a background process by PID |
| `kill_process` | Terminate a process by PID |
| `download_file` | Download a URL directly to this machine (models, datasets, etc.) |
| `take_screenshot` | Capture the primary display — returns base64-encoded PNG |
| `click` | Click at screen coordinates `(x, y)` — left / right / middle, single or multi-click |
| `move_mouse` | Move cursor to `(x, y)`, optionally animated |
| `type_text` | Type a string into the focused window |
| `press_key` | Press a single key or hotkey combo (e.g. `enter`, `f11`, `ctrl+c`, `win+d`) |
| `scroll` | Scroll the mouse wheel up or down, optionally at a specific point |

## Requirements

- Python 3.10+
- Windows 10/11, or Linux with systemd (for autostart)

## Quick start

On the machine you want to control:

```bash
git clone https://github.com/raghibrm/remote-pc-mcp
cd remote-pc-mcp
cp .env.example .env
```

Edit `.env` and set a strong token:

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

Then either install as an autostart service (recommended), or run in the foreground.

### Install for autostart

Installs Python dependencies and registers the server to launch hidden at every login, restart automatically on crash (exponential backoff 5→60s, resets after 5 min of uptime), and survive reboots.

```bash
# Windows  — drops a Startup-folder shortcut to `pythonw daemon.py`
install.bat

# Linux  — drops a systemd user unit (~/.config/systemd/user/remote-pc-mcp.service)
chmod +x install.sh uninstall.sh start.sh
./install.sh
```

Both installers are **idempotent and self-healing** — rerun any time to refresh after moving the repo.

To remove:

```bash
# Windows
uninstall.bat

# Linux
./uninstall.sh
```

### Foreground run (development)

For a one-off run with visible output and no autostart side effects:

```bash
# Windows
start.bat

# Linux
./start.sh
```

`start.bat` / `start.sh` do not install anything; they spawn `python server.py` directly and exit when it does. No restart loop — use the autostart install for that.

### Verify it's up

```bash
curl http://localhost:8765/health
# {"status":"ok","server":"remote-pc-mcp","version":"0.3.1"}
```

## Adding to Claude Code

In your Claude Code project's `.mcp.json`:

```json
{
  "mcpServers": {
    "gaming-pc": {
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
"url": "http://gaming-pc.tail12345.ts.net:8765/mcp"
```

Restart Claude Code. The tools will appear automatically.

## Security

`shell_exec` runs **any command** on the host as the user that started the server. That is intentional — it is what makes the server useful for remote-driving a PC. It also means:

- **The bearer token is a root-equivalent credential.** Generate a 32-byte hex token, store it only in `.env` (which is git-ignored), and treat it like a password.
- **Never expose the server to the public internet** without TLS terminations and a reverse proxy (nginx, Caddy, Cloudflare Tunnel).
- **Use Tailscale** (strongly recommended): bind to your Tailscale IP (set `REMOTE_PC_MCP_HOST=100.x.x.x` in `.env`) so the listener is only reachable from devices in your tailnet.
- **LAN-only deployments** with `REMOTE_PC_MCP_HOST=0.0.0.0` are reasonable if you trust every device on the LAN and have a strong token. Don't do this on a coffee-shop network.

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

## Logs and troubleshooting

Two log files in the repo root, both rotated automatically:

| File | What's in it | Rotation |
|------|--------------|----------|
| `server.log` | App events + uvicorn startup/access logs | 10 MB × 5 |
| `daemon.log` | Supervisor events (crashes, restarts, backoff) | 2 MB × 3 |

**Server isn't responding?**

```bash
# Is the listener up?
curl http://localhost:8765/health

# What's the supervisor seeing?
tail -f daemon.log

# Linux: full journal
journalctl --user -u remote-pc-mcp -f

# Windows: is the autostart registered?
explorer shell:startup    # look for remote-pc-mcp.lnk
```

**Stuck process / port already in use?**

```bash
# Windows
uninstall.bat   # stops everything (also removes autostart — re-run install.bat after)

# Linux
./uninstall.sh
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
| `start.{bat,sh}` | Foreground dev run |
| `install.{bat,sh}` | Idempotent autostart installer |
| `uninstall.{bat,sh}` | Removes autostart + stops the server |

### Tests

A self-contained test suite under `tests/` launches its own isolated server on a high port with an ephemeral token, exercises every tool, and verifies that a mid-run server restart does not lock the client out. It does **not** touch the production server you have running.

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## License

MIT
