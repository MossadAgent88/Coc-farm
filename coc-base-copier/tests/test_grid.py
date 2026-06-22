"""Grid registration: corner detection, homography, pixel->tile, sanity gate."""

from __future__ import annotations

import numpy as np
import pytest

from src.copy.grid import Grid, GridRegistrationError, corner_confidence, detect_map_corners
from src.copy.schema import MAX_TILE
from tests.conftest import make_diamond_image


def test_detect_corners_on_synthetic_diamond():
    image, corners = make_diamond_image()
    detected = detect_map_corners(image)
    # within a few px of the drawn corners
    for name in ("top", "right", "bottom", "left"):
        dx = abs(getattr(detected, name)[0] - getattr(corners, name)[0])
        dy = abs(getattr(detected, name)[1] - getattr(corners, name)[1])
        assert dx <= 4 and dy <= 4, f"{name} off by ({dx},{dy})"


def test_corner_confidence_high_for_diamond_low_for_rectangle():
    image, corners = make_diamond_image()
    assert corner_confidence(image, corners) >= 0.7

    # A full-frame bright rectangle is NOT a diamond -> low confidence.
    full = np.full((1080, 1920, 3), 255, dtype=np.uint8)
    with pytest.raises(GridRegistrationError):
        Grid.from_image(full)


def test_pixel_to_tile_corner_bindings(grid):
    # Origin convention: top->(0,0), right->(43,0), left->(0,43), bottom->(43,43)
    assert grid.pixel_to_tile(*grid.corners.top) == (0, 0)
    assert grid.pixel_to_tile(*grid.corners.right) == (MAX_TILE, 0)
    assert grid.pixel_to_tile(*grid.corners.left) == (0, MAX_TILE)
    assert grid.pixel_to_tile(*grid.corners.bottom) == (MAX_TILE, MAX_TILE)


def test_center_maps_to_middle_tile(grid):
    cx = (grid.corners.left[0] + grid.corners.right[0]) / 2
    cy = (grid.corners.top[1] + grid.corners.bottom[1]) / 2
    tx, ty = grid.pixel_to_tile(cx, cy)
    assert 21 <= tx <= 22 and 21 <= ty <= 22


def test_tile_to_pixel_round_trips(grid):
    for tile in [(0, 0), (5, 30), (22, 22), (43, 43)]:
        px, py = grid.tile_to_pixel(*tile)
        assert grid.pixel_to_tile(px, py) == tile


def test_pixel_to_tile_is_clamped(grid):
    # A pixel far outside the diamond must still clamp into 0..43.
    tx, ty = grid.pixel_to_tile(-5000, -5000)
    assert 0 <= tx <= MAX_TILE and 0 <= ty <= MAX_TILE


def test_from_image_succeeds_on_diamond():
    image, _ = make_diamond_image()
    g = Grid.from_image(image)
    assert g.confidence >= 0.7
