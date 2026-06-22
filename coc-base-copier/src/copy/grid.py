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

import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

try:  # loguru matches the rest of the repo; degrade gracefully if absent.
    from loguru import logger
except Exception:  # pragma: no cover - logging is non-essential
    import logging

    logger = logging.getLogger("coc.copy.grid")

from src.copy.schema import GRID_SIZE, MAX_TILE

# Where corner-detection debug artifacts are written (override for tests).
_DEBUG_DIR = Path(os.environ.get("COC_GRID_DEBUG_DIR", "/tmp"))


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


def _log_brightness(gray: np.ndarray) -> None:
    logger.debug(
        f"grid: brightness mean={float(gray.mean()):.1f} std={float(gray.std()):.1f} "
        f"(very low std => preprocessing may be washing the image out)"
    )


def _auto_canny(gray: np.ndarray) -> np.ndarray:
    """Canny with thresholds auto-derived from Otsu -- no per-theme tuning."""
    high, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    high = max(1.0, float(high))
    return cv2.Canny(gray, int(0.5 * high), int(high))


def _candidate_masks(gray: np.ndarray) -> dict[str, np.ndarray]:
    """Brightness-only binarizations. Color is never used, so green grass, winter
    ice, and desert sand all reduce to the same 'bright field vs dark surround'
    problem. We try both Otsu polarities (diamond may be brighter OR darker than
    its surround) and an adaptive threshold for uneven lighting."""
    masks: dict[str, np.ndarray] = {}
    _t, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    masks["otsu"] = otsu
    masks["otsu_inv"] = cv2.bitwise_not(otsu)
    masks["adaptive"] = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, -5
    )
    return masks


def _contour_corner_candidates(
    mask: np.ndarray, frame_area: float
) -> list[MapCorners]:
    """Axis-extreme corners for every sufficiently large contour in a mask."""
    out: list[MapCorners] = []
    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    for c in contours:
        if cv2.contourArea(c) < 0.05 * frame_area:
            continue
        hull = cv2.convexHull(c).reshape(-1, 2).astype(np.float32)
        if len(hull) >= 4:
            out.append(_order_quad_corners(hull))
    return out


def _hough_corner_candidates(
    edges: np.ndarray, shape: tuple[int, ...]
) -> list[MapCorners]:
    """Fallback: hull of Hough segments whose slope matches an isometric edge.

    The diamond's four edges have slope ~ +/-0.5 (2:1 iso projection). Keeping
    only those segments rejects horizontal UI bars; the convex hull of their
    endpoints brackets the diamond. Always scored by ``corner_confidence`` so a
    bad hull simply loses to a better candidate.
    """
    h, w = shape[:2]
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180.0, threshold=60,
        minLineLength=int(0.12 * max(h, w)), maxLineGap=40,
    )
    if lines is None:
        logger.debug("grid: HoughLinesP found no segments")
        return []
    logger.debug(f"grid: HoughLinesP found {len(lines)} segments")
    pts: list[tuple[float, float]] = []
    for x1, y1, x2, y2 in lines[:, 0, :]:
        if x2 == x1:
            continue
        slope = (y2 - y1) / float(x2 - x1)
        if 0.2 <= abs(slope) <= 1.6:
            pts.extend([(float(x1), float(y1)), (float(x2), float(y2))])
    if len(pts) < 4:
        return []
    hull = cv2.convexHull(np.array(pts, dtype=np.float32)).reshape(-1, 2)
    return [_order_quad_corners(hull)]


def _save_grid_debug(
    gray: np.ndarray, edges: np.ndarray, image: np.ndarray, corners: MapCorners
) -> None:
    """Write preprocessed + annotated images so a failure is diagnosable."""
    try:
        _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(_DEBUG_DIR / "grid_debug_preprocessed.png"), edges)
        cv2.imwrite(str(_DEBUG_DIR / "grid_debug_gray.png"), gray)
        annotated = image.copy()
        pts = corners.as_array().astype(int)
        cv2.polylines(annotated, [pts.reshape(-1, 1, 2)], True, (0, 0, 255), 3)
        for (x, y), name in zip(pts, ("top", "right", "bottom", "left")):
            cv2.circle(annotated, (int(x), int(y)), 10, (0, 255, 0), -1)
            cv2.putText(
                annotated, name, (int(x) + 10, int(y)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2,
            )
        cv2.imwrite(str(_DEBUG_DIR / "grid_debug_annotated.png"), annotated)
        logger.debug(f"grid: wrote debug images to {_DEBUG_DIR}")
    except Exception as exc:  # pragma: no cover - debug only
        logger.debug(f"grid: failed to write debug images: {exc}")


def detect_map_corners(image: np.ndarray) -> MapCorners:
    """Detect the village diamond corners using brightness contrast only.

    Theme-agnostic by design: the diamond reads as a bright field/line over a
    darker surround whatever the grass color (default green, winter ice, desert
    sand). We binarize by luminance several ways, take axis-extreme corners for
    every large contour, add a Hough-based fallback, then keep the candidate
    that scores best under :func:`corner_confidence`. Debug artifacts are written
    to ``$COC_GRID_DEBUG_DIR`` (default /tmp) when ``COC_GRID_DEBUG`` is set or
    the best candidate is below the trust threshold, so a failing real-world
    screenshot always leaves a trail (preprocessed + annotated images).
    """
    if image is None or image.ndim != 3:
        raise GridRegistrationError("image must be an HxWx3 BGR array")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    _log_brightness(gray)
    frame_area = float(gray.shape[0] * gray.shape[1])
    edges = _auto_canny(gray)

    candidates: list[tuple[float, str, MapCorners]] = []
    for name, mask in _candidate_masks(gray).items():
        for corners in _contour_corner_candidates(mask, frame_area):
            conf = corner_confidence(image, corners)
            candidates.append((conf, name, corners))
            logger.debug(
                f"grid candidate [{name}] confidence={conf:.3f} {corners.to_dict()}"
            )
    for corners in _hough_corner_candidates(edges, image.shape):
        conf = corner_confidence(image, corners)
        candidates.append((conf, "hough", corners))
        logger.debug(
            f"grid candidate [hough] confidence={conf:.3f} {corners.to_dict()}"
        )

    debug_on = bool(os.environ.get("COC_GRID_DEBUG"))
    if not candidates:
        if debug_on:
            try:
                _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(_DEBUG_DIR / "grid_debug_preprocessed.png"), edges)
            except Exception:  # pragma: no cover
                pass
        raise GridRegistrationError("no diamond-like contour found in any mask")

    candidates.sort(key=lambda t: t[0], reverse=True)
    best_conf, best_name, corners = candidates[0]
    logger.debug(f"grid: best candidate [{best_name}] confidence={best_conf:.3f}")

    if debug_on or best_conf < 0.70:
        _save_grid_debug(gray, edges, image, corners)

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
