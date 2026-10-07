#!/usr/bin/env python3
"""Compatibility shim — the implementation lives in remote_pc_mcp/daemon.py.

The install scripts' Startup shortcut and systemd unit point here, so existing
deployments keep working across a git pull. Pins REMOTE_PC_MCP_HOME to the
repo root so daemon.log and the spawned server's files stay where flat-layout
checkouts (pre-0.5.0) kept them.
"""

import os
import sys
from pathlib import Path

if __name__ == "__main__":
    os.environ.setdefault("REMOTE_PC_MCP_HOME", str(Path(__file__).resolve().parent))
    from remote_pc_mcp.daemon import main

    sys.exit(main())
