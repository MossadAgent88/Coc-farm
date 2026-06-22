"""Theme-agnostic corner detection: winter (icy blue) and desert (sand) themes.

The detector must key on brightness contrast, not grass color. These build a
filled diamond in non-green palettes and assert registration still succeeds
with confidence > 0.85 (the trust threshold is 0.70 and is NOT lowered).
"""

from __future__ import annotations

import cv2
import numpy as np

from src.copy.grid import Grid, corner_confidence, detect_map_corners
from src.copy.schema import MAX_TILE


def _themed_diamond(
    bg_bgr: tuple[int, int, int], fg_bgr: tuple[int, int, int],
    width: int = 1920, height: int = 1080,
) -> np.ndarray:
    """A bright diamond (fg) over a darker surround (bg), same iso geometry as
    the default-theme fixture."""
    img = np.full((height, width, 3), bg_bgr, dtype=np.uint8)
    cx, cy = width // 2, height // 2
    pts = np.array(
        [(cx, cy - 400), (cx + 800, cy), (cx, cy + 400), (cx - 800, cy)],
        dtype=np.int32,
    )
    cv2.fillConvexPoly(img, pts, fg_bgr)
    return img


def test_winter_icy_blue_theme_detects_with_high_confidence():
    # dark navy surround, bright icy-blue playfield (BGR)
    img = _themed_diamond(bg_bgr=(60, 35, 20), fg_bgr=(245, 230, 200))
    corners = detect_map_corners(img)
    assert corner_confidence(img, corners) > 0.85
    grid = Grid.from_image(img)  # must not raise; >= 0.70 trust gate
    assert grid.confidence > 0.85
    # corners near the drawn tips (within a few px after blur)
    assert abs(corners.top[1] - 140) <= 5
    assert abs(corners.left[0] - 160) <= 5
    # and the grid maps the four pixel corners to the four tile corners
    assert grid.pixel_to_tile(*corners.top) == (0, 0)
    assert grid.pixel_to_tile(*corners.right) == (MAX_TILE, 0)
    assert grid.pixel_to_tile(*corners.bottom) == (MAX_TILE, MAX_TILE)
    assert grid.pixel_to_tile(*corners.left) == (0, MAX_TILE)


def test_desert_sand_theme_detects_with_high_confidence():
    # darker sand surround, lighter sand playfield
    img = _themed_diamond(bg_bgr=(90, 120, 150), fg_bgr=(170, 205, 235))
    grid = Grid.from_image(img)
    assert grid.confidence > 0.85


def test_dark_diamond_on_bright_surround_still_detected():
    # inverted contrast (diamond darker than surround) -> otsu_inv mask path
    img = _themed_diamond(bg_bgr=(235, 235, 235), fg_bgr=(70, 70, 70))
    grid = Grid.from_image(img)
    assert grid.confidence > 0.85
