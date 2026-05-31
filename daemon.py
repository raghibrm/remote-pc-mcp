"""Supervisor: run server.py and restart with exponential backoff on crash.

Designed to be invoked via `pythonw daemon.py` from a Startup-folder shortcut
(see install.bat / install.sh). For a foreground run use start.bat / start.sh,
which executes server.py directly without supervision.

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

_HERE = Path(__file__).parent
_SERVER = _HERE / "server.py"
_LOG_FILE = _HERE / "daemon.log"

# Backoff after a crash: walk through this schedule, capped at the last value.
# Reset to the first value after the server stays up for LONG_RUN_SECONDS.
_BACKOFF_SCHEDULE = (5, 10, 20, 40, 60)
_LONG_RUN_SECONDS = 300


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
    if _server_already_up():
        logger.info("server already healthy on configured port; daemon exiting")
        return 0
    logger.info("daemon starting (server=%s)", _SERVER)
    backoff_idx = 0
    try:
        while True:
            started = time.monotonic()
            try:
                result = subprocess.run([sys.executable, str(_SERVER)])
            except FileNotFoundError:
                logger.error("server.py not found at %s; exiting", _SERVER)
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
