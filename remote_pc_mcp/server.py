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
    import ctypes

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Per-monitor DPI awareness, set before pyautogui's import asks for the
    # weaker system-wide kind (which then fails harmlessly). System-wide
    # awareness scales monitors that differ from the system DPI, and the
    # screen capture and the cursor scale them differently, so screenshots
    # and clicks disagree on those monitors. Per-monitor awareness puts both
    # in true physical pixels everywhere.
    _PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
    if not ctypes.windll.user32.SetProcessDpiAwarenessContext(_PER_MONITOR_AWARE_V2):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor v1, pre-1703
        except (AttributeError, OSError):
            pass

from pathlib import Path

import asyncio
import base64
import ctypes
import functools
import io
import json
import os
import secrets
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from remote_pc_mcp import __version__, app_dir
from remote_pc_mcp import _keys, _logging, _screen

_logging.configure()

import httpx
import psutil
import pyautogui
import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP, Image
from mcp.server.transport_security import TransportSecuritySettings
from PIL import Image as PILImage
from PIL import ImageGrab
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

pyautogui.FAILSAFE = False  # disable corner-hit abort; we're driving remotely

# .env lives in the app dir (repo root for a clone via the root shims'
# REMOTE_PC_MCP_HOME; the working directory otherwise), not wherever
# find_dotenv's frame-walk lands now that this module sits in a package.
_APP_DIR = app_dir()
load_dotenv(_APP_DIR / ".env")

# ── Config ─────────────────────────────────────────────────────────────────

_TOKEN = os.environ.get("REMOTE_PC_MCP_TOKEN", "")
_HOST = os.getenv("REMOTE_PC_MCP_HOST", "0.0.0.0")
_PORT = int(os.getenv("REMOTE_PC_MCP_PORT", "8765"))

# Resource caps. Override via env when a host needs different limits.
_MAX_SHELL_TIMEOUT = int(os.getenv("REMOTE_PC_MCP_MAX_SHELL_TIMEOUT", "600"))
_MAX_READ_BYTES = int(os.getenv("REMOTE_PC_MCP_MAX_READ_BYTES", str(50 * 1024 * 1024)))
_MAX_WRITE_BYTES = int(os.getenv("REMOTE_PC_MCP_MAX_WRITE_BYTES", str(50 * 1024 * 1024)))
_MAX_DOWNLOAD_BYTES = int(os.getenv("REMOTE_PC_MCP_MAX_DOWNLOAD_BYTES", str(2 * 1024**3)))

# Screenshot size limits, matching the Claude API's standard image limits so
# the client never shrinks the image again behind the server's back. 0 turns
# a limit off; both off means screenshots and clicks use desktop pixels.
_SCREEN_MAX_EDGE = int(os.getenv("REMOTE_PC_MCP_SCREEN_MAX_EDGE", "1568"))
_SCREEN_MAX_PIXELS = int(os.getenv("REMOTE_PC_MCP_SCREEN_MAX_PIXELS", "1150000"))

IS_WINDOWS = platform.system() == "Windows"
_STATE_DIR = _APP_DIR / ".state"
_STATE_DIR.mkdir(parents=True, exist_ok=True)
_PROCS_FILE = _STATE_DIR / "procs.json"

# ── Logging ────────────────────────────────────────────────────────────────

logger = _logging.get_logger()


# ── Error sanitization ─────────────────────────────────────────────────────


def _build_redactions() -> list[tuple[str, str]]:
    r = [(str(Path.home()), "~"), (str(_APP_DIR), "<server-dir>")]
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
    """Atomic write: serialize to <file>.tmp, then os.replace into place. A
    power loss between the write and the replace leaves the previous registry
    intact instead of half-written JSON that _load_procs would discard."""
    try:
        tmp = _PROCS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({str(k): v for k, v in _procs.items()}))
        tmp.replace(_PROCS_FILE)
    except Exception as e:
        logger.error("Failed to persist process registry: %s", _safe_error(e))


def _gc_proc(pid: int) -> None:
    """Drop a registry entry and delete its temp stdout/stderr files. Caller
    must hold _procs_lock."""
    _popens.pop(pid, None)
    info = _procs.pop(pid, None)
    if not info:
        return
    for key in ("stdout_path", "stderr_path"):
        path = info.get(key)
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass


def _gc_dead_procs() -> None:
    """Drop registry entries whose PIDs are no longer running. Idempotent."""
    with _procs_lock:
        dead = []
        for pid in list(_procs):
            try:
                p = psutil.Process(pid)
                if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                    dead.append(pid)
            except psutil.NoSuchProcess:
                dead.append(pid)
        for pid in dead:
            _gc_proc(pid)
        if dead:
            _save_procs()


_procs: dict[int, dict] = _load_procs()

# Popen handles for jobs started by this server process, kept in memory only
# so get_process_output can report an exit code. A job that outlives a server
# restart is still tracked through _procs, but its exit code is unknown.
_popens: dict[int, subprocess.Popen] = {}


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
#
# FastMCP runs a plain `def` tool on the event loop itself, so one slow call (a
# 1 s CPU sample, a 4K screenshot, a 5 s kill wait) froze every other request,
# /health included: five concurrent system_info calls held /health for 7.4 s.
# @_off_loop runs such a tool in a worker thread instead.


def _off_loop(fn):
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    return wrapper


# Off the event loop, two clients' input calls could now run at once and their
# keystrokes interleave. Each mouse or keyboard call holds this for its duration.
_ui_lock = threading.Lock()


def _shell_exec_sync(command: str, capped_timeout: int, working_dir: Optional[str]) -> dict:
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


@mcp.tool()
async def shell_exec(
    command: str,
    timeout: int = 30,
    working_dir: Optional[str] = None,
) -> dict:
    """Run a shell command. Returns stdout, stderr, exit_code.

    timeout is capped at REMOTE_PC_MCP_MAX_SHELL_TIMEOUT (default 600s). The
    blocking subprocess runs in a thread so /health and other tool calls keep
    being served while a long command is in flight.
    """
    capped_timeout = min(max(1, timeout), _MAX_SHELL_TIMEOUT)
    audit_cmd = command if len(command) <= 200 else command[:200] + "..."
    logger.info("shell_exec timeout=%d cwd=%s cmd=%r", capped_timeout, working_dir, audit_cmd)
    return await asyncio.to_thread(_shell_exec_sync, command, capped_timeout, working_dir)


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
@_off_loop
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
@_off_loop
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
@_off_loop
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
@_off_loop
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
@_off_loop
def start_process(command: str, working_dir: Optional[str] = None) -> dict:
    """Start a long-running command in the background. Returns PID to track it."""
    try:
        out = tempfile.NamedTemporaryFile(delete=False, suffix=".out.txt", mode="w")
        err = tempfile.NamedTemporaryFile(delete=False, suffix=".err.txt", mode="w")
        proc = subprocess.Popen(command, shell=True, stdout=out, stderr=err, cwd=working_dir)
        out.close()
        err.close()
        with _procs_lock:
            _popens[proc.pid] = proc
            _procs[proc.pid] = {
                "pid": proc.pid,
                "command": command,
                "stdout_path": out.name,
                "stderr_path": err.name,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            _save_procs()
        logger.info("start_process pid=%d cmd=%r", proc.pid, command[:200])
        return {"pid": proc.pid, "command": command}
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
@_off_loop
def get_process_output(pid: int, tail_lines: int = 100) -> dict:
    """Get the latest stdout/stderr from a process started with start_process.

    Reads output even after the process has exited (until the next call notices
    it's dead and the temp files are reaped). After the reap, subsequent calls
    return 'not tracked'.

    exit_code is None while the job runs, and also when the server restarted
    after starting the job, since the exit code is then unknowable.
    """
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

    popen = _popens.get(pid)
    exit_code = popen.poll() if popen is not None and not running else None

    result = {
        "pid": pid,
        "running": running,
        "exit_code": exit_code,
        "command": info["command"],
        "started_at": info["started_at"],
        "stdout": tail(info["stdout_path"], tail_lines),
        "stderr": tail(info["stderr_path"], tail_lines),
    }
    # Reap on this call: once the caller has seen the final output of a dead
    # process, drop the registry entry and the temp files so they don't leak
    # for the lifetime of the server.
    if not running:
        with _procs_lock:
            _gc_proc(pid)
            _save_procs()
    return result


@mcp.tool()
@_off_loop
def kill_process(pid: int) -> dict:
    """Terminate a process by PID.

    For a job started with start_process this ends the whole job: the shell
    and everything it launched. Killing only the shell left the real program
    running (a 12-worker job kept every core busy after a "killed" reply). Any
    other PID is ended alone, since its children (Explorer's, say) are not
    part of anything this server started.
    """
    try:
        p = psutil.Process(pid)
        procs = [p]
        if pid in _procs:
            procs = p.children(recursive=True)[::-1] + [p]
        for q in procs:
            try:
                q.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(procs, timeout=5)
        for q in alive:
            try:
                q.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(alive, timeout=5)
        force = bool(alive)
        with _procs_lock:
            _gc_proc(pid)
            _save_procs()
        logger.info("kill_process pid=%d processes=%d force=%s", pid, len(procs), force)
        return {"pid": pid, "killed": True, "processes": len(procs), "force_killed": force}
    except psutil.NoSuchProcess:
        with _procs_lock:
            _gc_proc(pid)
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


# ── Screen space ────────────────────────────────────────────────────────────
#
# take_screenshot returns the desktop shrunk to fit a vision model, and click,
# move_mouse and scroll take coordinates in that image. See _screen.py.


def _desktop() -> _screen.Desktop:
    """The desktop in the coordinates pyautogui moves in.

    On Windows this process is per-monitor DPI-aware (see the top of this
    module), so these are physical pixels, the same ones the screenshot holds.
    """
    if IS_WINDOWS:
        metric = ctypes.windll.user32.GetSystemMetrics
        SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
        return _screen.Desktop(
            metric(SM_XVIRTUALSCREEN),
            metric(SM_YVIRTUALSCREEN),
            metric(SM_CXVIRTUALSCREEN),
            metric(SM_CYVIRTUALSCREEN),
        )
    width, height = pyautogui.size()
    return _screen.Desktop(0, 0, width, height)


def _screen_scale(desktop: _screen.Desktop) -> float:
    return _screen.scale_for(desktop, _SCREEN_MAX_EDGE, _SCREEN_MAX_PIXELS)


def _to_desktop(x: int, y: int) -> tuple[int, int]:
    desktop = _desktop()
    return _screen.to_desktop(x, y, desktop, _screen_scale(desktop))


@mcp.tool(structured_output=False)
@_off_loop
def take_screenshot(save_path: Optional[str] = None, delay: float = 0.0) -> list:
    """Capture the whole desktop, every monitor, as an image sized for a vision model.

    The image is shrunk to at most REMOTE_PC_MCP_SCREEN_MAX_EDGE pixels on its
    long edge and REMOTE_PC_MCP_SCREEN_MAX_PIXELS in total (1568 and 1,150,000
    by default). click, move_mouse and scroll take x, y in this image's pixels,
    and the server maps them to the real desktop. The full-resolution PNG stays
    on this machine at the returned path.

    delay waits that many seconds first (at most 10). Apps can take a moment to
    redraw after a click or a keystroke, and a screenshot taken straight away
    can still show the old screen.

    Requires an interactive desktop session on Windows; pyautogui-driven tools
    cannot reach a Session 0 (service-context) desktop.
    """
    if delay > 0:
        time.sleep(min(delay, 10.0))
    if save_path is None:
        save_path = str(
            Path(tempfile.gettempdir())
            / f"screenshot_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.png"
        )

    if IS_WINDOWS:
        # In this per-monitor-aware process the grab covers the whole virtual
        # desktop in physical pixels, origin at _desktop()'s left and top.
        try:
            ImageGrab.grab(all_screens=True).save(save_path)
        except Exception as e:
            return {"error": _safe_error(e)}
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

    try:
        desktop = _desktop()
        scale = _screen_scale(desktop)
        width, height = _screen.image_size(desktop, scale)
        with PILImage.open(save_path) as full:
            captured = full.size
            view = full.convert("RGB").resize((width, height), PILImage.LANCZOS)
        buf = io.BytesIO()
        view.save(buf, "JPEG", quality=80)
    except Exception as e:
        return {"error": _safe_error(e)}

    info = {
        "success": True,
        "width": width,
        "height": height,
        "coordinates": "click, move_mouse and scroll take x, y in this image's pixels",
        "scale": round(scale, 4),
        "desktop": {
            "left": desktop.left,
            "top": desktop.top,
            "width": desktop.width,
            "height": desktop.height,
        },
        "path": save_path,
    }
    if captured != (desktop.width, desktop.height):
        info["warning"] = (
            f"captured {captured[0]}x{captured[1]} but the desktop is "
            f"{desktop.width}x{desktop.height}, so clicks may land off target"
        )
        logger.warning("take_screenshot size mismatch: %s", info["warning"])
    return [Image(data=buf.getvalue(), format="jpeg"), info]


# ── UI control (pyautogui) ──────────────────────────────────────────────────
#
# These require an interactive desktop session — they cannot drive a locked
# screen or a service-context (Session 0) Windows process.


@mcp.tool()
@_off_loop
def click(x: int, y: int, button: str = "left", clicks: int = 1) -> dict:
    """Click at (x, y) in take_screenshot's image. button = 'left' | 'right' | 'middle'."""
    try:
        dx, dy = _to_desktop(x, y)
        with _ui_lock:
            pyautogui.click(x=dx, y=dy, clicks=clicks, button=button)
        return {
            "success": True, "x": x, "y": y, "desktop_x": dx, "desktop_y": dy,
            "button": button, "clicks": clicks,
        }
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
@_off_loop
def move_mouse(x: int, y: int, duration: float = 0.0) -> dict:
    """Move the cursor to (x, y) in take_screenshot's image. duration > 0 animates the movement."""
    try:
        dx, dy = _to_desktop(x, y)
        with _ui_lock:
            pyautogui.moveTo(x=dx, y=dy, duration=duration)
        return {"success": True, "x": x, "y": y, "desktop_x": dx, "desktop_y": dy}
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
@_off_loop
def type_text(text: str, interval: float = 0.01) -> dict:
    """Type a string into the focused window, exactly as given. interval = seconds between characters.

    On Windows every character, including accents, dashes and emoji, is typed
    as itself (see _keys.py). interval=0 sends the whole string as one burst:
    a browser takes it whole, but Windows 11 Notepad kept 13 of 177
    characters, so the default leaves 10 ms between characters. Elsewhere
    pyautogui types it, and it skips non-ASCII characters.
    """
    try:
        with _ui_lock:
            if not IS_WINDOWS:
                pyautogui.typewrite(text, interval=interval)
            elif interval > 0:
                for ch in text:
                    _keys.send(_keys.text_events(ch))
                    time.sleep(interval)
            elif text:
                _keys.send(_keys.text_events(text))
        return {"success": True, "length": len(text)}
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
@_off_loop
def press_key(key: str) -> dict:
    """Press a single key or hotkey combo. Examples: 'enter', 'f11', 'ctrl+c', 'win+d'.

    On Windows the whole combo goes in as one batch, so no other input can
    land between ctrl going down and the key it modifies.
    """
    try:
        with _ui_lock:
            if IS_WINDOWS:
                _keys.send(_keys.combo_events(key))
            elif "+" in key:
                pyautogui.hotkey(*[k.strip() for k in key.split("+")])
            else:
                pyautogui.press(key)
        return {"success": True, "key": key}
    except Exception as e:
        return {"error": _safe_error(e)}


@mcp.tool()
@_off_loop
def scroll(amount: int, x: Optional[int] = None, y: Optional[int] = None) -> dict:
    """Scroll the mouse wheel by amount notches. Positive = up, negative = down.

    Optional (x, y) in take_screenshot's image moves the cursor there first.
    """
    # On Windows pyautogui passes the amount straight through as wheel units,
    # 120 to a notch, so scroll(-5) moved a page a few pixels. Elsewhere it
    # already counts notches.
    WHEEL_DELTA = 120
    try:
        with _ui_lock:
            if x is not None and y is not None:
                pyautogui.moveTo(*_to_desktop(x, y))
            pyautogui.scroll(amount * WHEEL_DELTA if IS_WINDOWS else amount)
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


def main() -> None:
    if not _TOKEN:
        sys.exit("ERROR: REMOTE_PC_MCP_TOKEN not set. Copy .env.example → .env and fill it in.")

    # Reap registry entries whose PIDs died while we were down. Without this,
    # background processes that the user never explicitly killed accumulate in
    # the registry across server restarts and leak their temp stdout/stderr
    # files in %TEMP%.
    _gc_dead_procs()

    logger.info("remote-pc-mcp v%s starting on %s:%d", __version__, _HOST, _PORT)

    # log_config=None preserves our dictConfig setup; uvicorn's default would
    # overwrite it and route its loggers back to stderr (which is hollow under
    # pythonw on Python 3.10+).
    config = uvicorn.Config(
        _build_app(), host=_HOST, port=_PORT, log_config=None
    )
    # Wrap the uvicorn server so a transient OSError on accept() (e.g. when the
    # Tailscale interface briefly loses its bound IP during a network change)
    # doesn't permanently kill the listener. Back off exponentially so a
    # permanent OSError (interface gone for real) doesn't spin at 2s forever
    # and flood the log; the schedule resets after a long-running success.
    _REBIND_BACKOFF = (2, 5, 10, 30, 60)
    _REBIND_LONG_RUN_SECONDS = 300
    backoff_idx = 0
    while True:
        started = time.monotonic()
        server = uvicorn.Server(config)
        try:
            server.run()
            break
        except OSError as e:
            uptime = time.monotonic() - started
            if uptime >= _REBIND_LONG_RUN_SECONDS:
                backoff_idx = 0
            delay = _REBIND_BACKOFF[min(backoff_idx, len(_REBIND_BACKOFF) - 1)]
            logger.error("Listener died (%s); rebinding in %ds", _safe_error(e), delay)
            time.sleep(delay)
            backoff_idx += 1


if __name__ == "__main__":
    main()
