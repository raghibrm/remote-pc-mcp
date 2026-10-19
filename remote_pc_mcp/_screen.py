"""Screen space: the coordinates take_screenshot's image and the mouse tools share.

A vision model sees a screenshot shrunk to fit its image limits, and the
coordinates it answers with are in that shrunken image. So the server shrinks
the image itself, by a known factor, and the mouse tools map image pixels back
to the desktop. The factor depends only on the desktop's current size and the
two limits, so nothing is remembered between calls.

No display access here, so this module is testable anywhere.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Desktop:
    """The whole desktop, every monitor, in the coordinates the mouse moves in.

    left and top are zero or negative: a monitor left of or above the primary
    one has negative coordinates.
    """

    left: int
    top: int
    width: int
    height: int


def scale_for(desktop: Desktop, max_edge: int, max_pixels: int) -> float:
    """Image pixels per desktop pixel, at most 1. A limit of 0 is ignored."""
    scale = 1.0
    if max_edge > 0:
        scale = min(scale, max_edge / max(desktop.width, desktop.height))
    if max_pixels > 0:
        scale = min(scale, (max_pixels / (desktop.width * desktop.height)) ** 0.5)
    return scale


def image_size(desktop: Desktop, scale: float) -> tuple[int, int]:
    return max(1, round(desktop.width * scale)), max(1, round(desktop.height * scale))


def to_desktop(x: int, y: int, desktop: Desktop, scale: float) -> tuple[int, int]:
    """Map image pixel (x, y) to the centre of the desktop area it shows."""
    width, height = image_size(desktop, scale)
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError(f"({x}, {y}) is outside the {width}x{height} screenshot")
    dx = min(desktop.width - 1, int((x + 0.5) / scale))
    dy = min(desktop.height - 1, int((y + 0.5) / scale))
    return desktop.left + dx, desktop.top + dy
