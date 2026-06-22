"""Canonical layout schema — dataclasses + (de)serialization.

Source of truth for ``docs/layout-schema.md``. Pure data + JSON helpers, no
OpenCV / no ADB / no network, so it is trivially unit-testable and importable
from anywhere in the pipeline.

Conventions mirror the existing ``cocbot`` package: modern type hints
(``X | None``, ``list[...]``), dataclasses, snake_case.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

SCHEMA_VERSION = "1.0.0"
GRID_SIZE = 44  # tiles per side; tile indices are 0..GRID_SIZE-1
MAX_TILE = GRID_SIZE - 1
CONFIDENCE_FLOOR = 0.7  # below this a detection is re-asked, never silently used

Category = Literal["defense", "resource", "army", "trap", "obstacle", "decoration"]
VALID_CATEGORIES: frozenset[str] = frozenset(
    ("defense", "resource", "army", "trap", "obstacle", "decoration")
)
VALID_ROTATIONS: frozenset[int] = frozenset((0, 90, 180, 270))

# Canonical type -> (footprint_w, footprint_h, default_category). Used to fill
# missing footprints and to sanity-check the model's category. Footprints are
# the common max-size values; the paster may refine per level.
KNOWN_TYPES: dict[str, tuple[int, int, Category]] = {
    # defense
    "town_hall": (4, 4, "defense"),
    "cannon": (3, 3, "defense"),
    "archer_tower": (3, 3, "defense"),
    "mortar": (3, 3, "defense"),
    "wizard_tower": (3, 3, "defense"),
    "air_defense": (3, 3, "defense"),
    "x_bow": (3, 3, "defense"),
    "inferno_tower": (3, 3, "defense"),
    "eagle_artillery": (4, 4, "defense"),
    "scattershot": (3, 3, "defense"),
    "air_sweeper": (2, 2, "defense"),
    "bomb_tower": (3, 3, "defense"),
    "monolith": (3, 3, "defense"),
    "spell_tower": (3, 3, "defense"),
    "builder_hut": (2, 2, "defense"),
    # resource
    "gold_mine": (3, 3, "resource"),
    "elixir_collector": (3, 3, "resource"),
    "dark_elixir_drill": (3, 3, "resource"),
    "gold_storage": (3, 3, "resource"),
    "elixir_storage": (3, 3, "resource"),
    "dark_elixir_storage": (3, 3, "resource"),
    "clan_castle": (3, 3, "resource"),
    # army
    "army_camp": (5, 5, "army"),
    "barracks": (3, 3, "army"),
    "dark_barracks": (3, 3, "army"),
    "laboratory": (3, 3, "army"),
    "spell_factory": (3, 3, "army"),
    "dark_spell_factory": (3, 3, "army"),
    "pet_house": (3, 3, "army"),
    "blacksmith": (3, 3, "army"),
    "king_altar": (3, 3, "army"),
    "queen_altar": (3, 3, "army"),
    "warden_altar": (3, 3, "army"),
    "champion_altar": (3, 3, "army"),
    "minion_prince_altar": (3, 3, "army"),
    # trap (1x1 unless noted)
    "bomb": (1, 1, "trap"),
    "spring_trap": (1, 1, "trap"),
    "giant_bomb": (2, 2, "trap"),
    "air_bomb": (1, 1, "trap"),
    "seeking_air_mine": (1, 1, "trap"),
    "skeleton_trap": (1, 1, "trap"),
    "tornado_trap": (2, 2, "trap"),
}

# Trap type keys (used to flag traps explicitly).
TRAP_TYPES: frozenset[str] = frozenset(
    t for t, (_w, _h, c) in KNOWN_TYPES.items() if c == "trap"
)


def default_footprint(type_key: str) -> tuple[int, int]:
    """Best-effort footprint for a type; (1, 1) for unknown types."""
    spec = KNOWN_TYPES.get(type_key)
    return (spec[0], spec[1]) if spec else (1, 1)


@dataclass
class LayoutObject:
    """A single non-wall placeable (building, trap, obstacle, decoration)."""

    id: str
    category: Category
    type: str
    tile_x: int
    tile_y: int
    rotation: int = 0
    level: int | None = None
    footprint: tuple[int, int] | None = None
    is_trap: bool = False
    confidence: float = 1.0
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.footprint is None:
            self.footprint = default_footprint(self.type)
        # keep is_trap consistent with category
        self.is_trap = self.category == "trap" or self.type in TRAP_TYPES

    def occupied_tiles(self) -> list[tuple[int, int]]:
        """Every tile this object's footprint covers (anchor = top tile)."""
        w, h = self.footprint or (1, 1)
        return [
            (self.tile_x + dx, self.tile_y + dy)
            for dx in range(w)
            for dy in range(h)
        ]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.footprint is not None:
            d["footprint"] = list(self.footprint)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LayoutObject":
        fp = d.get("footprint")
        return cls(
            id=str(d["id"]),
            category=d["category"],
            type=str(d["type"]),
            tile_x=int(d["tile_x"]),
            tile_y=int(d["tile_y"]),
            rotation=int(d.get("rotation", 0)),
            level=(None if d.get("level") is None else int(d["level"])),
            footprint=(tuple(fp) if fp else None),  # type: ignore[arg-type]
            is_trap=bool(d.get("is_trap", False)),
            confidence=float(d.get("confidence", 1.0)),
            notes=d.get("notes"),
        )


@dataclass
class WallChain:
    """A connected run of wall tiles, ordered as a stroke path for the paster."""

    id: str
    tiles: list[tuple[int, int]]
    level: int | None = None
    closed: bool = False
    piece_levels: list[int] | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tiles": [list(t) for t in self.tiles],
            "level": self.level,
            "closed": self.closed,
            "piece_levels": self.piece_levels,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WallChain":
        return cls(
            id=str(d["id"]),
            tiles=[tuple(t) for t in d["tiles"]],  # type: ignore[misc]
            level=(None if d.get("level") is None else int(d["level"])),
            closed=bool(d.get("closed", False)),
            piece_levels=d.get("piece_levels"),
            confidence=float(d.get("confidence", 1.0)),
        )


@dataclass
class GridInfo:
    """Registration metadata. Debug only — pixel data never drives the paster."""

    size: int = GRID_SIZE
    corners_px: dict[str, tuple[float, float]] | None = None
    corner_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "corners_px": (
                {k: list(v) for k, v in self.corners_px.items()}
                if self.corners_px
                else None
            ),
            "corner_confidence": self.corner_confidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GridInfo":
        corners = d.get("corners_px")
        return cls(
            size=int(d.get("size", GRID_SIZE)),
            corners_px=(
                {k: tuple(v) for k, v in corners.items()} if corners else None
            ),
            corner_confidence=float(d.get("corner_confidence", 0.0)),
        )


@dataclass
class SourceInfo:
    kind: str = "screenshot"  # screenshot | device | clan_chat | war | fc
    image_id: str | None = None
    captured_at: str | None = None
    image_width: int | None = None
    image_height: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SourceInfo":
        return cls(
            kind=d.get("kind", "screenshot"),
            image_id=d.get("image_id"),
            captured_at=d.get("captured_at"),
            image_width=d.get("image_width"),
            image_height=d.get("image_height"),
        )


@dataclass
class Layout:
    """The canonical output. Serializes to the JSON in docs/layout-schema.md."""

    source: SourceInfo = field(default_factory=SourceInfo)
    grid: GridInfo = field(default_factory=GridInfo)
    objects: list[LayoutObject] = field(default_factory=list)
    wall_chains: list[WallChain] = field(default_factory=list)
    town_hall_level: int | None = None
    warnings: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    # ---- derived stats ----

    def wall_piece_count(self) -> int:
        return sum(len(c.tiles) for c in self.wall_chains)

    def trap_count(self) -> int:
        return sum(1 for o in self.objects if o.is_trap)

    def low_confidence_count(self) -> int:
        n = sum(1 for o in self.objects if o.confidence < CONFIDENCE_FLOOR)
        n += sum(1 for c in self.wall_chains if c.confidence < CONFIDENCE_FLOOR)
        return n

    def stats(self) -> dict[str, int]:
        return {
            "object_count": len(self.objects),
            "wall_piece_count": self.wall_piece_count(),
            "trap_count": self.trap_count(),
            "low_confidence_count": self.low_confidence_count(),
        }

    # ---- serialization ----

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source.to_dict(),
            "town_hall_level": self.town_hall_level,
            "grid": self.grid.to_dict(),
            "objects": [o.to_dict() for o in self.objects],
            "wall_chains": [c.to_dict() for c in self.wall_chains],
            "warnings": list(self.warnings),
            "stats": self.stats(),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        # sort_keys=False keeps our intentional field order; stable across runs.
        return json.dumps(self.to_dict(), indent=indent, separators=(",", ": "))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Layout":
        return cls(
            source=SourceInfo.from_dict(d.get("source", {})),
            grid=GridInfo.from_dict(d.get("grid", {})),
            objects=[LayoutObject.from_dict(o) for o in d.get("objects", [])],
            wall_chains=[WallChain.from_dict(c) for c in d.get("wall_chains", [])],
            town_hall_level=d.get("town_hall_level"),
            warnings=list(d.get("warnings", [])),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )

    @classmethod
    def from_json(cls, text: str) -> "Layout":
        return cls.from_dict(json.loads(text))
