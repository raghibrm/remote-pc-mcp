# Setting up remote-pc-mcp

Do steps 1 to 4 on the machine to be controlled, and step 5 on the machine the agent runs on.

## 1. Install

Pick one.

- **pip.** `pip install remote-pc-mcp`, then start `remote-pc-mcp` (foreground) or `remote-pc-mcp-daemon` (restarts it after a crash). The server reads `.env` from the folder it starts in, or from `REMOTE_PC_MCP_HOME` when that is set. A pip install does not start on sign-in.
- **Clone with autostart.** Clone https://github.com/raghibrm/remote-pc-mcp and run `install.bat` on Windows or `./install.sh` on Linux. It installs dependencies, starts the server on every sign-in, and restarts it after a crash. On Linux, `./install.sh --linger` keeps it running without a sign-in.

## 2. Set a token

Put a long random token in `.env` as `REMOTE_PC_MCP_TOKEN=...`. Generate one with `python -c "import secrets; print(secrets.token_hex(32))"`. Anyone holding it can run any command on the machine, so treat it like a password.

## 3. Keep it private

Set `REMOTE_PC_MCP_HOST` in `.env` to the machine's Tailscale IP, or run the server only on a network where every device is trusted. Never open port 8765 to the internet without TLS and a reverse proxy. Restart the server after editing `.env`.

## 4. Check it

`curl http://localhost:8765/health` should answer `{"status":"ok", ...}`.

## 5. Connect the agent

Store the token in an environment variable on the agent's machine, then add the server to the client's MCP config. In Claude Code (`.mcp.json` in the project, or `~/.claude.json`):

```json
{
  "mcpServers": {
    "remote-pc": {
      "type": "http",
      "url": "http://HOST:8765/mcp",
      "headers": { "Authorization": "Bearer ${REMOTE_PC_MCP_TOKEN}" }
    }
  }
}
```

Replace `HOST` with the machine's IP or Tailscale name. Other clients (Claude Desktop, Cursor, Cline, Windsurf) take the same entry in their own MCP settings. A client that cannot read environment variables in its config needs the token pasted in, and that file stays on the user's machine. For several machines, add one entry per machine with its own name and token variable, then reload the client.
