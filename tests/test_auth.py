import httpx


def test_mcp_rejects_missing_auth(server):
    r = httpx.post(server.mcp_url, json={}, timeout=5.0)
    assert r.status_code == 401


def test_mcp_rejects_wrong_token(server):
    r = httpx.post(
        server.mcp_url,
        json={},
        headers={"Authorization": "Bearer not-the-real-token"},
        timeout=5.0,
    )
    assert r.status_code == 401


def test_mcp_rejects_wrong_scheme(server):
    r = httpx.post(
        server.mcp_url,
        json={},
        headers={"Authorization": f"Basic {server.token}"},
        timeout=5.0,
    )
    assert r.status_code == 401


def test_mcp_accepts_correct_token(server):
    r = httpx.post(
        server.mcp_url,
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={
            **server.auth_headers(),
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        timeout=5.0,
    )
    assert r.status_code != 401
