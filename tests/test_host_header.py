"""
DNS-rebinding protection in the MCP SDK rejects any Host header not on its
allowlist. v0.2.0 hit this in production: main PC reached gaming-pc by its
Tailscale IP and the streamable_http endpoint returned 400 "Invalid Host
header". v0.2.1 turns the protection off by default so tailnet / LAN access
works; this test pins that behaviour.
"""

import httpx


def test_mcp_accepts_non_localhost_host_header(server):
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    r = httpx.post(
        server.mcp_url,
        json=body,
        headers={
            **server.auth_headers(),
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Host": "gaming-pc.example.ts.net:8765",
        },
        timeout=5.0,
    )
    assert r.status_code != 400, f"DNS-rebinding rejected legit host: {r.text}"
    assert r.status_code != 401  # auth was correct
