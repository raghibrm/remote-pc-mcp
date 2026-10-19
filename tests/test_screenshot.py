import asyncio
import base64
import io
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from remote_pc_mcp._screen import Desktop, image_size, scale_for

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="checks the Windows capture path"
)

# The server under test runs with the default limits.
MAX_EDGE, MAX_PIXELS = 1568, 1_150_000

# Moving the real cursor is fine on a CI runner, but on a desk it lands under
# whoever is working, so locally the input test is opt-in.
_INPUT_ALLOWED = bool(os.environ.get("CI") or os.environ.get("REMOTE_PC_MCP_TEST_INPUT"))


def _desktop() -> Desktop:
    """The whole desktop in physical pixels, read per-monitor DPI-aware like the server."""
    import ctypes

    user32 = ctypes.windll.user32
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # no-op after the first call
    return Desktop(*(user32.GetSystemMetrics(i) for i in (76, 77, 78, 79)))


def _cursor() -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


async def _screenshot(call_tool_content, path) -> tuple[bytes, dict]:
    content = await call_tool_content("take_screenshot", {"save_path": str(path)})
    texts = [c.text for c in content if getattr(c, "type", "") == "text"]
    info = json.loads(texts[0])
    if "error" in info:
        pytest.skip(f"no interactive desktop: {info['error']}")
    images = [c for c in content if getattr(c, "type", "") == "image"]
    assert len(images) == 1 and images[0].mimeType == "image/jpeg"
    return base64.b64decode(images[0].data), info


async def test_screenshot_is_the_whole_desktop_sized_for_a_model(call_tool_content, tmp_path):
    shot = tmp_path / "shot.png"
    try:
        jpeg, info = await _screenshot(call_tool_content, shot)
        desktop = _desktop()
        expected = image_size(desktop, scale_for(desktop, MAX_EDGE, MAX_PIXELS))

        assert Image.open(io.BytesIO(jpeg)).size == expected
        assert (info["width"], info["height"]) == expected
        assert info["desktop"] == {
            "left": desktop.left, "top": desktop.top,
            "width": desktop.width, "height": desktop.height,
        }
        assert "warning" not in info

        # The full-resolution file on disk covers the whole desktop. Before
        # 0.5.1 a display scaled above 100% came back as its top-left corner.
        width, height = struct.unpack(">II", shot.read_bytes()[16:24])
        assert (width, height) == (desktop.width, desktop.height)
    finally:
        shot.unlink(missing_ok=True)


async def test_click_outside_the_screenshot_is_rejected(call_tool):
    r = await call_tool("click", {"x": 100_000, "y": 0})
    assert "outside the" in r["error"]


def _last_input_tick() -> int:
    """When a person last touched the mouse or keyboard. SetCursorPos does not count."""
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return info.dwTime


def _monitor_centres() -> list[tuple[int, int]]:
    """Centre of every monitor, in the same DPI-aware desktop coordinates.

    Monitors need not fill the desktop's bounding box. Its corners can sit in a
    gap no monitor covers, where Windows moves the cursor to the nearest screen,
    so the test aims at real monitors only.
    """
    import ctypes
    from ctypes import wintypes

    _desktop()  # makes this process DPI-aware first
    centres = []
    proc = ctypes.WINFUNCTYPE(
        ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
    )

    def _collect(_monitor, _dc, rect, _data):
        r = rect.contents
        centres.append(((r.left + r.right) // 2, (r.top + r.bottom) // 2))
        return 1

    ctypes.windll.user32.EnumDisplayMonitors(None, None, proc(_collect), 0)
    return centres


@pytest.mark.skipif(not _INPUT_ALLOWED, reason="moves the real cursor; set REMOTE_PC_MCP_TEST_INPUT=1")
async def test_move_mouse_lands_where_the_screenshot_shows(call_tool):
    import ctypes

    desktop = _desktop()
    scale = scale_for(desktop, MAX_EDGE, MAX_PIXELS)
    # One image pixel covers 1/scale desktop pixels.
    tolerance = 1 / scale + 1

    before = _cursor()
    try:
        for mx, my in _monitor_centres():
            x, y = int((mx - desktop.left) * scale), int((my - desktop.top) * scale)
            # A person moving the mouse between the server's move and this read
            # would fail the check for a reason that has nothing to do with the
            # mapping, so a read with real input in between is retried.
            for _attempt in range(3):
                tick = _last_input_tick()
                r = await call_tool("move_mouse", {"x": x, "y": y})
                cx, cy = _cursor()
                if _last_input_tick() == tick:
                    break
            else:
                pytest.skip("the mouse or keyboard was in use throughout")
            assert abs(cx - mx) <= tolerance and abs(cy - my) <= tolerance, (
                f"aimed at monitor centre ({mx}, {my}) via image ({x}, {y}), "
                f"server moved to ({r['desktop_x']}, {r['desktop_y']}), cursor at ({cx}, {cy})"
            )
    finally:
        ctypes.windll.user32.SetCursorPos(*before)


async def _until(predicate, timeout=5.0):
    for _ in range(int(timeout / 0.1)):
        if predicate():
            return True
        await asyncio.sleep(0.1)
    return False


@pytest.mark.skipif(not _INPUT_ALLOWED, reason="types into a window; set REMOTE_PC_MCP_TEST_INPUT=1")
async def test_typing_and_hotkeys_reach_the_window_exactly(call_tool, tmp_path):
    # pyautogui turned "Line 2" into "LINE @", dropped Shift from ")_+{}" and
    # skipped every non-ASCII character. The test opens its own window and
    # types only once that window has focus, so nothing lands anywhere else.
    status, out = tmp_path / "status.txt", tmp_path / "out.txt"
    target = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("_type_target.py")), str(status), str(out)]
    )

    def focused():
        return status.exists() and status.read_text(encoding="utf-8") == "focused"

    def holds(expected):
        return lambda: out.exists() and out.read_text(encoding="utf-8") == expected

    try:
        if not await _until(focused, timeout=8):
            pytest.skip("the test window never got focus, so nothing was typed")
        text = "Line 2 ASCII: The quick brown fox 0123456789 !@#$%^&*()_+-=[]{};:'\",.<>/?\\|`~\ncafé naïve — done"
        assert (await call_tool("type_text", {"text": text}))["success"]
        assert await _until(holds(text)), f"window holds {out.read_text(encoding='utf-8')!r}"

        # One batch per combo: ctrl+a selects all, so the next text replaces it.
        assert focused(), "focus moved away mid-test"
        assert (await call_tool("press_key", {"key": "ctrl+a"}))["success"]
        assert (await call_tool("type_text", {"text": "replaced"}))["success"]
        assert await _until(holds("replaced")), f"window holds {out.read_text(encoding='utf-8')!r}"
    finally:
        target.kill()
