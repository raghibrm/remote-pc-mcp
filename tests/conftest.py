"""
Pytest fixtures: launch an isolated remote-pc-mcp server in a subprocess on a
high port with a fresh token, expose helpers for HTTP and MCP-client probes,
tear the server down at session end.

Tests do not share state with whatever production server the user has running.
"""

from __future__ import annotations

import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVER_PY = _REPO_ROOT / "server.py"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_health(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code == 200 and r.json().get("status") == "ok":
                return
        except Exception as e:
            last_err = e
        time.sleep(0.2)
    raise RuntimeError(f"server at {url} never became healthy: {last_err}")


class ServerHandle:
    def __init__(self, port: int, token: str, proc: subprocess.Popen):
        self.port = port
        self.token = token
        self.proc = proc
        self.base_url = f"http://127.0.0.1:{port}"
        self.mcp_url = f"{self.base_url}/mcp"
        self.health_url = f"{self.base_url}/health"

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def stop(self) -> None:
        if self.proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
            self.proc.wait(timeout=2)


def _spawn_server(port: int, token: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["REMOTE_PC_MCP_TOKEN"] = token
    env["REMOTE_PC_MCP_HOST"] = "127.0.0.1"
    env["REMOTE_PC_MCP_PORT"] = str(port)
    # Smaller caps speed up over-limit tests.
    env["REMOTE_PC_MCP_MAX_READ_BYTES"] = str(1 * 1024 * 1024)
    env["REMOTE_PC_MCP_MAX_WRITE_BYTES"] = str(1 * 1024 * 1024)
    env["REMOTE_PC_MCP_MAX_SHELL_TIMEOUT"] = "10"

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    return subprocess.Popen(
        [sys.executable, str(_SERVER_PY)],
        cwd=str(_REPO_ROOT),
        env=env,
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture(scope="session")
def server() -> ServerHandle:
    port = _free_port()
    token = secrets.token_hex(16)
    proc = _spawn_server(port, token)
    handle = ServerHandle(port, token, proc)
    try:
        _wait_for_health(handle.health_url, timeout=30.0)
    except Exception:
        handle.stop()
        raise
    yield handle
    handle.stop()


@pytest.fixture
def client(server: ServerHandle) -> httpx.Client:
    with httpx.Client(base_url=server.base_url, headers=server.auth_headers(), timeout=30.0) as c:
        yield c


async def _call_tool(server: ServerHandle, name: str, args: dict) -> dict:
    """Open a fresh streamable-http MCP session, call one tool, return the parsed result.

    Because the server is stateless, opening a session per call is cheap and is
    also the most realistic way to verify the stateless transport works.
    """
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    http_client = httpx.AsyncClient(headers=server.auth_headers(), timeout=30.0)
    async with streamable_http_client(server.mcp_url, http_client=http_client) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, args)
            if result.structuredContent is not None:
                return result.structuredContent
            import json
            for item in result.content:
                text = getattr(item, "text", None)
                if text:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return {"_text": text}
            return {}


@pytest.fixture
def call_tool(server: ServerHandle):
    async def _go(name: str, args: dict | None = None) -> dict:
        return await _call_tool(server, name, args or {})

    return _go
