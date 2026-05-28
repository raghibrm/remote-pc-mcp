"""
Running start.bat / start.sh while a healthy server is already on the port
must be a no-op. Before v0.2.2, a second invocation killed the existing
server and started a duplicate, which then dueled with the first in an
auto-restart loop. This test pins the new behaviour: probe /health up front;
if healthy, exit 0 with 'already running'.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_START_SCRIPT = _REPO_ROOT / ("start.bat" if os.name == "nt" else "start.sh")


@pytest.mark.skipif(not _START_SCRIPT.exists(), reason="start script missing")
def test_start_script_yields_when_already_running(server):
    """server fixture already has a healthy instance on server.port."""
    env = os.environ.copy()
    env["REMOTE_PC_MCP_PORT"] = str(server.port)
    env["REMOTE_PC_MCP_TOKEN"] = server.token

    if os.name == "nt":
        cmd = ["cmd", "/c", str(_START_SCRIPT)]
    else:
        cmd = ["bash", str(_START_SCRIPT)]

    t0 = time.time()
    proc = subprocess.run(
        cmd, env=env, cwd=str(_REPO_ROOT),
        capture_output=True, text=True, timeout=120,
    )
    elapsed = time.time() - t0

    combined = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, f"start script exited non-zero: {combined}"
    assert "already running" in combined.lower(), (
        f"start script did not detect existing server. Output:\n{combined}"
    )
    assert elapsed < 60, f"start script took {elapsed:.1f}s — should exit fast"

    import httpx
    r = httpx.get(server.health_url, timeout=5.0)
    assert r.status_code == 200
    assert r.json()["version"]
