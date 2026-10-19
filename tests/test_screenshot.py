import base64
import struct
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="checks the Windows capture path"
)


def _physical_virtual_screen() -> tuple[int, int]:
    """Size of the whole desktop in physical pixels, read DPI-aware."""
    import ctypes

    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
    return user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)


async def test_screenshot_covers_the_whole_desktop(call_tool, tmp_path):
    # On a display scaled above 100% the old capture returned only the
    # top-left part of the screen, so the image came out smaller than this.
    shot = tmp_path / "shot.png"
    try:
        r = await call_tool("take_screenshot", {"save_path": str(shot)})
        if "error" in r:
            pytest.skip(f"no interactive desktop: {r['error']}")
        png = base64.b64decode(r["image_base64"])
        width, height = struct.unpack(">II", png[16:24])
        assert (width, height) == _physical_virtual_screen()
    finally:
        shot.unlink(missing_ok=True)
