"""Detector entry point: screenshot -> canonical Layout.

Pipeline (idempotent, confidence-gated, failure-explicit):

    image bytes
      -> grid registration (grid.py: corner detect + homography)   [deterministic]
      -> ONE Claude Vision call (vision.py)                        [temperature 0]
      -> pixel->tile registration of every detection
      -> wall pieces grouped into ordered chains
      -> Layout assembled
      -> validate (validate.py); on failure, re-run vision (max 2 retries)

Reuses the existing device layer: ``detect_from_device`` calls
``cocbot.io.capture_screenshot`` (imported lazily so this package does not pull
in the whole bot just to parse a saved screenshot).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from collections import Counter
from dataclasses import dataclass

import cv2
import numpy as np

try:
    from loguru import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("coc.copy.detect")

from src.copy.grid import Grid, GridRegistrationError
from src.copy.schema import (
    CONFIDENCE_FLOOR,
    KNOWN_TYPES,
    MAX_TILE,
    GridInfo,
    Layout,
    LayoutObject,
    SourceInfo,
    WallChain,
    default_footprint,
)
from src.copy.validate import validate_layout
from src.copy.vision import VisionResult, VisionTransport, detect_objects

MAX_RETRIES = 2  # so up to 3 vision calls total
MAX_SKIP_RATIO = 0.10  # fail if >10% of buildings can't be placed


class DetectionError(RuntimeError):
    """Raised when detection cannot produce a valid layout after retries.

    Carries the best-effort :class:`Layout` and the list of blocking reasons so
    callers can inspect/repair instead of getting a silent half-result.
    """

    def __init__(self, message: str, *, layout: Layout, errors: list[str]) -> None:
        super().__init__(message)
        self.layout = layout
        self.errors = errors


# --------------------------- wall chain parsing ---------------------------


@dataclass(frozen=True)
class WallPiece:
    """One detected 1x1 wall tile, pre-chaining."""

    tile: tuple[int, int]
    level: int | None = None
    confidence: float = 1.0


def _neighbors8(t: tuple[int, int]) -> list[tuple[int, int]]:
    x, y = t
    return [
        (x + dx, y + dy)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        if not (dx == 0 and dy == 0)
    ]


def _ortho_neighbors(t: tuple[int, int]) -> list[tuple[int, int]]:
    x, y = t
    return [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]


def _is_diagonal(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] != b[0] and a[1] != b[1]


def _wall_adjacency(
    nodes: set[tuple[int, int]],
) -> dict[tuple[int, int], list[tuple[int, int]]]:
    """8-connected adjacency, minus diagonal 'corner shortcuts'.

    CoC walls connect both orthogonally and diagonally, but at a 90-degree bend
    (an L-corner) the two arms are also diagonally adjacent, which would create a
    spurious triangle and fragment the chain. We drop a diagonal edge whenever
    its two endpoints already share an orthogonal neighbor that is itself a wall
    tile (i.e. the diagonal is just a corner cut). Genuine diagonal wall runs --
    where no such common orthogonal tile exists -- stay connected.
    """
    adj: dict[tuple[int, int], set[tuple[int, int]]] = {n: set() for n in nodes}
    for n in nodes:
        for m in _neighbors8(n):
            if m not in nodes:
                continue
            if _is_diagonal(n, m):
                shared = (set(_ortho_neighbors(n)) & set(_ortho_neighbors(m))) & nodes
                if shared:
                    continue  # diagonal corner shortcut -> skip
            adj[n].add(m)
    return {n: sorted(ms) for n, ms in adj.items()}


def _finalize_path(
    path: list[tuple[int, int]],
) -> tuple[list[tuple[int, int]], bool]:
    """If a walk returned to its start, mark it closed and drop the dup tile."""
    if len(path) > 2 and path[0] == path[-1]:
        return path[:-1], True
    return path, False


def build_wall_chains(pieces: list[WallPiece]) -> list[WallChain]:
    """Group connected wall tiles into ordered chains (segments).

    Decomposition rule (deterministic):
      * Nodes of degree != 2 (endpoints, junctions, isolated tiles) are "breaks".
      * Each maximal run of degree-2 tiles between two breaks is one chain.
      * Pure loops (every tile degree 2, no break) become one ``closed`` chain.
      * Branch points are shared as endpoints between the chains that meet there.

    Tiles within a chain are ordered as a walk so the paster can stroke them.
    All iteration is over sorted collections so the same input always yields the
    same chains in the same order (idempotency).
    """
    if not pieces:
        return []

    # Deduplicate by tile (keep highest-confidence record per tile).
    by_tile: dict[tuple[int, int], WallPiece] = {}
    for p in pieces:
        cur = by_tile.get(p.tile)
        if cur is None or p.confidence > cur.confidence:
            by_tile[p.tile] = p

    nodes = set(by_tile)
    adj = _wall_adjacency(nodes)
    used_edges: set[frozenset[tuple[int, int]]] = set()
    chains: list[WallChain] = []

    def walk(start: tuple[int, int], nxt: tuple[int, int]) -> list[tuple[int, int]]:
        """Walk from start through degree-2 nodes until a break/visited node."""
        path = [start, nxt]
        used_edges.add(frozenset((start, nxt)))
        prev, cur = start, nxt
        while len(adj[cur]) == 2:
            a, b = adj[cur]
            forward = b if a == prev else a
            edge = frozenset((cur, forward))
            if edge in used_edges:
                break
            used_edges.add(edge)
            path.append(forward)
            prev, cur = cur, forward
            if cur == start:  # closed loop returned to origin
                break
        return path

    # 1) Paths anchored at break nodes (degree != 2), in sorted order.
    break_nodes = sorted(n for n in nodes if len(adj[n]) != 2)
    for n in break_nodes:
        if len(adj[n]) == 0:  # isolated tile -> single-tile chain
            chains.append(_make_chain(len(chains), [n], by_tile, closed=False))
            continue
        for m in adj[n]:
            if frozenset((n, m)) in used_edges:
                continue
            path, closed = _finalize_path(walk(n, m))
            chains.append(_make_chain(len(chains), path, by_tile, closed=closed))

    # 2) Remaining edges belong to pure loops (all degree-2).
    for n in sorted(nodes):
        for m in adj[n]:
            if frozenset((n, m)) in used_edges:
                continue
            path, closed = _finalize_path(walk(n, m))
            chains.append(_make_chain(len(chains), path, by_tile, closed=closed))

    return chains


def _make_chain(
    index: int,
    tiles: list[tuple[int, int]],
    by_tile: dict[tuple[int, int], WallPiece],
    *,
    closed: bool,
) -> WallChain:
    levels = [by_tile[t].level for t in tiles]
    confs = [by_tile[t].confidence for t in tiles]
    known_levels = [lv for lv in levels if lv is not None]
    dominant = Counter(known_levels).most_common(1)[0][0] if known_levels else None
    mixed = len(set(known_levels)) > 1
    return WallChain(
        id=f"wall_{index:02d}",
        tiles=tiles,
        level=dominant,
        closed=closed,
        piece_levels=(levels if mixed else None),  # type: ignore[arg-type]
        confidence=round(min(confs), 3) if confs else 1.0,
    )


# --------------------------- detection pipeline ---------------------------


def _image_id(image_bytes: bytes) -> str:
    return "sha256:" + hashlib.sha256(image_bytes).hexdigest()


def _load_image(path: str) -> tuple[np.ndarray, bytes]:
    with open(path, "rb") as fh:
        raw = fh.read()
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise DetectionError(
            f"could not decode image: {path}", layout=Layout(), errors=["bad image"]
        )
    return img, raw


def _clamp_anchor(anchor: int, footprint: int) -> int:
    """Clamp a footprint anchor so the whole footprint stays within 0..MAX_TILE."""
    return min(max(anchor, 0), MAX_TILE - footprint + 1)


# Placement nudges: original spot first, then up to 3 single-tile shifts. If all
# four collide, the building is skipped (robust to vision's imperfect centers).
_NUDGES = ((0, 0), (1, 0), (-1, 0), (0, 1))

_CALIBRATABLE_CATEGORIES = frozenset(("defense", "resource", "army"))
_CALIBRATION_INPUT_MIN = 0.50
_CALIBRATION_INPUT_MAX = 0.75
_CALIBRATION_OUTPUT_MIN = 0.75
_CALIBRATION_OUTPUT_MAX = 0.85


def _confidence_calibration(
    type_key: str, confidence: float
) -> tuple[float, str | None]:
    """Lift conservative confidence only for schema-known actionable buildings."""
    spec = KNOWN_TYPES.get(type_key)
    if spec is None:
        return confidence, None
    category = spec[2]
    if category not in _CALIBRATABLE_CATEGORIES:
        return confidence, None
    if not (_CALIBRATION_INPUT_MIN <= confidence < _CALIBRATION_INPUT_MAX):
        return confidence, None

    span_in = _CALIBRATION_INPUT_MAX - _CALIBRATION_INPUT_MIN
    span_out = _CALIBRATION_OUTPUT_MAX - _CALIBRATION_OUTPUT_MIN
    calibrated = _CALIBRATION_OUTPUT_MIN + (
        (confidence - _CALIBRATION_INPUT_MIN) / span_in
    ) * span_out
    calibrated = min(max(calibrated, _CALIBRATION_OUTPUT_MIN), _CALIBRATION_OUTPUT_MAX)
    return round(calibrated, 3), (
        f"known actionable {category} type with specific model label"
    )


def _assemble(
    vres: VisionResult, grid: Grid
) -> tuple[list[LayoutObject], list[WallPiece], list[str], int, int]:
    """Register raw detections to tiles with footprint-aware placement.

    Vision gives PIXEL centers only. Here we: convert center pixel -> center tile
    via the grid, look up the type's footprint, CENTER that footprint on the
    center tile, clamp it in-bounds, and resolve overlaps by nudging up to 3
    tiles or (failing that) skipping the building. Walls that land on a building
    tile are skipped. Returns (objects, wall_pieces, warnings, skipped, total).
    """
    warnings: list[str] = []
    objects: list[LayoutObject] = []
    wall_pieces: list[WallPiece] = []
    occupied: dict[tuple[int, int], str] = {}

    # Sort deterministically so ids/placement are stable for identical output.
    ordered = sorted(
        vres.detections,
        key=lambda d: (float(d.get("py", 0)), float(d.get("px", 0)), str(d["type"])),
    )
    buildings = [d for d in ordered if str(d["type"]) != "wall"]
    walls = [d for d in ordered if str(d["type"]) == "wall"]

    obj_index = 0
    skipped = 0
    for det in buildings:
        type_key = str(det["type"])
        px, py = float(det["px"]), float(det["py"])
        original_conf = float(det.get("confidence", 1.0))
        conf, calibration_reason = _confidence_calibration(type_key, original_conf)
        level = det.get("level")
        level = None if level is None else int(level)

        cx, cy = grid.pixel_to_tile(px, py)  # center tile (already clamped 0..43)
        fw, fh = default_footprint(type_key)
        # center the footprint on the center tile, then clamp in-bounds
        ax = _clamp_anchor(cx - (fw - 1) // 2, fw)
        ay = _clamp_anchor(cy - (fh - 1) // 2, fh)

        placed: tuple[int, int, list[tuple[int, int]]] | None = None
        for dx, dy in _NUDGES:
            nx = _clamp_anchor(ax + dx, fw)
            ny = _clamp_anchor(ay + dy, fh)
            tiles = [(nx + i, ny + j) for i in range(fw) for j in range(fh)]
            if all(t not in occupied for t in tiles):
                placed = (nx, ny, tiles)
                break

        if placed is None:
            skipped += 1
            warnings.append(
                f"skipped {type_key} at px({px:.0f},{py:.0f}) ~tile({cx},{cy}): "
                f"no collision-free {fw}x{fh} placement after nudging"
            )
            continue

        nx, ny, tiles = placed
        oid = f"obj_{obj_index:04d}"
        for t in tiles:
            occupied[t] = oid
        if (nx, ny) != (cx - (fw - 1) // 2, cy - (fh - 1) // 2):
            warnings.append(
                f"{oid} ({type_key}) adjusted to ({nx},{ny}) to avoid overlap/bounds"
            )
        if type_key not in KNOWN_TYPES:
            warnings.append(f"unknown type {type_key!r} kept as-is at ({nx},{ny})")

        notes = det.get("notes")
        if calibration_reason is not None:
            calibration_note = (
                f"confidence calibrated from {original_conf:.2f} to {conf:.2f}: "
                f"{calibration_reason}"
            )
            notes = f"{notes}; {calibration_note}" if notes else calibration_note
            warnings.append(f"{oid} ({type_key}) {calibration_note}")
            logger.info(
                f"confidence calibration: type={type_key} "
                f"original={original_conf:.2f} calibrated={conf:.2f} "
                f"reason={calibration_reason}"
            )

        obj = LayoutObject(
            id=oid,
            category=det.get("category", "decoration"),
            type=type_key,
            tile_x=nx,
            tile_y=ny,
            rotation=int(det.get("rotation", 0)),
            level=level,
            footprint=(fw, fh),
            confidence=conf,
            original_confidence=(
                original_conf if calibration_reason is not None else None
            ),
            notes=notes,
            pixel_x=px,
            pixel_y=py,
        )
        if conf < CONFIDENCE_FLOOR:
            warnings.append(
                f"{oid} ({type_key}) low confidence {conf:.2f} at ({nx},{ny})"
            )
        objects.append(obj)
        obj_index += 1

    # Walls are 1x1; drop any that land on a building tile (don't fail the run).
    for det in walls:
        px, py = float(det["px"]), float(det["py"])
        conf = float(det.get("confidence", 1.0))
        level = det.get("level")
        level = None if level is None else int(level)
        tx, ty = grid.pixel_to_tile(px, py)
        if (tx, ty) in occupied:
            warnings.append(
                f"skipped wall piece at ({tx},{ty}); collides with {occupied[(tx, ty)]}"
            )
            continue
        wall_pieces.append(WallPiece((tx, ty), level=level, confidence=conf))

    return objects, wall_pieces, warnings, skipped, len(buildings)


def detect(
    screenshot_path: str,
    *,
    transport: VisionTransport | None = None,
    grid: Grid | None = None,
) -> Layout:
    """Detect a full village layout from a screenshot file.

    Args:
        screenshot_path: path to a 1920x1080 (recommended) BGR/PNG screenshot of
            a CoC village. Editor/layout-edit view is preferred because traps and
            walls are clearest there.
        transport: optional injected vision transport (tests pass a fake). When
            omitted, the live Anthropic transport is used and ANTHROPIC_API_KEY
            must be set.
        grid: optional pre-built grid (skip on-image corner detection).

    Returns:
        A validated :class:`Layout`.

    Raises:
        GridRegistrationError: the map corners could not be trusted.
        DetectionError: no valid layout after MAX_RETRIES re-runs (carries the
            best-effort layout and the blocking reasons).
    """
    image, raw_bytes = _load_image(screenshot_path)
    h, w = image.shape[:2]

    if grid is None:
        grid = Grid.from_image(image)  # raises GridRegistrationError if untrusted

    source = SourceInfo(
        kind="screenshot",
        image_id=_image_id(raw_bytes),
        captured_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        image_width=w,
        image_height=h,
    )

    last_layout: Layout | None = None
    last_errors: list[str] = []

    for attempt in range(MAX_RETRIES + 1):
        vres = detect_objects(image, transport=transport)
        objects, wall_pieces, warnings, skipped, total_buildings = _assemble(
            vres, grid
        )
        chains = build_wall_chains(wall_pieces)

        layout = Layout(
            source=source,
            grid=GridInfo(
                corners_px=grid.corners.to_dict(),
                corner_confidence=grid.confidence,
            ),
            objects=objects,
            wall_chains=chains,
            town_hall_level=vres.town_hall_level,
            warnings=list(warnings),
        )

        if vres.view != "editor":
            layout.warnings.append(
                "source view is not 'editor'; traps are usually invisible in the "
                "normal view -- supply a layout-edit screenshot to capture traps"
            )

        skip_ratio = (skipped / total_buildings) if total_buildings else 0.0
        if skipped:
            layout.warnings.append(
                f"placement: skipped {skipped}/{total_buildings} buildings "
                f"({skip_ratio:.0%}) with unresolvable collisions"
            )

        result = validate_layout(layout)
        layout.warnings.extend(result.warnings)
        has_low_conf = layout.low_confidence_count() > 0
        too_many_skipped = skip_ratio > MAX_SKIP_RATIO

        if result.ok and not has_low_conf and not too_many_skipped:
            logger.info(
                f"detect: valid layout on attempt {attempt + 1} ({layout.stats()})"
            )
            return layout

        errors = list(result.errors)
        if too_many_skipped:
            errors.append(
                f"too many buildings skipped: {skipped}/{total_buildings} "
                f"({skip_ratio:.0%}) > {MAX_SKIP_RATIO:.0%}"
            )
        last_layout, last_errors = layout, errors
        reason = "; ".join(errors) if errors else "low-confidence items"
        if attempt < MAX_RETRIES:
            logger.warning(
                f"detect: attempt {attempt + 1} rejected ({reason}); re-running vision"
            )
        else:
            logger.error(f"detect: exhausted retries; final issues: {reason}")

    assert last_layout is not None
    if last_errors:
        # Hard schema/sanity failure after retries -- fail explicitly.
        joined = "; ".join(last_errors)
        raise DetectionError(
            f"layout invalid after {MAX_RETRIES} retries: {joined}",
            layout=last_layout,
            errors=last_errors,
        )
    # Only soft (low-confidence) issues remain: return the best-effort layout
    # with everything flagged in warnings -- nothing dropped silently.
    last_layout.warnings.append(
        "returned with unresolved low-confidence detections after retries; "
        "review 'confidence' fields before pasting"
    )
    logger.warning("detect: returning best-effort layout with low-confidence flags")
    return last_layout


def detect_from_device(*, transport: VisionTransport | None = None) -> Layout:
    """Capture the current screen via the existing ADB layer, then detect.

    Reuses ``cocbot.io.capture_screenshot`` (lazy import) so this module does not
    duplicate the device/ADB code that already lives in the repo. Writes the
    capture to a temp PNG and runs the normal file pipeline for one code path.
    """
    import tempfile

    from cocbot.io import capture_screenshot  # noqa: PLC0415 - reuse existing ADB layer

    frame = capture_screenshot()  # BGR np.ndarray, 1920x1080
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        cv2.imwrite(tmp.name, frame)
        path = tmp.name
    layout = detect(path, transport=transport)
    layout.source.kind = "device"
    return layout


def _cli(argv: list[str] | None = None) -> int:
    """Tiny CLI: ``python -m src.copy.detect <screenshot.png>`` -> JSON on stdout."""
    import argparse

    parser = argparse.ArgumentParser(description="CoC base detector")
    parser.add_argument("screenshot", help="path to a village screenshot (png/jpg)")
    parser.add_argument("--out", help="write JSON here instead of stdout")
    args = parser.parse_args(argv)

    layout = detect(args.screenshot)
    text = layout.to_json()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
