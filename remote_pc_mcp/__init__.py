"""remote-pc-mcp — expose a PC's capabilities as MCP tools over streamable HTTP."""

import os
from pathlib import Path

__version__ = "0.5.0"


def app_dir() -> Path:
    """Directory for this server's .env, logs, and .state.

    REMOTE_PC_MCP_HOME when set (the root shims set it to the repo root, so a
    git clone keeps today's file locations exactly), else the working
    directory — which the Startup shortcut and the systemd unit both pin to
    the install directory.
    """
    return Path(os.environ.get("REMOTE_PC_MCP_HOME") or Path.cwd())
