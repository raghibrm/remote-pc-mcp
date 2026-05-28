# remote-pc-mcp

An MCP server that exposes a PC's capabilities — shell execution, filesystem, background processes, GPU stats, screenshots, UI control, and file transfer — to Claude Code or any MCP client over **streamable HTTP**.

Use it to give Claude Code full control over a remote machine: a gaming PC with a GPU, a home server, or any box on your network. Once configured, Claude can run commands, manage files, launch training jobs, check GPU utilisation, take screenshots, and drive the desktop — all from your main workstation.

The transport is `mcp` SDK's streamable HTTP (`stateless_http=True`), so a server restart does not break already-connected clients. Each request is self-contained — there is no in-memory session that can go stale.

## Tools

| Tool | Description |
|------|-------------|
| `shell_exec` | Run any shell command synchronously — returns stdout, stderr, exit code |
| `read_file` | Read a file as text or base64 (binary fallback) |
| `write_file` | Write text or binary content to a file |
| `list_directory` | List files and directories, optionally recursive |
| `system_info` | OS, CPU, RAM, and GPU stats (via nvidia-smi) |
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

- Python 3.11+
- Windows or Linux

## Setup

**On the machine you want to control (the remote PC):**

1. Clone this repo:

```bash
git clone https://github.com/raghibrm/remote-pc-mcp
cd remote-pc-mcp
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create your config:

```bash
cp .env.example .env
```

Edit `.env` and set a strong token:

```
REMOTE_PC_MCP_TOKEN=your-long-random-token-here
```

Generate one with:
```bash
# Windows
python -c "import secrets; print(secrets.token_hex(32))"

# Linux / macOS
openssl rand -hex 32
```

4. Start the server:

```bash
# Windows
start.bat

# Linux
chmod +x start.sh && ./start.sh
```

`start.bat` / `start.sh` restart automatically on a non-zero exit, so a one-off crash will not take the server down. Clean exit (code 0) ends the loop.

The server listens on port `8765` by default. Visit `http://HOST:8765/health` to confirm it is up.

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

For Tailscale users, use your machine's Tailscale hostname:

```json
"url": "http://gaming-pc.tail12345.ts.net:8765/mcp"
```

After saving `.mcp.json`, restart Claude Code. The tools will appear automatically.

## Security

`shell_exec` can run **any command** on the host machine. This is intentional — it's what makes the server powerful. Treat the token like a root password.

**Recommendations:**

- **Use Tailscale** (strongly recommended): bind the server to your Tailscale IP only so it's only reachable from devices on your tailnet. Set `REMOTE_PC_MCP_HOST` to your Tailscale IP (e.g. `100.x.x.x`).
- **LAN only**: if both machines are on the same local network and you trust your LAN, `0.0.0.0` with a strong token is reasonable.
- **Never expose to the public internet** without TLS and a reverse proxy (nginx, Caddy).

Tokens are compared with `secrets.compare_digest` (constant-time). Errors are passed through a sanitiser that strips absolute paths, the home directory, and the token before being returned to a client.

## Resource limits

Every tool that touches the host is bounded so a single caller cannot OOM or fill the disk. Defaults (override via env, see `.env.example`):

| Var | Default | Applies to |
|-----|---------|------------|
| `REMOTE_PC_MCP_MAX_SHELL_TIMEOUT` | 600s | `shell_exec` |
| `REMOTE_PC_MCP_MAX_READ_BYTES` | 50 MB | `read_file` |
| `REMOTE_PC_MCP_MAX_WRITE_BYTES` | 50 MB | `write_file` |
| `REMOTE_PC_MCP_MAX_DOWNLOAD_BYTES` | 2 GB | `download_file` |

## Auto-start

**Windows — run at login:**

Add a shortcut to `start.bat` in `shell:startup`, or create a Task Scheduler entry:

```
Action: Start a program
Program: pythonw
Arguments: C:\path\to\remote-pc-mcp\server.py
```

Under `pythonw.exe` there is no console; the server redirects stdout/stderr to `server.log` automatically.

**Linux — systemd:**

```ini
[Unit]
Description=remote-pc-mcp

[Service]
ExecStart=/usr/bin/python /path/to/remote-pc-mcp/server.py
WorkingDirectory=/path/to/remote-pc-mcp
EnvironmentFile=/path/to/remote-pc-mcp/.env
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now remote-pc-mcp
```

## Tests

A self-contained test suite lives under `tests/`. It launches its own isolated server on a high port with an ephemeral token, exercises every tool, and verifies that a mid-run server restart does not lock the client out.

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

The tests do not touch the production server you started with `start.bat` — they spin up their own instance and tear it down.

## Notes on UI-driving tools

`take_screenshot`, `click`, `move_mouse`, `type_text`, `press_key`, and `scroll` require an **interactive desktop session**. On Windows that means a user is logged in and the screen is unlocked; a service running under Session 0 cannot reach the desktop. On Linux you need `scrot`, `gnome-screenshot`, or ImageMagick's `import` installed for screenshots — `sudo apt install scrot` is the easiest.

## License

MIT
