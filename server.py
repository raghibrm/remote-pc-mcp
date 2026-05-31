#!/usr/bin/env python3
"""
remote-pc-mcp — expose a PC's capabilities as MCP tools over streamable HTTP.

Tools: shell_exec, read_file, write_file, list_directory, system_info,
       start_process, get_process_output, kill_process, download_file,
       take_screenshot, click, move_mouse, type_text, press_key, scroll.
"""

# Set Windows event loop policy before any other asyncio import. ProactorEventLoop
# crashes uvicorn on certain transient socket errors; SelectorEventLoop is stable.
import platform
import sys

if platform.system() == "Windows":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from pathlib import Path

import base64
import json
import os
import secrets
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from typing import Optional

import _logging

_logging.configure()

import httpx
import psutil
import pyautogui
import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

__version__ = "0.3.0"

pyautogui.FAILSAFE = False  # disable corner-hit abort; we're driving remotely
load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────

_TOKEN = os.environ.get("REMOTE_PC_MCP_TOKEN", "")
_HOST = os.getenv("REMOTE_PC_MCP_HOST", "0.0.0.0")
_PORT = int(os.getenv("REMOTE_PC_MCP_PORT", "8765"))

# Resource caps. Override via env when a host needs different limits.
_MAX_SHELL_TIMEOUT = int(os.getenv("REMOTE_PC_MCP_MAX_SHELL_TIMEOUT", "600"))
_MAX_READ_BYTES = int(os.getenv("REMOTE_PC_MCP_MAX_READ_BYTES", str(50 * 1024 * 1024)))
_MAX_WRITE_BYTES = int(os.getenv("REMOTE_PC_MCP_MAX_WRITE_BYTES", str(50 * 1024 * 1024)))
_MAX_DOWNLOAD_BYTES = int(os.getenv("REMOTE_PC_MCP_MAX_DOWNLOAD_BYTES", str(2 * 1024**3)))

IS_WINDOWS = platform.system() == "Windows"
_HERE = Path(__file__).parent
_STATE_DIR = _HERE / ".state"
_STATE_DIR.mkdir(exist_ok=True)
_PROCS_FILE = _STATE_DIR / "procs.json"

# ── Logging ────────────────────────────────────────────────────────────────

logger = _logging.get_logger()


# ── Error sanitization ─────────────────────────────────────────────────────


def _build_redactions() -> list[tuple[str, str]]:
    r = [(str(Path.home()), "~"), (str(_HERE), "<server-dir>")]
    if _TOKEN:
        r.append((_TOKEN, "<token>"))
    return r


_REDACTIONS = _build_redactions()


def _safe_msg(msg: str) -> str:
    for src, dst in _REDACTIONS:
        if src:
            msg = msg.replace(src, dst)
    return msg[:500]


def _safe_error(e: Exception) -> str:
    return _safe_msg(f"{type(e).__name__}: {e}")


# ── Process registry (persists across restarts) ────────────────────────────

_procs_lock = threading.Lock()


def _load_procs() -> dict[int, dict]:
    try:
        return {int(k): v for k, v in json.loads(_PROCS_FILE.read_text()).items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_procs() -> None:
    try:
        _PROCS_FILE.write_text(json.dumps({str(k): v for k, v in _procs.items()}))
    except Exception as e:
        logger.error("Failed to persist process registry: %s", _safe_error(e))


_procs: dict[int, dict] = _load_procs()


# ── MCP server (stateless streamable HTTP) ─────────────────────────────────
#
# stateless_http=True means each request is self-contained: no in-memory
# session_id cache to go stale on restart. json_response=True means responses
# are single JSON payloads (not SSE event streams), so a client that POSTs and
# walks away cannot leave a zombie stream behind. This is the fix for the
# class of bugs where a server restart bricks the client.
#
# DNS-rebinding protection in the SDK rejects any Host header not in its
# allowlist, which breaks legitimate access via Tailscale IPs and LAN hostnames.
# This server is already protected by a 256-bit bearer token (constant-time
# compared); DNS rebinding is the wrong threat model on a tailnet/LAN. We
# default the protection OFF and let operators opt in by setting
# REMOTE_PC_MCP_ALLOWED_HOSTS to a comma-separated list when they want it.

_ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("REMOTE_PC_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()
]
_TRANSPORT_SECURITY = TransportSecuritySettings(
    enable_dns_rebinding_protection=bool(_ALLOWED_HOSTS),
    allowed_hosts=_ALLOWED_HOSTS,
    allowed_origins=_ALLOWED_HOSTS,
)

mcp = FastMCP(
    "remote-pc-mcp",
    stateless_http=True,
    json_response=True,
    transport_security=_TRANSPORT_SECURITY,
)


# ── Tools ───────────────────────────────────────────────────────────────────


@mcp.tool()
def shell_exec(
    command: str,
    timeout: int = 30,
    working_dir: Optional[str] = None,
) -> dict:
    """Run a shell command synchronously. Returns stdout, stderr, exit_code.

    timeout is capped at REMOTE_PC_MCP_MAX_SHELL_TIMEOUT (default 600s).
    """
    capped_timeout = min(max(1, timeout), _MAX_SHELL_TIMEOUT)
    audit_cmd = command if len(command) <= 200 else command[:200] + "..."
    logger.info("shell_exec timeout=%d cwd=%s cmd=%r", capped_timeout, working_dir, audit_cmd)
    proc = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=working_dir,
    )
    try:
        stdout, stderr = proc.communicate(timeout=capped_timeout)
        return {"stdout": stdout, "stderr": stderr, "exit_code": proc.returncode, "timed_out": False}
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc.pid)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        return {"stdout": "", "stderr": "Timed out", "exit_code": -1, "timed_out": True}
    except Exception as e:
        _kill_process_tree(proc.pid)
        return {"stdout": "", "stderr": _safe_error(e), "exit_code": -1, "timed_out": False}


def _kill_process_tree(pid: int) -> None:
    """Kill a process and all of its children. shell=True on Windows spawns
    cmd.exe which spawns the real command; killing only the parent leaves the
    grandchild alive."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    for child in parent.children(recursive=True):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    try:
        parent.kill()
    except psutil.NoSuchProcess:
        pass


@mcp.tool()
def read_file(path: str, encoding: str = "utf-8") -> dict:
    """Read a file as text, with base64 fallback for binary files.

    Files larger than REMOTE_PC_MCP_MAX_READ_BYTES (default 50 MB) are rejected.
    """
    try:
        p = Path(path)
        if not p.exists():
            return {"error": _safe_msg(f"Not found: {path}")}
        size = p.stat().st_size
        if size > _MAX_READ_BYTES:
            return {"error": f"File too large ({size} bytes, max {_MAX_READ_BYTES})"}
        try:
            return {"content": p.read_text(encoding=encoding), "encoding": encoding, "size": size}
        except UnicodeDecodeError:
            return {
                "content": base64.b64encode(p.read_bytes()).decode(),
                "encoding": "base64",
                "size": size,
            }
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
def write_file(
    path: str, content: str, encoding: str = "utf-8", base64_encoded: bool = False
) -> dict:
    """Write content to a file. Set base64_encoded=True for binary data.

    Content larger than REMOTE_PC_MCP_MAX_WRITE_BYTES (default 50 MB) is rejected.
    """
    try:
        if base64_encoded:
            data = base64.b64decode(content)
            if len(data) > _MAX_WRITE_BYTES:
                return {"error": f"Content too large ({len(data)} bytes, max {_MAX_WRITE_BYTES})"}
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        else:
            encoded = content.encode(encoding)
            if len(encoded) > _MAX_WRITE_BYTES:
                return {
                    "error": f"Content too large ({len(encoded)} bytes, max {_MAX_WRITE_BYTES})"
                }
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding=encoding)
        return {"success": True, "path": str(p.resolve()), "size": p.stat().st_size}
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
def list_directory(path: str, recursive: bool = False) -> dict:
    """List files and subdirectories at a path."""
    try:
        p = Path(path)
        if not p.exists():
            return {"error": _safe_msg(f"Not found: {path}")}
        if not p.is_dir():
            return {"error": _safe_msg(f"Not a directory: {path}")}
        entries = []
        items = p.rglob("*") if recursive else p.iterdir()
        for item in sorted(items):
            try:
                st = item.stat()
                entries.append(
                    {
                        "name": item.name,
                        "path": str(item),
                        "type": "dir" if item.is_dir() else "file",
                        "size": st.st_size if item.is_file() else None,
                        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                    }
                )
            except PermissionError:
                pass
        return {"path": str(p.resolve()), "count": len(entries), "entries": entries}
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
def system_info() -> dict:
    """Return OS, CPU, RAM, and GPU (via nvidia-smi) information."""
    vm = psutil.virtual_memory()
    info = {
        "hostname": platform.node(),
        "os": platform.system(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "cpu_count_logical": psutil.cpu_count(),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "cpu_percent": psutil.cpu_percent(interval=1),
        "ram_total_gb": round(vm.total / 1e9, 2),
        "ram_used_gb": round(vm.used / 1e9, 2),
        "ram_percent": vm.percent,
        "gpu": [],
        "server_version": __version__,
    }
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().splitlines():
                parts = [x.strip() for x in line.split(",")]
                if len(parts) == 5:
                    info["gpu"].append(
                        {
                            "name": parts[0],
                            "vram_total_mb": int(parts[1]),
                            "vram_used_mb": int(parts[2]),
                            "utilization_pct": int(parts[3]),
                            "temp_c": int(parts[4]),
                        }
                    )
    except Exception:
        pass
    return info


@mcp.tool()
def start_process(command: str, working_dir: Optional[str] = None) -> dict:
    """Start a long-running command in the background. Returns PID to track it."""
    try:
        out = tempfile.NamedTemporaryFile(delete=False, suffix=".out.txt", mode="w")
        err = tempfile.NamedTemporaryFile(delete=False, suffix=".err.txt", mode="w")
        proc = subprocess.Popen(command, shell=True, stdout=out, stderr=err, cwd=working_dir)
        out.close()
        err.close()
        with _procs_lock:
            _procs[proc.pid] = {
                "pid": proc.pid,
                "command": command,
                "stdout_path": out.name,
                "stderr_path": err.name,
                "started_at": datetime.utcnow().isoformat() + "Z",
            }
            _save_procs()
        logger.info("start_process pid=%d cmd=%r", proc.pid, command[:200])
        return {"pid": proc.pid, "command": command}
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
def get_process_output(pid: int, tail_lines: int = 100) -> dict:
    """Get the latest stdout/stderr from a process started with start_process."""
    if pid not in _procs:
        return {"error": f"PID {pid} not tracked. Only processes started via start_process are tracked."}
    info = _procs[pid]

    def tail(fpath: str, n: int) -> str:
        try:
            lines = Path(fpath).read_text(errors="replace").splitlines()
            return "\n".join(lines[-n:])
        except Exception as ex:
            return f"[error reading output: {_safe_error(ex)}]"

    try:
        proc = psutil.Process(pid)
        running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        running = False

    return {
        "pid": pid,
        "running": running,
        "command": info["command"],
        "started_at": info["started_at"],
        "stdout": tail(info["stdout_path"], tail_lines),
        "stderr": tail(info["stderr_path"], tail_lines),
    }


@mcp.tool()
def kill_process(pid: int) -> dict:
    """Terminate a running process by PID."""
    try:
        p = psutil.Process(pid)
        p.terminate()
        force = False
        try:
            p.wait(timeout=5)
        except psutil.TimeoutExpired:
            p.kill()
            force = True
        with _procs_lock:
            _procs.pop(pid, None)
            _save_procs()
        logger.info("kill_process pid=%d force=%s", pid, force)
        return {"pid": pid, "killed": True, "force_killed": force}
    except psutil.NoSuchProcess:
        with _procs_lock:
            _procs.pop(pid, None)
            _save_procs()
        return {"error": f"No process with PID {pid}"}
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
async def download_file(url: str, destination: str) -> dict:
    """Download a file from a URL to a local path on this machine.

    Downloads larger than REMOTE_PC_MCP_MAX_DOWNLOAD_BYTES (default 2 GB) are aborted.
    """
    try:
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        async with httpx.AsyncClient(follow_redirects=True, timeout=600) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in resp.aiter_bytes(8192):
                        downloaded += len(chunk)
                        if downloaded > _MAX_DOWNLOAD_BYTES:
                            f.close()
                            dest.unlink(missing_ok=True)
                            return {"error": f"Download exceeded {_MAX_DOWNLOAD_BYTES} bytes; aborted"}
                        f.write(chunk)
        return {"success": True, "path": str(dest.resolve()), "size": dest.stat().st_size}
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
def take_screenshot(save_path: Optional[str] = None) -> dict:
    """Capture the primary display. Returns base64-encoded PNG.

    Requires an interactive desktop session on Windows; pyautogui-driven tools
    cannot reach a Session 0 (service-context) desktop.
    """
    if save_path is None:
        save_path = str(
            Path(tempfile.gettempdir())
            / f"screenshot_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.png"
        )

    if IS_WINDOWS:
        ps = f"""
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$s = [System.Windows.Forms.SystemInformation]::VirtualScreen
$b = New-Object System.Drawing.Bitmap($s.Width, $s.Height)
$g = [System.Drawing.Graphics]::FromImage($b)
$g.CopyFromScreen($s.Left, $s.Top, 0, 0, $b.Size)
$b.Save('{save_path}')
$g.Dispose(); $b.Dispose()
"""
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode != 0:
            return {"error": _safe_error(RuntimeError(r.stderr.strip()))}
    else:
        taken = False
        for cmd in [
            f"scrot '{save_path}'",
            f"gnome-screenshot -f '{save_path}'",
            f"import -window root '{save_path}'",
        ]:
            r = subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
            if r.returncode == 0:
                taken = True
                break
        if not taken:
            return {"error": "No screenshot tool found. On Linux install scrot: sudo apt install scrot"}

    data = base64.b64encode(Path(save_path).read_bytes()).decode()
    return {"success": True, "path": save_path, "image_base64": data, "format": "png"}


# ── UI control (pyautogui) ──────────────────────────────────────────────────
#
# These require an interactive desktop session — they cannot drive a locked
# screen or a service-context (Session 0) Windows process.


@mcp.tool()
def click(x: int, y: int, button: str = "left", clicks: int = 1) -> dict:
    """Click at screen coordinates (x, y). button = 'left' | 'right' | 'middle'."""
    try:
        pyautogui.click(x=x, y=y, clicks=clicks, button=button)
        return {"success": True, "x": x, "y": y, "button": button, "clicks": clicks}
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
def move_mouse(x: int, y: int, duration: float = 0.0) -> dict:
    """Move the cursor to (x, y). duration > 0 animates the movement."""
    try:
        pyautogui.moveTo(x=x, y=y, duration=duration)
        return {"success": True, "x": x, "y": y}
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
def type_text(text: str, interval: float = 0.0) -> dict:
    """Type a string into the focused window. interval = seconds between keys."""
    try:
        pyautogui.typewrite(text, interval=interval)
        return {"success": True, "length": len(text)}
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
def press_key(key: str) -> dict:
    """Press a single key or hotkey combo. Examples: 'enter', 'f11', 'ctrl+c', 'win+d'."""
    try:
        if "+" in key:
            pyautogui.hotkey(*[k.strip() for k in key.split("+")])
        else:
            pyautogui.press(key)
        return {"success": True, "key": key}
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
def scroll(amount: int, x: Optional[int] = None, y: Optional[int] = None) -> dict:
    """Scroll the mouse wheel. Positive = up, negative = down. Optional (x, y) anchors at coords."""
    try:
        if x is not None and y is not None:
            pyautogui.moveTo(x, y)
        pyautogui.scroll(amount)
        return {"success": True, "amount": amount}
    except Exception as e:
        return {"error": _safe_error(e)}


# ── Auth middleware ─────────────────────────────────────────────────────────


class _AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if not secrets.compare_digest(auth[7:].encode(), _TOKEN.encode()):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


# ── Starlette app (streamable HTTP transport) ──────────────────────────────


async def _health(_request: Request) -> JSONResponse:
    return JSONResponse(
        {"status": "ok", "server": "remote-pc-mcp", "version": __version__}
    )


def _build_app() -> Starlette:
    app: Starlette = mcp.streamable_http_app()
    app.routes.insert(0, Route("/health", endpoint=_health))
    app.add_middleware(_AuthMiddleware)
    return app


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not _TOKEN:
        sys.exit("ERROR: REMOTE_PC_MCP_TOKEN not set. Copy .env.example → .env and fill it in.")
    logger.info("remote-pc-mcp v%s starting on %s:%d", __version__, _HOST, _PORT)

    # log_config=None preserves our dictConfig setup; uvicorn's default would
    # overwrite it and route its loggers back to stderr (which is hollow under
    # pythonw on Python 3.10+).
    config = uvicorn.Config(
        _build_app(), host=_HOST, port=_PORT, log_config=None
    )
    # Wrap the uvicorn server so a transient OSError on accept() (e.g. when the
    # Tailscale interface briefly loses its bound IP during a network change)
    # doesn't permanently kill the listener. We log, sleep, and re-bind.
    while True:
        server = uvicorn.Server(config)
        try:
            server.run()
            break
        except OSError as e:
            logger.error("Listener died (%s); rebinding in 2s", _safe_error(e))
            time.sleep(2)
