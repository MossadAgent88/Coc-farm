"""Pixel -> tile registration.

Detects the 4 corners of the village diamond (the white map border) with
OpenCV, builds a homography to the 44x44 grid, and exposes
``pixel_to_tile(x, y) -> (tile_x, tile_y)``.

Mirrors ``cocbot/vision.py`` conventions: cv2 + numpy + loguru, pure functions,
tuned for 1920x1080 BGR LDPlayer screenshots (but tolerant of other sizes --
registration is geometric, not pixel-constant).

Origin convention (see docs/layout-schema.md section 1):
    top corner    -> grid (0, 0)
    right corner  -> grid (GRID_SIZE, 0)
    bottom corner -> grid (GRID_SIZE, GRID_SIZE)
    left corner   -> grid (0, GRID_SIZE)
The homography maps pixels into a continuous [0, GRID_SIZE] grid space; the
tile index is ``floor`` of that, clamped to 0..GRID_SIZE-1.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

try:  # loguru matches the rest of the repo; degrade gracefully if absent.
    from loguru import logger
except Exception:  # pragma: no cover - logging is non-essential
    import logging

    logger = logging.getLogger("coc.copy.grid")

from src.copy.schema import GRID_SIZE, MAX_TILE


class GridRegistrationError(RuntimeError):
    """Raised when the map corners cannot be detected or fail sanity checks."""


@dataclass(frozen=True)
class MapCorners:
    """The four diamond corners in pixel space."""

    top: tuple[float, float]
    right: tuple[float, float]
    bottom: tuple[float, float]
    left: tuple[float, float]

    def as_array(self) -> np.ndarray:
        """Ordered top, right, bottom, left as float32 (N,2) for cv2."""
        return np.array(
            [self.top, self.right, self.bottom, self.left], dtype=np.float32
        )

    def to_dict(self) -> dict[str, tuple[float, float]]:
        return {
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "left": self.left,
        }


# Grid-space targets for (top, right, bottom, left). Continuous, not tile index.
_GRID_TARGETS = np.array(
    [
        [0.0, 0.0],               # top
        [GRID_SIZE, 0.0],         # right
        [GRID_SIZE, GRID_SIZE],   # bottom
        [0.0, GRID_SIZE],         # left
    ],
    dtype=np.float32,
)


def _order_quad_corners(pts: np.ndarray) -> MapCorners:
    """Label 4 arbitrary points as top/right/bottom/left of a diamond.

    The CoC map is an isometric diamond whose four vertices are the topmost,
    bottommost, leftmost and rightmost points of the quad -- so we label by the
    axis extremes directly (robust to the diamond being wider than it is tall,
    unlike an x+y / x-y heuristic which assumes a square).
    """
    pts = pts.reshape(-1, 2).astype(np.float32)
    xs, ys = pts[:, 0], pts[:, 1]
    top = pts[int(np.argmin(ys))]
    bottom = pts[int(np.argmax(ys))]
    left = pts[int(np.argmin(xs))]
    right = pts[int(np.argmax(xs))]
    return MapCorners(
        top=(float(top[0]), float(top[1])),
        right=(float(right[0]), float(right[1])),
        bottom=(float(bottom[0]), float(bottom[1])),
        left=(float(left[0]), float(left[1])),
    )


def detect_map_corners(image: np.ndarray) -> MapCorners:
    """Detect the diamond border corners via the largest 4-point contour.

    The CoC playable area is bounded by a bright grid/border. We threshold the
    bright pixels, find the largest contour, approximate it to a quadrilateral,
    and label the vertices. Raises GridRegistrationError if no usable quad is
    found.
    """
    if image is None or image.ndim != 3:
        raise GridRegistrationError("image must be an HxWx3 BGR array")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # The border is the brightest large structure. Otsu adapts to brightness.
    _thr, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Close small gaps so the border reads as one contour.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        raise GridRegistrationError("no contours found for map border")

    largest = max(contours, key=cv2.contourArea)
    peri = cv2.arcLength(largest, True)
    quad: np.ndarray | None = None
    for eps in (0.02, 0.03, 0.05, 0.08):
        approx = cv2.approxPolyDP(largest, eps * peri, True)
        if len(approx) == 4:
            quad = approx
            break
    if quad is None:
        # Fall back to the minimum-area rotated rect (always 4 pts).
        box = cv2.boxPoints(cv2.minAreaRect(largest))
        quad = box.astype(np.int32)
        logger.debug("corner detection fell back to minAreaRect")

    corners = _order_quad_corners(np.asarray(quad, dtype=np.float32))
    logger.debug(f"detected map corners: {corners.to_dict()}")
    return corners


def corner_confidence(image: np.ndarray, corners: MapCorners) -> float:
    """A 0..1 sanity score for detected corners.

    The CoC map is an isometric diamond (~2:1 wide:tall), so we do NOT require
    equal diagonals. Instead we combine:
      (a) convexity (hard gate),
      (b) "diamond-ness": a diamond fills ~half its bounding box, so the
          contour-area / bbox-area ratio should be near 0.5 (a full rectangle
          gives ~1.0 and scores 0),
      (c) aspect ratio within a plausible isometric range (~1.2..2.6),
      (d) coverage: the base fills a believable fraction of the frame.
    Returns 0.0 for anything obviously wrong so callers can gate on it.
    """
    h, w = image.shape[:2]
    poly = corners.as_array().astype(np.int32)

    # (a) convex + non-degenerate
    if not cv2.isContourConvex(poly):
        return 0.0
    area = float(cv2.contourArea(poly))
    if area <= 0:
        return 0.0

    bx, by, bw, bh = cv2.boundingRect(poly)
    bbox_area = float(bw * bh)
    if bbox_area <= 0 or bh <= 0:
        return 0.0

    # (b) diamond-ness
    ratio = area / bbox_area
    diamondness = max(0.0, 1.0 - abs(ratio - 0.5) / 0.5)

    # (c) aspect plausibility
    aspect = bw / bh
    if 1.2 <= aspect <= 2.6:
        aspect_score = 1.0
    else:
        d = min(abs(aspect - 1.2), abs(aspect - 2.6))
        aspect_score = max(0.0, 1.0 - d)

    # (d) frame coverage (0.06..0.56 of frame -> 0..1)
    coverage = area / float(w * h)
    coverage_score = max(0.0, min(1.0, (coverage - 0.06) / 0.5))

    score = diamondness * 0.5 + aspect_score * 0.25 + coverage_score * 0.25
    return round(max(0.0, min(1.0, score)), 3)


class Grid:
    """Homography-backed pixel<->tile mapping for one screenshot."""

    def __init__(self, corners: MapCorners, confidence: float) -> None:
        self.corners = corners
        self.confidence = confidence
        src = corners.as_array()
        self._H = cv2.getPerspectiveTransform(src, _GRID_TARGETS)
        self._H_inv = cv2.getPerspectiveTransform(_GRID_TARGETS, src)

    # ---- construction ----

    @classmethod
    def from_image(cls, image: np.ndarray, *, min_confidence: float = 0.7) -> "Grid":
        """Detect corners, validate, and build the grid.

        Raises GridRegistrationError if the corners look untrustworthy, so the
        caller never registers detections against a bogus grid.
        """
        corners = detect_map_corners(image)
        conf = corner_confidence(image, corners)
        if conf < min_confidence:
            raise GridRegistrationError(
                f"map corners failed sanity check (confidence={conf:.2f} "
                f"< {min_confidence:.2f}); refusing to register detections"
            )
        return cls(corners, conf)

    @classmethod
    def from_corners(cls, corners: MapCorners, image: np.ndarray) -> "Grid":
        """Build directly from known corners (tests / editor screenshots)."""
        return cls(corners, corner_confidence(image, corners))

    # ---- mapping ----

    def pixel_to_grid(self, x: float, y: float) -> tuple[float, float]:
        """Map a pixel to continuous grid coordinates in [0, GRID_SIZE]."""
        pt = np.array([[[float(x), float(y)]]], dtype=np.float32)
        out = cv2.perspectiveTransform(pt, self._H)[0][0]
        return float(out[0]), float(out[1])

    def pixel_to_tile(self, x: float, y: float) -> tuple[int, int]:
        """Map a pixel to an integer tile (clamped to 0..43)."""
        gx, gy = self.pixel_to_grid(x, y)
        tx = int(max(0, min(MAX_TILE, int(np.floor(gx)))))
        ty = int(max(0, min(MAX_TILE, int(np.floor(gy)))))
        return tx, ty

    def tile_to_pixel(self, tile_x: float, tile_y: float) -> tuple[float, float]:
        """Map a tile center back to a pixel (useful for the paster/overlay)."""
        gx, gy = tile_x + 0.5, tile_y + 0.5
        pt = np.array([[[float(gx), float(gy)]]], dtype=np.float32)
        out = cv2.perspectiveTransform(pt, self._H_inv)[0][0]
        return float(out[0]), float(out[1])
