#!/usr/bin/env python3
"""
remote-pc-mcp — expose a PC's capabilities as MCP tools for Claude Code or any MCP client.

Tools: shell_exec, read_file, write_file, list_directory, system_info,
       start_process, get_process_output, kill_process, download_file, take_screenshot,
       click, move_mouse, type_text, press_key, scroll
"""

import base64
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

if sys.stdout is None or sys.stderr is None:
    _log = open(Path(__file__).with_name("server.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = _log
    sys.stderr = _log

import httpx
import psutil
import pyautogui
import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

pyautogui.FAILSAFE = False  # disable corner-hit abort; we're driving remotely

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────

_TOKEN = os.environ.get("REMOTE_PC_MCP_TOKEN", "")
_HOST  = os.getenv("REMOTE_PC_MCP_HOST", "0.0.0.0")
_PORT  = int(os.getenv("REMOTE_PC_MCP_PORT", "8765"))

IS_WINDOWS = platform.system() == "Windows"

# Background process registry: pid → {command, stdout_path, stderr_path, started_at}
_procs: dict[int, dict] = {}

# ── MCP server ──────────────────────────────────────────────────────────────

mcp = FastMCP("remote-pc-mcp")

# ── Tools ───────────────────────────────────────────────────────────────────

@mcp.tool()
def shell_exec(
    command: str,
    timeout: int = 30,
    working_dir: Optional[str] = None,
) -> dict:
    """Run a shell command synchronously. Returns stdout, stderr, exit_code."""
    try:
        r = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=working_dir,
        )
        return {"stdout": r.stdout, "stderr": r.stderr, "exit_code": r.returncode, "timed_out": False}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Timed out", "exit_code": -1, "timed_out": True}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "exit_code": -1, "timed_out": False}


@mcp.tool()
def read_file(path: str, encoding: str = "utf-8") -> dict:
    """Read a file as text, with base64 fallback for binary files."""
    try:
        p = Path(path)
        if not p.exists():
            return {"error": f"Not found: {path}"}
        try:
            return {"content": p.read_text(encoding=encoding), "encoding": encoding, "size": p.stat().st_size}
        except UnicodeDecodeError:
            return {"content": base64.b64encode(p.read_bytes()).decode(), "encoding": "base64", "size": p.stat().st_size}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def write_file(path: str, content: str, encoding: str = "utf-8", base64_encoded: bool = False) -> dict:
    """Write content to a file. Set base64_encoded=True for binary data."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if base64_encoded:
            p.write_bytes(base64.b64decode(content))
        else:
            p.write_text(content, encoding=encoding)
        return {"success": True, "path": str(p.resolve()), "size": p.stat().st_size}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def list_directory(path: str, recursive: bool = False) -> dict:
    """List files and subdirectories at a path."""
    try:
        p = Path(path)
        if not p.exists():
            return {"error": f"Not found: {path}"}
        if not p.is_dir():
            return {"error": f"Not a directory: {path}"}
        entries = []
        items = p.rglob("*") if recursive else p.iterdir()
        for item in sorted(items):
            try:
                st = item.stat()
                entries.append({
                    "name": item.name,
                    "path": str(item),
                    "type": "dir" if item.is_dir() else "file",
                    "size": st.st_size if item.is_file() else None,
                    "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                })
            except PermissionError:
                pass
        return {"path": str(p.resolve()), "count": len(entries), "entries": entries}
    except Exception as e:
        return {"error": str(e)}


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
    }
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().splitlines():
                parts = [x.strip() for x in line.split(",")]
                if len(parts) == 5:
                    info["gpu"].append({
                        "name": parts[0],
                        "vram_total_mb": int(parts[1]),
                        "vram_used_mb": int(parts[2]),
                        "utilization_pct": int(parts[3]),
                        "temp_c": int(parts[4]),
                    })
    except Exception:
        pass
    return info


@mcp.tool()
def start_process(command: str, working_dir: Optional[str] = None) -> dict:
    """Start a long-running command in the background. Returns PID to track it."""
    try:
        out = tempfile.NamedTemporaryFile(delete=False, suffix=".out.txt", mode="w")
        err = tempfile.NamedTemporaryFile(delete=False, suffix=".err.txt", mode="w")
        proc = subprocess.Popen(
            command, shell=True,
            stdout=out, stderr=err,
            cwd=working_dir,
        )
        out.close()
        err.close()
        _procs[proc.pid] = {
            "pid": proc.pid,
            "command": command,
            "stdout_path": out.name,
            "stderr_path": err.name,
            "started_at": datetime.utcnow().isoformat() + "Z",
        }
        return {"pid": proc.pid, "command": command}
    except Exception as e:
        return {"error": str(e)}


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
            return f"[error reading output: {ex}]"

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
        p.wait(timeout=5)
        return {"pid": pid, "killed": True}
    except psutil.NoSuchProcess:
        return {"error": f"No process with PID {pid}"}
    except psutil.TimeoutExpired:
        psutil.Process(pid).kill()
        return {"pid": pid, "killed": True, "force_killed": True}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def download_file(url: str, destination: str) -> dict:
    """Download a file from a URL to a local path on this machine."""
    try:
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(follow_redirects=True, timeout=600) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in resp.aiter_bytes(8192):
                        f.write(chunk)
        return {"success": True, "path": str(dest.resolve()), "size": dest.stat().st_size}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def take_screenshot(save_path: Optional[str] = None) -> dict:
    """Capture the primary display. Returns base64-encoded PNG."""
    if save_path is None:
        save_path = str(
            Path(tempfile.gettempdir()) / f"screenshot_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.png"
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
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return {"error": r.stderr.strip()}
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

@mcp.tool()
def click(x: int, y: int, button: str = "left", clicks: int = 1) -> dict:
    """Click at screen coordinates (x, y). button = 'left' | 'right' | 'middle'."""
    try:
        pyautogui.click(x=x, y=y, clicks=clicks, button=button)
        return {"success": True, "x": x, "y": y, "button": button, "clicks": clicks}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def move_mouse(x: int, y: int, duration: float = 0.0) -> dict:
    """Move the cursor to (x, y). duration > 0 animates the movement."""
    try:
        pyautogui.moveTo(x=x, y=y, duration=duration)
        return {"success": True, "x": x, "y": y}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def type_text(text: str, interval: float = 0.0) -> dict:
    """Type a string into the focused window. interval = seconds between keys."""
    try:
        pyautogui.typewrite(text, interval=interval)
        return {"success": True, "length": len(text)}
    except Exception as e:
        return {"error": str(e)}


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
        return {"error": str(e)}


@mcp.tool()
def scroll(amount: int, x: Optional[int] = None, y: Optional[int] = None) -> dict:
    """Scroll the mouse wheel. Positive = up, negative = down. Optional (x, y) anchors at coords."""
    try:
        if x is not None and y is not None:
            pyautogui.moveTo(x, y)
        pyautogui.scroll(amount)
        return {"success": True, "amount": amount}
    except Exception as e:
        return {"error": str(e)}


# ── Auth middleware ─────────────────────────────────────────────────────────

class _AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != _TOKEN:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


# ── Starlette app with SSE transport ────────────────────────────────────────

def _build_app() -> Starlette:
    sse = SseServerTransport("/messages/")
    server = mcp._mcp_server  # low-level Server from FastMCP

    async def handle_sse(request: Request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    app = Starlette(routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
        Route("/health", endpoint=lambda _: JSONResponse({"status": "ok", "server": "remote-pc-mcp"})),
    ])
    app.add_middleware(_AuthMiddleware)
    return app


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not _TOKEN:
        sys.exit("ERROR: REMOTE_PC_MCP_TOKEN not set. Copy .env.example → .env and fill it in.")
    print(f"remote-pc-mcp listening on {_HOST}:{_PORT}")
    uvicorn.run(_build_app(), host=_HOST, port=_PORT, log_level="info")
