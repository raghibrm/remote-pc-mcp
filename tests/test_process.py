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


async def test_kill_process_ends_the_whole_job(call_tool, tmp_path):
    # The shell starts python, which starts a grandchild. Killing only the
    # shell used to leave both running.
    import psutil

    child = tmp_path / "job.py"
    child.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    start = await call_tool("start_process", {"command": f'"{sys.executable}" "{child}"'})
    pid = start["pid"]

    descendants = []
    for _ in range(50):  # up to 10 s for the tree to appear
        descendants = psutil.Process(pid).children(recursive=True)
        if sum(p.name().lower().startswith("python") for p in descendants) >= 2:
            break
        await asyncio.sleep(0.2)
    pythons = [p for p in descendants if p.name().lower().startswith("python")]
    assert len(pythons) >= 2, f"job tree never formed: {[p.name() for p in descendants]}"

    killed = await call_tool("kill_process", {"pid": pid})
    assert killed["killed"] is True and killed["processes"] >= 3

    _, alive = psutil.wait_procs(descendants, timeout=5)
    assert alive == [], f"processes left running after kill_process: {[p.pid for p in alive]}"


async def _wait_until_finished(call_tool, pid: int, timeout: float = 15.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        out = await call_tool("get_process_output", {"pid": pid, "tail_lines": 10})
        if not out["running"]:
            return out
        assert out["exit_code"] is None
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"process {pid} still running after {timeout}s")
        await asyncio.sleep(0.2)


async def test_get_process_output_reports_exit_code(call_tool):
    # `exit N` means the same thing to cmd.exe and /bin/sh.
    ok = await call_tool("start_process", {"command": "exit 0"})
    failed = await call_tool("start_process", {"command": "exit 3"})

    assert (await _wait_until_finished(call_tool, ok["pid"]))["exit_code"] == 0
    assert (await _wait_until_finished(call_tool, failed["pid"]))["exit_code"] == 3


async def test_get_process_output_unknown_pid(call_tool):
    r = await call_tool("get_process_output", {"pid": 999999999, "tail_lines": 5})
    assert "error" in r


async def test_kill_unknown_pid(call_tool):
    r = await call_tool("kill_process", {"pid": 999999999})
    assert "error" in r
