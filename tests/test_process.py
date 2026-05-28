import asyncio
import sys


async def test_start_get_kill_process(call_tool):
    if sys.platform.startswith("win"):
        cmd = "ping 127.0.0.1 -n 20 > nul"
    else:
        cmd = "sleep 20"
    start = await call_tool("start_process", {"command": cmd})
    pid = start["pid"]
    assert pid > 0

    await asyncio.sleep(0.5)

    out = await call_tool("get_process_output", {"pid": pid, "tail_lines": 10})
    assert out["pid"] == pid
    assert out["running"] is True

    killed = await call_tool("kill_process", {"pid": pid})
    assert killed["killed"] is True


async def test_get_process_output_unknown_pid(call_tool):
    r = await call_tool("get_process_output", {"pid": 999999999, "tail_lines": 5})
    assert "error" in r


async def test_kill_unknown_pid(call_tool):
    r = await call_tool("kill_process", {"pid": 999999999})
    assert "error" in r
