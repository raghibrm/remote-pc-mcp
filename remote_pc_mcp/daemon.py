"""Supervisor: run the server and restart with exponential backoff on crash.

Designed to be invoked via `pythonw daemon.py` (the repo-root shim) from a
Startup-folder shortcut (see install.bat / install.sh), or as the
`remote-pc-mcp-daemon` console script from a pip install. For an unsupervised
foreground run, execute the server entry point directly.

Logs to daemon.log (separate from server.log) so the supervisor's writes never
contend with the server's RotatingFileHandler for the same file.
"""

import logging
import logging.handlers
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from remote_pc_mcp import app_dir

_LOG_FILE = app_dir() / "daemon.log"

# Held for the daemon's whole life, so a second daemon (another sign-in
# firing the Startup shortcut) sees it taken and leaves instead of competing.
# The OS releases it when the process exits, however it exits.
_LOCK_FILE = app_dir() / ".state" / "daemon.lock"

# The server runs as `python -m remote_pc_mcp.server`. Prepending this
# package's parent to PYTHONPATH makes that resolve in a plain git clone
# (where nothing is pip-installed); in an installed environment the entry is
# redundant but harmless.
_PKG_PARENT = Path(__file__).resolve().parents[1]

# Backoff after a crash: walk through this schedule, capped at the last value.
# Reset to the first value after the server stays up for LONG_RUN_SECONDS.
_BACKOFF_SCHEDULE = (5, 10, 20, 40, 60)
_LONG_RUN_SECONDS = 300

# A server this daemon did not start (a manual run, or an older autostart that
# launches server.py directly) is watched instead of left alone: health is
# polled, and after this many failures in a row the daemon starts its own.
_WATCH_INTERVAL_SECONDS = 30
_WATCH_FAILURES_BEFORE_TAKEOVER = 3


def _acquire_lock():
    """Take the single-daemon lock. Returns the open file holding it, or None
    when another daemon already has it."""
    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    handle = open(_LOCK_FILE, "a+")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _watch_until_down(logger: logging.Logger) -> None:
    """Return once a server this daemon did not start stops answering."""
    failures = 0
    while failures < _WATCH_FAILURES_BEFORE_TAKEOVER:
        time.sleep(_WATCH_INTERVAL_SECONDS)
        if _server_already_up():
            failures = 0
        else:
            failures += 1
            logger.warning(
                "watched server missed a health check (%d of %d)",
                failures, _WATCH_FAILURES_BEFORE_TAKEOVER,
            )


def _server_already_up() -> bool:
    port = os.environ.get("REMOTE_PC_MCP_PORT", "8765")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2):
            return True
    except Exception:
        return False


def _configure_logging() -> logging.Logger:
    handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s daemon %(message)s")
    )
    logger = logging.getLogger("remote-pc-mcp.daemon")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger


def main() -> int:
    logger = _configure_logging()
    lock = _acquire_lock()
    if lock is None:
        logger.info("another daemon is already supervising; exiting")
        return 0
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_PKG_PARENT) + os.pathsep + env.get("PYTHONPATH", "")
    backoff_idx = 0
    try:
        if _server_already_up():
            # Exiting here used to leave that server unsupervised for good.
            logger.info("server already running without a daemon; watching its health")
            _watch_until_down(logger)
            logger.warning("watched server is down; starting one under this daemon")
        logger.info("daemon starting (server=%s -m remote_pc_mcp.server)", sys.executable)
        while True:
            started = time.monotonic()
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "remote_pc_mcp.server"], env=env
                )
            except FileNotFoundError:
                logger.error("interpreter not found at %s; exiting", sys.executable)
                return 1
            uptime = time.monotonic() - started

            if result.returncode == 0:
                logger.info("server exited cleanly after %.1fs; stopping daemon", uptime)
                return 0

            if uptime >= _LONG_RUN_SECONDS:
                backoff_idx = 0

            delay = _BACKOFF_SCHEDULE[min(backoff_idx, len(_BACKOFF_SCHEDULE) - 1)]
            logger.warning(
                "server crashed (exit=%d, uptime=%.1fs); restarting in %ds",
                result.returncode, uptime, delay,
            )
            time.sleep(delay)
            backoff_idx += 1
    except KeyboardInterrupt:
        logger.info("daemon interrupted; exiting")
        return 0


if __name__ == "__main__":
    sys.exit(main())
