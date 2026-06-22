"""Schema validation + sanity checks for a Layout.

Pure, deterministic, no I/O. ``detect.py`` calls ``validate_layout`` and, on
failure, re-runs the vision model (max 2 retries). Every failure is returned as
an explicit human-readable reason — a layout is never quietly accepted as good.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.copy.schema import (
    CONFIDENCE_FLOOR,
    MAX_TILE,
    VALID_CATEGORIES,
    VALID_ROTATIONS,
    Layout,
)

# TH15 wall cap is 250 (+ a handful from events); 275 rejects nonsense while
# leaving margin for future town-hall levels.
MAX_WALL_TILES = 275


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:  # allow `if validate_layout(...)`
        return self.ok


def _in_bounds(x: int, y: int) -> bool:
    return 0 <= x <= MAX_TILE and 0 <= y <= MAX_TILE


def validate_layout(layout: Layout) -> ValidationResult:
    """Return ok + the list of hard errors and soft warnings for a layout."""
    errors: list[str] = []
    warnings: list[str] = []

    # ---- per-object structural checks ----
    occupied: dict[tuple[int, int], str] = {}  # tile -> owning object id
    th_ids: list[str] = []

    for obj in layout.objects:
        if obj.category not in VALID_CATEGORIES:
            errors.append(f"{obj.id}: invalid category {obj.category!r}")
        if obj.rotation not in VALID_ROTATIONS:
            errors.append(f"{obj.id}: invalid rotation {obj.rotation}")
        if obj.type == "town_hall":
            th_ids.append(obj.id)

        for tx, ty in obj.occupied_tiles():
            if not _in_bounds(tx, ty):
                errors.append(
                    f"{obj.id} ({obj.type}): tile ({tx},{ty}) out of bounds 0..{MAX_TILE}"
                )
                continue
            clash = occupied.get((tx, ty))
            if clash is not None:
                errors.append(
                    f"tile collision at ({tx},{ty}): {obj.id} overlaps {clash}"
                )
            else:
                occupied[(tx, ty)] = obj.id

        if obj.confidence < CONFIDENCE_FLOOR:
            warnings.append(
                f"{obj.id} ({obj.type}): low confidence {obj.confidence:.2f}"
            )

    # ---- Town Hall exactly once ----
    if len(th_ids) == 0:
        errors.append("no town_hall detected (expected exactly 1)")
    elif len(th_ids) > 1:
        errors.append(f"multiple town_halls detected: {th_ids} (expected exactly 1)")

    # ---- walls ----
    wall_tiles_seen: dict[tuple[int, int], str] = {}
    total_wall_tiles = 0
    for chain in layout.wall_chains:
        for tx, ty in chain.tiles:
            total_wall_tiles += 1
            if not _in_bounds(tx, ty):
                errors.append(
                    f"{chain.id}: wall tile ({tx},{ty}) out of bounds 0..{MAX_TILE}"
                )
                continue
            if (tx, ty) in occupied:
                errors.append(
                    f"{chain.id}: wall tile ({tx},{ty}) collides with object "
                    f"{occupied[(tx, ty)]}"
                )
            dup = wall_tiles_seen.get((tx, ty))
            if dup is not None:
                errors.append(
                    f"{chain.id}: wall tile ({tx},{ty}) duplicated (also in {dup})"
                )
            else:
                wall_tiles_seen[(tx, ty)] = chain.id
        if chain.confidence < CONFIDENCE_FLOOR:
            warnings.append(f"{chain.id}: low confidence {chain.confidence:.2f}")

    if total_wall_tiles >= MAX_WALL_TILES:
        errors.append(
            f"wall count {total_wall_tiles} >= {MAX_WALL_TILES} (implausible)"
        )

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)
