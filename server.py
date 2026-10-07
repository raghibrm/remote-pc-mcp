#!/usr/bin/env python3
"""Compatibility shim — the implementation lives in remote_pc_mcp/server.py.

Running this file from a git clone needs no pip install: the script directory
(the repo root) is already first on sys.path, so the package resolves. It also
pins REMOTE_PC_MCP_HOME to the repo root so .env, server.log, and .state stay
exactly where flat-layout checkouts (pre-0.5.0) kept them.
"""

import os
from pathlib import Path

if __name__ == "__main__":
    os.environ.setdefault("REMOTE_PC_MCP_HOME", str(Path(__file__).resolve().parent))
    from remote_pc_mcp.server import main

    main()
