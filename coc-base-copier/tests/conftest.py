"""Shared test fixtures for the base-copier.

Adds the project root to sys.path so ``import src.copy...`` works without an
install step, and provides a synthetic village screenshot + a fake vision
transport so the full pipeline can be tested with no network / no API key.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]  # coc-base-copier/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.copy.grid import Grid, MapCorners  # noqa: E402
from src.copy.vision import VisionTransport  # noqa: E402


def make_diamond_image(
    width: int = 1920, height: int = 1080
) -> tuple[np.ndarray, MapCorners]:
    """A black frame with a white isometric (~2:1) diamond, plus its corners."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    cx, cy = width // 2, height // 2
    half_w, half_h = 800, 400
    top = (cx, cy - half_h)
    right = (cx + half_w, cy)
    bottom = (cx, cy + half_h)
    left = (cx - half_w, cy)
    pts = np.array([top, right, bottom, left], dtype=np.int32)
    cv2.fillConvexPoly(img, pts, (255, 255, 255))
    corners = MapCorners(
        top=(float(top[0]), float(top[1])),
        right=(float(right[0]), float(right[1])),
        bottom=(float(bottom[0]), float(bottom[1])),
        left=(float(left[0]), float(left[1])),
    )
    return img, corners


@pytest.fixture
def diamond() -> tuple[np.ndarray, MapCorners]:
    return make_diamond_image()


@pytest.fixture
def grid(diamond) -> Grid:
    image, corners = diamond
    return Grid.from_corners(corners, image)


@pytest.fixture
def screenshot_path(tmp_path, diamond) -> str:
    image, _corners = diamond
    path = tmp_path / "village.png"
    cv2.imwrite(str(path), image)
    return str(path)


class FakeTransport(VisionTransport):
    """Returns canned JSON, ignoring the image. Optionally varies per attempt."""

    def __init__(self, payloads: list[dict] | dict):
        # Accept a single payload (reused every call) or a list (one per attempt).
        self._payloads = payloads if isinstance(payloads, list) else [payloads]
        self.calls = 0

    def complete(self, *, image_png: bytes, prompt: str, system: str) -> str:
        idx = min(self.calls, len(self._payloads) - 1)
        self.calls += 1
        return json.dumps(self._payloads[idx])


def detection(grid: Grid, tile_xy, type_, category, level=10, conf=0.95, rotation=0):
    """Build one raw detection dict whose px/py map to the given tile."""
    px, py = grid.tile_to_pixel(tile_xy[0], tile_xy[1])
    return {
        "type": type_,
        "category": category,
        "level": level,
        "px": int(round(px)),
        "py": int(round(py)),
        "rotation": rotation,
        "confidence": conf,
    }
