import sys


async def test_shell_exec_runs(call_tool):
    r = await call_tool("shell_exec", {"command": "echo hello"})
    assert r["exit_code"] == 0
    assert "hello" in r["stdout"]
    assert r["timed_out"] is False


async def test_shell_exec_failure_returns_nonzero(call_tool):
    r = await call_tool("shell_exec", {"command": "nonexistent_command_xyzzy"})
    assert r["exit_code"] != 0


async def test_shell_exec_timeout(call_tool):
    if sys.platform.startswith("win"):
        cmd = "ping 127.0.0.1 -n 30 > nul"
    else:
        cmd = "sleep 30"
    r = await call_tool("shell_exec", {"command": cmd, "timeout": 1})
    assert r["timed_out"] is True
    assert r["exit_code"] == -1


async def test_shell_exec_timeout_cap_enforced(call_tool):
    # conftest sets MAX_SHELL_TIMEOUT=10; request 9999 — should still cap.
    if sys.platform.startswith("win"):
        cmd = "ping 127.0.0.1 -n 30 > nul"
    else:
        cmd = "sleep 30"
    import time
    t0 = time.time()
    r = await call_tool("shell_exec", {"command": cmd, "timeout": 9999})
    elapsed = time.time() - t0
    assert r["timed_out"] is True
    assert elapsed < 20, f"timeout cap not enforced; took {elapsed:.1f}s"


async def test_system_info(call_tool):
    r = await call_tool("system_info", {})
    assert "hostname" in r
    assert "os" in r
    assert "ram_total_gb" in r
    assert "server_version" in r
    assert isinstance(r["gpu"], list)


async def test_list_directory(call_tool, tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.txt").write_text("yy")
    r = await call_tool("list_directory", {"path": str(tmp_path)})
    assert r["count"] >= 2
    names = {e["name"] for e in r["entries"]}
    assert {"a.txt", "b.txt"}.issubset(names)


async def test_list_directory_not_found(call_tool):
    r = await call_tool("list_directory", {"path": "Z:/definitely/not/here/xyzzy"})
    assert "error" in r


async def test_read_write_roundtrip(call_tool, tmp_path):
    target = tmp_path / "rw.txt"
    payload = "hello, file!"
    w = await call_tool("write_file", {"path": str(target), "content": payload})
    assert w["success"] is True
    assert w["size"] == len(payload.encode("utf-8"))
    r = await call_tool("read_file", {"path": str(target)})
    assert r["content"] == payload
    assert r["encoding"] == "utf-8"


async def test_read_file_binary_fallback(call_tool, tmp_path):
    target = tmp_path / "bin.dat"
    target.write_bytes(b"\x00\x01\x02\xff\xfe")
    r = await call_tool("read_file", {"path": str(target)})
    assert r["encoding"] == "base64"
    import base64
    assert base64.b64decode(r["content"]) == b"\x00\x01\x02\xff\xfe"


async def test_read_file_not_found(call_tool):
    r = await call_tool("read_file", {"path": "Z:/definitely/not/here.txt"})
    assert "error" in r
