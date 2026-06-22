"""Layout loading and normalization for the paster.

The detector-owned ``src.copy.schema.Layout`` remains the source of truth when
it is available. This module only adapts its objects into the minimal shape the
paster needs.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from loguru import logger

_LOW_CONFIDENCE = 0.7


@dataclass(frozen=True)
class PasteObject:
    tile_x: int
    tile_y: int
    type: str
    category: str
    name: str
    level: int | None
    rotation: int
    confidence: float
    raw: Any

    @property
    def tile(self) -> tuple[int, int]:
        return (self.tile_x, self.tile_y)

    @property
    def key(self) -> str:
        return (
            f"object:{self.category}:{self.type}:{self.name}:"
            f"{self.tile_x}:{self.tile_y}:{self.level or 0}:{self.rotation}"
        )

    @property
    def low_confidence(self) -> bool:
        return self.confidence < _LOW_CONFIDENCE

    @property
    def is_wall(self) -> bool:
        return self.category == "wall" or self.type == "wall"

    @property
    def is_trap(self) -> bool:
        return self.category == "trap"

    @property
    def is_obstacle(self) -> bool:
        return self.category == "obstacle"


@dataclass(frozen=True)
class WallPoint:
    tile_x: int
    tile_y: int

    @property
    def tile(self) -> tuple[int, int]:
        return (self.tile_x, self.tile_y)


@dataclass(frozen=True)
class WallChain:
    points: tuple[WallPoint, ...]
    raw: Any
    confidence: float = 1.0

    @property
    def key(self) -> str:
        coords = ";".join(f"{p.tile_x},{p.tile_y}" for p in self.points)
        return f"wall_chain:{coords}"


@dataclass(frozen=True)
class LayoutBundle:
    path: Path
    layout: Any
    raw_json: dict[str, Any]
    layout_hash: str
    town_hall: int | None
    objects: tuple[PasteObject, ...]
    wall_chains: tuple[WallChain, ...]


class LayoutContractError(ValueError):
    """Raised when a layout cannot be interpreted without guessing."""


def load_layout(path: str | Path) -> LayoutBundle:
    layout_path = Path(path).resolve()
    text = layout_path.read_text(encoding="utf-8")
    raw = json.loads(text)
    digest = _layout_hash(raw)
    layout = _load_detector_layout(layout_path, text, raw)
    objects = tuple(_iter_objects(layout, raw))
    wall_chains = tuple(_iter_wall_chains(layout, raw))
    logger.info(
        f"Loaded layout {layout_path.name}: "
        f"{len(objects)} objects, {len(wall_chains)} wall chain(s)"
    )
    return LayoutBundle(
        path=layout_path,
        layout=layout,
        raw_json=raw,
        layout_hash=digest,
        town_hall=_read_int(raw, "town_hall", "townHall", "th", "town_hall_level"),
        objects=objects,
        wall_chains=wall_chains,
    )


def _layout_hash(raw: dict[str, Any]) -> str:
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_detector_layout(path: Path, text: str, raw: dict[str, Any]) -> Any:
    try:
        schema = importlib.import_module("src.copy.schema")
    except ModuleNotFoundError:
        logger.warning(
            "Detector schema src.copy.schema is not importable; "
            "using JSON fallback for dry-run and unit-test planning only"
        )
        return raw

    layout_cls = getattr(schema, "Layout", None)
    if layout_cls is None or not hasattr(layout_cls, "from_json"):
        raise LayoutContractError("src.copy.schema.Layout.from_json(...) is missing")

    try:
        return layout_cls.from_json(text)
    except Exception as exc:
        raise LayoutContractError(
            f"{path} does not match src.copy.schema.Layout.from_json(text)"
        ) from exc


def _iter_objects(layout: Any, raw: dict[str, Any]) -> Iterable[PasteObject]:
    sources = []
    for name in ("objects", "buildings", "traps", "obstacles", "decorations"):
        value = _field(layout, name)
        if value is not None:
            sources.append(value)
    if not sources:
        for name in ("objects", "buildings", "traps", "obstacles", "decorations"):
            value = raw.get(name)
            if value is not None:
                sources.append(value)

    for source in sources:
        for item in _as_iterable(source):
            obj = _to_paste_object(item)
            if obj is not None:
                yield obj


def _iter_wall_chains(layout: Any, raw: dict[str, Any]) -> Iterable[WallChain]:
    sources = []
    for name in ("wall_chains", "wallChains", "walls"):
        value = _field(layout, name)
        if value is not None:
            sources.append(value)
    if not sources:
        for name in ("wall_chains", "wallChains", "walls"):
            value = raw.get(name)
            if value is not None:
                sources.append(value)

    for source in sources:
        for item in _as_iterable(source):
            if _looks_like_wall_chain(item):
                chain = _to_wall_chain(item)
                if len(chain.points) >= 2:
                    yield chain


def _to_paste_object(item: Any) -> PasteObject | None:
    tx, ty = _tile(item)
    if tx is None or ty is None:
        return None

    raw_type = _read_str(item, "type", "kind", "object_type", "building_type")
    name = _read_str(item, "name", "id", "building", "object_id") or raw_type
    # raw_type/name can both be None; coalesce to "" so _slug gets a str.
    object_type = _slug(raw_type or name or "")
    category = _category_for(item, object_type, name)
    return PasteObject(
        tile_x=tx,
        tile_y=ty,
        type=object_type,
        category=category,
        name=_slug(name or object_type),
        level=_read_int(item, "level", "lvl"),
        rotation=_read_int(item, "rotation", "rot") or 0,
        confidence=_read_float(item, "confidence", "score") or 1.0,
        raw=item,
    )


def _to_wall_chain(item: Any) -> WallChain:
    points_source = _field(item, "points")
    if points_source is None:
        points_source = _field(item, "tiles")
    if points_source is None:
        points_source = item

    points = []
    for point in _as_iterable(points_source):
        tx, ty = _tile(point)
        if tx is not None and ty is not None:
            points.append(WallPoint(tx, ty))
    confidence = _read_float(item, "confidence", "score") or 1.0
    return WallChain(tuple(points), raw=item, confidence=confidence)


def _looks_like_wall_chain(item: Any) -> bool:
    if _field(item, "points") is not None or _field(item, "tiles") is not None:
        return True
    if isinstance(item, list):
        return bool(item and _tile(item[0]) != (None, None))
    return False


def _tile(item: Any) -> tuple[int | None, int | None]:
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return _coerce_int(item[0]), _coerce_int(item[1])

    tile = _field(item, "tile")
    if tile is not None:
        tx, ty = _tile(tile)
        if tx is not None and ty is not None:
            return tx, ty

    tx = _read_int(item, "tile_x", "tileX", "x", "tx", "grid_x")
    ty = _read_int(item, "tile_y", "tileY", "y", "ty", "grid_y")
    return tx, ty


def _category_for(item: Any, object_type: str, name: str | None) -> str:
    explicit = _read_str(item, "category", "group")
    if explicit:
        return _slug(explicit)

    haystack = f"{object_type} {_slug(name or '')}"
    if "wall" in haystack:
        return "wall"
    if any(token in haystack for token in _OBSTACLE_TOKENS):
        return "obstacle"
    if any(token in haystack for token in _TRAP_TOKENS):
        return "trap"
    if any(token in haystack for token in _RESOURCE_TOKENS):
        return "resource"
    if any(token in haystack for token in _ARMY_TOKENS):
        return "army"
    if any(token in haystack for token in _DECORATION_TOKENS):
        return "decoration"
    return "defense"


def _field(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _as_iterable(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        return value.values()
    if isinstance(value, (list, tuple, set)):
        return value
    return ()


def _read_str(item: Any, *names: str) -> str | None:
    for name in names:
        value = _field(item, name)
        if value is not None:
            return str(value)
    return None


def _read_int(item: Any, *names: str) -> int | None:
    for name in names:
        value = _field(item, name)
        coerced = _coerce_int(value)
        if coerced is not None:
            return coerced
    return None


def _read_float(item: Any, *names: str) -> float | None:
    for name in names:
        value = _field(item, name)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


_OBSTACLE_TOKENS = {
    "obstacle",
    "tree",
    "trunk",
    "bush",
    "rock",
    "mushroom",
    "gem_box",
}
_TRAP_TOKENS = {
    "trap",
    "bomb",
    "spring",
    "tesla",
    "tornado",
    "seeking_air_mine",
    "air_bomb",
    "skeleton",
}
_RESOURCE_TOKENS = {
    "town_hall",
    "clan_castle",
    "gold",
    "elixir",
    "dark_elixir",
    "storage",
    "collector",
    "mine",
    "drill",
    "treasury",
}
_ARMY_TOKENS = {
    "camp",
    "barracks",
    "laboratory",
    "spell_factory",
    "workshop",
    "pet_house",
    "blacksmith",
    "hero",
    "altar",
}
_DECORATION_TOKENS = {
    "decoration",
    "statue",
    "flag",
    "flower",
    "torch",
    "garden",
}
