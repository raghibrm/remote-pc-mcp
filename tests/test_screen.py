import pytest

from remote_pc_mcp._screen import Desktop, image_size, scale_for, to_desktop

MAX_EDGE, MAX_PIXELS = 1568, 1_150_000


def test_wide_multi_monitor_desktop_is_limited_by_its_long_edge():
    # Five monitors, some left of and above the primary one.
    desktop = Desktop(-4804, -1191, 6724, 2700)
    scale = scale_for(desktop, MAX_EDGE, MAX_PIXELS)
    assert scale == pytest.approx(1568 / 6724)
    assert image_size(desktop, scale) == (1568, 630)


def test_4k_desktop_is_limited_by_its_pixel_count():
    desktop = Desktop(0, 0, 3840, 2160)
    scale = scale_for(desktop, MAX_EDGE, MAX_PIXELS)
    width, height = image_size(desktop, scale)
    assert max(width, height) <= MAX_EDGE
    assert width * height <= MAX_PIXELS * 1.001
    assert (width, height) == (1430, 804)


def test_small_desktop_is_not_enlarged():
    desktop = Desktop(0, 0, 1024, 768)
    assert scale_for(desktop, MAX_EDGE, MAX_PIXELS) == 1.0
    assert to_desktop(100, 200, desktop, 1.0) == (100, 200)


def test_zero_limits_mean_desktop_pixels():
    desktop = Desktop(-1920, 0, 5760, 2160)
    assert scale_for(desktop, 0, 0) == 1.0
    assert to_desktop(0, 0, desktop, 1.0) == (-1920, 0)


def test_image_corners_land_inside_the_desktop():
    desktop = Desktop(-4804, -1191, 6724, 2700)
    scale = scale_for(desktop, MAX_EDGE, MAX_PIXELS)
    width, height = image_size(desktop, scale)

    left, top = to_desktop(0, 0, desktop, scale)
    right, bottom = to_desktop(width - 1, height - 1, desktop, scale)

    assert desktop.left <= left < desktop.left + 5
    assert desktop.top <= top < desktop.top + 5
    assert desktop.left + desktop.width - 5 < right <= desktop.left + desktop.width - 1
    assert desktop.top + desktop.height - 5 < bottom <= desktop.top + desktop.height - 1


def test_primary_monitor_origin_maps_back_to_zero():
    # The primary monitor's top-left is desktop (0, 0); the image pixel that
    # shows it must map back to within one image pixel of it.
    desktop = Desktop(-4804, -1191, 6724, 2700)
    scale = scale_for(desktop, MAX_EDGE, MAX_PIXELS)
    x, y = round(4804 * scale), round(1191 * scale)
    dx, dy = to_desktop(x, y, desktop, scale)
    assert abs(dx) <= 1 / scale and abs(dy) <= 1 / scale


@pytest.mark.parametrize("x, y", [(-1, 0), (0, -1), (1568, 0), (0, 630)])
def test_points_outside_the_image_are_rejected(x, y):
    desktop = Desktop(-4804, -1191, 6724, 2700)
    scale = scale_for(desktop, MAX_EDGE, MAX_PIXELS)
    with pytest.raises(ValueError, match="outside the 1568x630 screenshot"):
        to_desktop(x, y, desktop, scale)
