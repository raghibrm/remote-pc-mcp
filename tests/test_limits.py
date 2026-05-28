"""
Conftest lowers caps to 1 MB for read/write and 10s for shell. We verify each
cap rejects oversized input cleanly instead of OOM'ing the server.
"""


async def test_read_rejects_oversize(call_tool, tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB > 1 MB cap
    r = await call_tool("read_file", {"path": str(big)})
    assert "error" in r
    assert "too large" in r["error"].lower()


async def test_write_rejects_oversize(call_tool, tmp_path):
    target = tmp_path / "big.txt"
    payload = "x" * (2 * 1024 * 1024)  # 2 MB > 1 MB cap
    r = await call_tool("write_file", {"path": str(target), "content": payload})
    assert "error" in r
    assert "too large" in r["error"].lower()


async def test_write_small_succeeds(call_tool, tmp_path):
    target = tmp_path / "small.txt"
    r = await call_tool(
        "write_file", {"path": str(target), "content": "small content under cap"}
    )
    assert r["success"] is True
