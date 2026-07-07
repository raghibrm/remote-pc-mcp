"""
The point of the streamable-http migration: a server restart in the middle of a
client's life must NOT brick the client. Each request is self-contained, so a
fresh call after restart should just work.
"""


import httpx

from .conftest import _spawn_server, _wait_for_health


async def test_calls_work_after_restart(server, call_tool):
    r1 = await call_tool("system_info", {})
    assert "hostname" in r1

    server.proc.terminate()
    try:
        server.proc.wait(timeout=5)
    except Exception:
        server.proc.kill()
        server.proc.wait(timeout=2)

    server.proc = _spawn_server(server.port, server.token)
    _wait_for_health(server.health_url, timeout=30.0)

    r2 = await call_tool("system_info", {})
    assert "hostname" in r2


def test_health_after_restart(server):
    r = httpx.get(server.health_url, timeout=5.0)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
