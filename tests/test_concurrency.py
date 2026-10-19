import asyncio
import time

import httpx


async def test_slow_tools_do_not_freeze_the_server(server, call_tool):
    # system_info samples CPU for a full second. When sync tools ran on the
    # event loop, four of them took ~6.5 s back to back and /health stalled
    # for the whole time; on a worker thread they overlap.
    gaps = []
    stop = asyncio.Event()

    async def poll_health():
        async with httpx.AsyncClient(timeout=30) as http:
            while not stop.is_set():
                t0 = time.perf_counter()
                await http.get(server.health_url)
                gaps.append(time.perf_counter() - t0)
                await asyncio.sleep(0.1)

    poller = asyncio.create_task(poll_health())
    t0 = time.perf_counter()
    results = await asyncio.gather(*[call_tool("system_info") for _ in range(4)])
    wall = time.perf_counter() - t0
    stop.set()
    await poller

    assert all("cpu_percent" in r for r in results)
    assert wall < 4.0, f"4 concurrent system_info took {wall:.1f}s"
    assert max(gaps) < 1.0, f"/health stalled {max(gaps):.1f}s while tools ran"
