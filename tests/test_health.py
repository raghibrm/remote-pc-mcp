import httpx


def test_health_returns_ok(server):
    r = httpx.get(server.health_url, timeout=5.0)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["server"] == "remote-pc-mcp"
    assert isinstance(body.get("version"), str) and body["version"]


def test_health_bypasses_auth(server):
    r = httpx.get(server.health_url, timeout=5.0)
    assert r.status_code == 200
