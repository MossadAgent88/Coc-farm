"""Village editor session controller for base pasting."""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np
from loguru import logger

from src.paste._paths import ensure_project_paths
from src.paste.layout import PasteObject, WallChain, WallPoint

ensure_project_paths()

from cocbot.io import batch_tap, capture_screenshot, swipe, tap  # noqa: E402
from cocbot.vision import TEMPLATES_DIR, find_green_button, find_template  # noqa: E402
from src.copy.grid import (  # noqa: E402
    Grid as CopyGrid,
    GridRegistrationError as CopyGridRegistrationError,
    MapCorners,
    corner_confidence,
    detect_map_corners,
)
from src.copy.schema import GRID_SIZE, MAX_TILE  # noqa: E402

SCREEN_SHAPE = (1080, 1920, 3)
DEFAULT_GRID_SIZE = GRID_SIZE
RECALIBRATE_EVERY = 20
CORNER_OFFSCREEN_MARGIN = 400


class EditorCalibrationError(RuntimeError):
    """Raised when editor grid corners cannot be validated."""


class EditorModeError(RuntimeError):
    """Raised when the editor mode cannot be asserted."""


class EditorPlacementError(RuntimeError):
    """Raised when a placement action cannot be completed."""


@dataclass(frozen=True)
class EditorGrid:
    """Editor wrapper around ``src.copy.grid.Grid``.

    Corners are ordered by the detector contract: top, right, bottom, left.
    ``tile_to_pixel`` delegates to ``Grid.tile_to_pixel`` so the paster and
    detector use the same homography convention.
    """

    grid: CopyGrid

    @classmethod
    def from_corners(
        cls,
        corners: MapCorners | Sequence[tuple[float, float]],
        image: np.ndarray | None = None,
        min_confidence: float = 0.7,
    ) -> "EditorGrid":
        validated = validate_editor_corners(corners, image=image)
        ref_image = image if image is not None else _synthetic_corner_image(validated)
        grid = CopyGrid.from_corners(validated, ref_image)
        if grid.confidence < min_confidence:
            raise EditorCalibrationError(
                f"Editor grid corner confidence {grid.confidence:.2f} "
                f"< {min_confidence:.2f}"
            )
        return cls(grid=grid)

    @property
    def corners(self) -> tuple[tuple[float, float], ...]:
        c = self.grid.corners
        return (c.top, c.right, c.bottom, c.left)

    @property
    def grid_size(self) -> int:
        return GRID_SIZE

    def tile_to_pixel(self, tx: int, ty: int) -> tuple[int, int]:
        x, y = self.grid.tile_to_pixel(tx, ty)
        return int(round(x)), int(round(y))


class EditorSession:
    """High-level controller for the CoC village editor."""

    def __init__(self, grid: EditorGrid | None = None) -> None:
        self.grid = grid
        self.placements_since_calibration = 0
        self._trap_mode = False

    def enter_edit_mode(self) -> None:
        screenshot = capture_screenshot()
        if self.is_edit_mode(screenshot):
            logger.info("Village editor already open")
            self.calibrate_editor_grid(screenshot)
            return

        logger.info("Opening village editor")
        for x, y, delay in EDITOR_OPEN_TAPS:
            tap(x, y, delay=delay)
        screenshot = capture_screenshot()
        if not self.is_edit_mode(screenshot):
            raise EditorModeError(
                "Village editor did not open or could not be asserted. "
                "Add editor UI templates before running live paste."
            )
        self.calibrate_editor_grid(screenshot)

    def exit_edit_mode(self, save: bool = True) -> None:
        self.assert_edit_mode()
        if save:
            logger.info("Saving editor layout")
            tap(*SAVE_BUTTON, delay=0.5)
            self._tap_green_or(*SAVE_CONFIRM_BUTTON)
        else:
            logger.info("Exiting editor without saving")
            tap(*CANCEL_BUTTON, delay=0.5)
            self._tap_green_or(*DISCARD_CONFIRM_BUTTON)
        time.sleep(1.0)

    def clear_layout(self) -> None:
        self.assert_edit_mode()
        logger.warning("Clearing current editor layout")
        tap(*ERASE_MODE_BUTTON, delay=0.3)
        tap(*ERASE_ALL_BUTTON, delay=0.3)
        self._tap_green_or(*ERASE_CONFIRM_BUTTON)
        time.sleep(1.0)

    def remove_at(self, tile: tuple[int, int]) -> None:
        self.assert_edit_mode()
        x, y = self._tile_to_pixel_checked(tile[0], tile[1])
        logger.info(f"Removing object at tile {tile}")
        tap(x, y, delay=0.2)
        tap(*REMOVE_BUTTON, delay=0.2)
        self._tap_green_or(*REMOVE_CONFIRM_BUTTON)

    def place(self, obj: PasteObject) -> None:
        self.assert_edit_mode()
        x, y = self._tile_to_pixel_checked(obj.tile_x, obj.tile_y)
        logger.info(f"Placing {obj.type} at tile ({obj.tile_x}, {obj.tile_y})")
        tap(x, y, delay=0.25)
        self._mark_placement()

    def place_wall_chain(self, chain: WallChain | Sequence[WallPoint]) -> None:
        self.assert_edit_mode()
        points = tuple(chain.points if isinstance(chain, WallChain) else chain)
        if len(points) < 2:
            raise EditorPlacementError("Wall chain must contain at least two points")

        pixels = [self._tile_to_pixel_checked(p.tile_x, p.tile_y) for p in points]
        segments = _wall_stroke_segments(points)
        logger.info(
            f"Dragging wall chain with {len(points)} tile(s) using "
            f"{len(segments)} stroke(s)"
        )
        for start_idx, end_idx in segments:
            x1, y1 = pixels[start_idx]
            x2, y2 = pixels[end_idx]
            duration = _wall_swipe_duration(points[start_idx], points[end_idx])
            swipe(x1, y1, x2, y2, duration_ms=duration)
            time.sleep(0.2)
        self._mark_placement()

    def open_shop(self) -> None:
        self.assert_edit_mode()
        logger.debug("Editor inventory is already visible; no shop tap needed")

    def tap_shop_category(self, category: str) -> None:
        logger.debug(
            f"Requested editor inventory category {category}; "
            "live editor build exposes a horizontal inventory strip"
        )

    def tap_shop_icon(self, obj: PasteObject, slot_index: int | None = None) -> None:
        if slot_index is None:
            slot_index = _shop_slot_from_object(obj)
        if slot_index is None:
            raise EditorPlacementError(
                f"No shop slot mapping for {obj.type!r}; refusing to guess"
            )
        x, y = _shop_slot_point(slot_index)
        logger.debug(f"Selecting shop icon for {obj.type} at slot {slot_index}")
        tap(x, y, delay=0.3)

    def rotate_selected(self, rotation: int) -> None:
        turns = (rotation // 90) % 4
        if turns <= 0:
            return
        logger.info(f"Applying {turns} rotation tap(s)")
        batch_tap([(ROTATE_BUTTON[0], ROTATE_BUTTON[1], 0.12) for _ in range(turns)])

    def confirm_level(self, obj: PasteObject) -> None:
        if not obj.level or obj.level <= 1:
            return
        logger.info(f"Confirming requested level {obj.level} for {obj.type}")
        tap(*LEVEL_BUTTON, delay=0.2)
        tap(*LEVEL_CONFIRM_BUTTON, delay=0.2)

    def confirm_placement(self) -> None:
        self._tap_green_or(*PLACEMENT_CONFIRM_BUTTON)

    def select_wall_tool(self) -> None:
        wall = PasteObject(
            tile_x=0,
            tile_y=0,
            type="wall",
            category="wall",
            name="wall",
            level=None,
            rotation=0,
            confidence=1.0,
            raw={},
        )
        self.open_shop()
        self.tap_shop_category("defense")
        self.tap_shop_icon(wall)

    def ensure_trap_mode(self) -> None:
        self.assert_edit_mode()
        if self._trap_mode or self._detect_trap_mode(capture_screenshot()):
            self._trap_mode = True
            return
        logger.info("Toggling editor trap visibility")
        tap(*TRAP_TOGGLE_BUTTON, delay=0.4)
        screenshot = capture_screenshot()
        if not self._detect_trap_mode(screenshot):
            raise EditorModeError("Could not verify editor show-traps mode")
        self._trap_mode = True

    def assert_edit_mode(self) -> None:
        screenshot = capture_screenshot()
        if not self.is_edit_mode(screenshot):
            raise EditorModeError("Not in village editor mode")

    def is_edit_mode(self, screenshot: np.ndarray) -> bool:
        _assert_screenshot_shape(screenshot)
        return _find_optional_template(screenshot, "editor_save", 0.72) is not None

    def calibrate_editor_grid(self, screenshot: np.ndarray | None = None) -> EditorGrid:
        screen = screenshot if screenshot is not None else capture_screenshot()
        _assert_screenshot_shape(screen)
        corners = _corners_from_env() or detect_editor_grid_corners(screen)
        if corners is None:
            raise EditorCalibrationError(
                "Editor grid corners were not detected; refusing to guess tile "
                "coordinates"
            )
        self.grid = EditorGrid.from_corners(corners, image=screen)
        self.placements_since_calibration = 0
        logger.info(f"Editor grid calibrated: {self.grid.corners}")
        return self.grid

    def _tile_to_pixel_checked(self, tx: int, ty: int) -> tuple[int, int]:
        if self.grid is None:
            self.calibrate_editor_grid()
        assert self.grid is not None
        if tx < 0 or ty < 0 or tx > MAX_TILE or ty > MAX_TILE:
            raise EditorPlacementError(
                f"Tile ({tx}, {ty}) is outside {self.grid.grid_size}x"
                f"{self.grid.grid_size} editor grid"
            )
        return self.grid.tile_to_pixel(tx, ty)

    def _mark_placement(self) -> None:
        self.placements_since_calibration += 1
        if self.placements_since_calibration >= RECALIBRATE_EVERY:
            logger.info("Re-verifying editor grid after 20 placements")
            self.calibrate_editor_grid()

    def _tap_green_or(self, x: int, y: int) -> None:
        screenshot = capture_screenshot()
        button = find_green_button(screenshot)
        if button:
            tap(button[0], button[1], delay=0.4)
            return
        tap(x, y, delay=0.4)

    def _detect_trap_mode(self, screenshot: np.ndarray) -> bool:
        return _find_optional_template(screenshot, "editor_show_traps_on", 0.72) is not None


def detect_editor_grid_corners(
    screenshot: np.ndarray,
) -> tuple[tuple[float, float], ...] | None:
    """Detect editor grid corners from a 1920x1080 screenshot.

    This is intentionally conservative. If the contour does not look like the
    editable map footprint, return ``None`` and let the caller abort.
    """
    _assert_screenshot_shape(screenshot)
    candidates: list[tuple[np.ndarray, tuple[int, int]]] = [(screenshot, (0, 0))]
    roi_y1, roi_y2, roi_x1, roi_x2 = EDITOR_GRID_ROI
    candidates.append((screenshot[roi_y1:roi_y2, roi_x1:roi_x2], (roi_x1, roi_y1)))

    for image, (offset_x, offset_y) in candidates:
        try:
            corners = detect_map_corners(image)
            adjusted = _offset_corners(corners, offset_x, offset_y)
            validated = validate_editor_corners(adjusted, image=screenshot)
            return _corners_tuple(validated)
        except (CopyGridRegistrationError, EditorCalibrationError):
            continue
    return None


def validate_editor_corners(
    corners: MapCorners | Sequence[tuple[float, float]],
    image: np.ndarray | None = None,
) -> MapCorners:
    mapped = _as_map_corners(corners)
    ordered = _corners_tuple(mapped)
    points = mapped.as_array()
    if np.any(points[:, 0] < -CORNER_OFFSCREEN_MARGIN) or np.any(
        points[:, 0] > 1919 + CORNER_OFFSCREEN_MARGIN
    ):
        raise EditorCalibrationError(f"Editor corner x out of bounds: {ordered}")
    if np.any(points[:, 1] < -CORNER_OFFSCREEN_MARGIN) or np.any(
        points[:, 1] > 1079 + CORNER_OFFSCREEN_MARGIN
    ):
        raise EditorCalibrationError(f"Editor corner y out of bounds: {ordered}")
    area = cv2.contourArea(points)
    if area < 90_000:
        raise EditorCalibrationError(f"Editor grid area too small: {area:.1f}")
    if not cv2.isContourConvex(points.astype(np.int32)):
        raise EditorCalibrationError("Editor grid corners are not convex")
    edge_lengths = [
        _distance(mapped.top, mapped.right),
        _distance(mapped.right, mapped.bottom),
        _distance(mapped.bottom, mapped.left),
        _distance(mapped.left, mapped.top),
    ]
    if min(edge_lengths) < 150:
        raise EditorCalibrationError("Editor grid edges are too short")
    ref_image = image if image is not None else _synthetic_corner_image(mapped)
    confidence = corner_confidence(ref_image, mapped)
    if confidence < 0.7:
        raise EditorCalibrationError(
            f"Editor grid corners failed sanity check (confidence={confidence:.2f})"
        )
    return mapped


def _as_map_corners(corners: MapCorners | Sequence[tuple[float, float]]) -> MapCorners:
    if isinstance(corners, MapCorners):
        return corners
    if len(corners) != 4:
        raise EditorCalibrationError(f"Expected 4 editor corners, got {len(corners)}")
    top, right, bottom, left = corners
    return MapCorners(
        top=(float(top[0]), float(top[1])),
        right=(float(right[0]), float(right[1])),
        bottom=(float(bottom[0]), float(bottom[1])),
        left=(float(left[0]), float(left[1])),
    )


def _corners_tuple(corners: MapCorners) -> tuple[tuple[float, float], ...]:
    return (corners.top, corners.right, corners.bottom, corners.left)


def _offset_corners(corners: MapCorners, offset_x: int, offset_y: int) -> MapCorners:
    def off(point: tuple[float, float]) -> tuple[float, float]:
        return point[0] + offset_x, point[1] + offset_y

    return MapCorners(
        top=off(corners.top),
        right=off(corners.right),
        bottom=off(corners.bottom),
        left=off(corners.left),
    )


def _synthetic_corner_image(corners: MapCorners) -> np.ndarray:
    image = np.zeros(SCREEN_SHAPE, dtype=np.uint8)
    polygon = corners.as_array().astype(np.int32)
    cv2.fillConvexPoly(image, polygon, (255, 255, 255))
    return image


def _assert_screenshot_shape(screenshot: np.ndarray) -> None:
    if screenshot.shape != SCREEN_SHAPE:
        raise EditorCalibrationError(
            f"Expected 1920x1080 BGR screenshot, got shape {screenshot.shape}"
        )


def _find_optional_template(
    screenshot: np.ndarray, template_name: str, threshold: float
) -> tuple[int, int, int, int] | None:
    if not (TEMPLATES_DIR / f"{template_name}.png").exists():
        return None
    return find_template(screenshot, template_name, threshold=threshold)


def _corners_from_env() -> MapCorners | None:
    raw = os.environ.get("COC_EDITOR_GRID_CORNERS")
    if not raw:
        return None
    parts = raw.split(";")
    if len(parts) != 4:
        raise EditorCalibrationError("COC_EDITOR_GRID_CORNERS must contain 4 x,y pairs")
    corners = []
    for part in parts:
        x_raw, y_raw = part.split(",", maxsplit=1)
        corners.append((float(x_raw), float(y_raw)))
    return validate_editor_corners(corners)


def _wall_stroke_segments(points: Sequence[WallPoint]) -> list[tuple[int, int]]:
    if not _chain_crosses_itself(points):
        return [(0, len(points) - 1)]

    segments = [(idx, idx + 1) for idx in range(len(points) - 1)]
    segments.sort(
        key=lambda pair: _tile_distance(points[pair[0]], points[pair[1]]),
        reverse=True,
    )
    return segments


def _chain_crosses_itself(points: Sequence[WallPoint]) -> bool:
    segments = list(zip(points, points[1:]))
    for i, first in enumerate(segments):
        for j, second in enumerate(segments):
            if abs(i - j) <= 1:
                continue
            if _segments_intersect(first[0], first[1], second[0], second[1]):
                return True
    return False


def _segments_intersect(a: WallPoint, b: WallPoint, c: WallPoint, d: WallPoint) -> bool:
    def orient(p: WallPoint, q: WallPoint, r: WallPoint) -> int:
        value = (q.tile_y - p.tile_y) * (r.tile_x - q.tile_x) - (
            q.tile_x - p.tile_x
        ) * (r.tile_y - q.tile_y)
        if value == 0:
            return 0
        return 1 if value > 0 else 2

    o1 = orient(a, b, c)
    o2 = orient(a, b, d)
    o3 = orient(c, d, a)
    o4 = orient(c, d, b)
    return o1 != o2 and o3 != o4


def _wall_swipe_duration(start: WallPoint, end: WallPoint) -> int:
    return max(280, int(_tile_distance(start, end) * 45))


def _tile_distance(start: WallPoint, end: WallPoint) -> float:
    return math.hypot(end.tile_x - start.tile_x, end.tile_y - start.tile_y)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _shop_slot_from_object(obj: PasteObject) -> int | None:
    return SHOP_ICON_SLOTS.get(obj.type) or SHOP_ICON_SLOTS.get(obj.name)


def _shop_slot_point(slot_index: int) -> tuple[int, int]:
    row = slot_index // SHOP_COLUMNS
    col = slot_index % SHOP_COLUMNS
    return SHOP_FIRST_SLOT[0] + col * SHOP_SLOT_STEP_X, SHOP_FIRST_SLOT[1] + row * SHOP_SLOT_STEP_Y


EDITOR_OPEN_TAPS = (
    (1845, 660, 0.8),
    (610, 990, 1.0),
)
SAVE_BUTTON = (1740, 664)
SAVE_CONFIRM_BUTTON = (1080, 730)
CANCEL_BUTTON = (1740, 761)
DISCARD_CONFIRM_BUTTON = (1080, 730)
ERASE_MODE_BUTTON = (1740, 64)
ERASE_ALL_BUTTON = (1740, 159)
ERASE_CONFIRM_BUTTON = (1080, 730)
REMOVE_BUTTON = (960, 865)
REMOVE_CONFIRM_BUTTON = (1080, 730)
SHOP_BUTTON = (1740, 965)
TRAP_TOGGLE_BUTTON = (1740, 449)
ROTATE_BUTTON = (1210, 865)
LEVEL_BUTTON = (760, 865)
LEVEL_CONFIRM_BUTTON = (1080, 730)
PLACEMENT_CONFIRM_BUTTON = (1080, 865)
EDITOR_GRID_ROI = (90, 1010, 240, 1680)  # y1, y2, x1, x2

SHOP_CATEGORY_BUTTONS = {
    "defense": (300, 980),
    "resource": (480, 980),
    "army": (660, 980),
    "decoration": (840, 980),
    "trap": (1020, 980),
    "wall": (300, 980),
}
SHOP_COLUMNS = 20
SHOP_FIRST_SLOT = (105, 965)
SHOP_SLOT_STEP_X = 202
SHOP_SLOT_STEP_Y = 0

SHOP_ICON_SLOTS = {
    "wall": 0,
    "cannon": 1,
    "archer_tower": 2,
    "mortar": 3,
    "air_defense": 4,
    "wizard_tower": 5,
    "air_sweeper": 6,
    "bomb_tower": 7,
    "hidden_tesla": 8,
    "x_bow": 9,
    "inferno_tower": 10,
    "eagle_artillery": 11,
    "scattershot": 12,
    "spell_tower": 13,
    "monolith": 14,
    "gold_mine": 0,
    "elixir_collector": 1,
    "dark_elixir_drill": 2,
    "gold_storage": 3,
    "elixir_storage": 4,
    "dark_elixir_storage": 5,
    "army_camp": 0,
    "barracks": 1,
    "laboratory": 2,
    "spell_factory": 3,
    "workshop": 4,
    "pet_house": 5,
    "bomb": 0,
    "spring_trap": 1,
    "air_bomb": 2,
    "giant_bomb": 3,
    "seeking_air_mine": 4,
    "skeleton_trap": 5,
    "tornado_trap": 6,
}
