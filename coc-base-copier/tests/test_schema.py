"""Schema conformance + round-trip tests."""

from __future__ import annotations

from src.copy.schema import (
    SCHEMA_VERSION,
    VALID_CATEGORIES,
    VALID_ROTATIONS,
    Layout,
    LayoutObject,
    SourceInfo,
    WallChain,
    default_footprint,
)


def _sample_layout() -> Layout:
    return Layout(
        source=SourceInfo(image_id="sha256:deadbeef", image_width=1920, image_height=1080),
        objects=[
            LayoutObject(id="obj_0000", category="defense", type="town_hall",
                         tile_x=20, tile_y=20, level=15, confidence=0.97),
            LayoutObject(id="obj_0001", category="defense", type="cannon",
                         tile_x=10, tile_y=12, level=14, confidence=0.9),
            LayoutObject(id="obj_0002", category="trap", type="giant_bomb",
                         tile_x=30, tile_y=30, level=4, confidence=0.6),
        ],
        wall_chains=[
            WallChain(id="wall_00", tiles=[(5, 5), (6, 5), (7, 5)], level=15, confidence=0.88),
        ],
        town_hall_level=15,
    )


def test_default_footprint_known_and_unknown():
    assert default_footprint("town_hall") == (4, 4)
    assert default_footprint("cannon") == (3, 3)
    assert default_footprint("not_a_real_type") == (1, 1)


def test_object_footprint_defaults_and_trap_flag():
    obj = LayoutObject(id="x", category="trap", type="giant_bomb", tile_x=1, tile_y=1)
    assert obj.footprint == (2, 2)
    assert obj.is_trap is True
    cannon = LayoutObject(id="y", category="defense", type="cannon", tile_x=1, tile_y=1)
    assert cannon.is_trap is False
    assert cannon.rotation == 0


def test_occupied_tiles_uses_footprint_anchor():
    th = LayoutObject(id="th", category="defense", type="town_hall", tile_x=10, tile_y=10)
    tiles = set(th.occupied_tiles())
    assert (10, 10) in tiles and (13, 13) in tiles
    assert len(tiles) == 16  # 4x4


def test_top_level_conformance():
    d = _sample_layout().to_dict()
    # required top-level keys
    for key in ("schema_version", "source", "grid", "objects", "wall_chains",
                "warnings", "stats"):
        assert key in d, f"missing top-level key {key}"
    assert d["schema_version"] == SCHEMA_VERSION
    assert d["stats"]["object_count"] == 3
    assert d["stats"]["trap_count"] == 1
    assert d["stats"]["wall_piece_count"] == 3
    assert d["stats"]["low_confidence_count"] == 1  # the 0.6 trap


def test_object_field_conformance():
    d = _sample_layout().to_dict()
    for obj in d["objects"]:
        for key in ("id", "category", "type", "tile_x", "tile_y", "rotation",
                    "level", "footprint", "is_trap", "confidence"):
            assert key in obj, f"object missing {key}"
        assert obj["category"] in VALID_CATEGORIES
        assert obj["rotation"] in VALID_ROTATIONS
        assert isinstance(obj["footprint"], list) and len(obj["footprint"]) == 2


def test_json_round_trip_is_stable():
    layout = _sample_layout()
    restored = Layout.from_json(layout.to_json())
    # Structural equality (ignoring derived stats, which recompute identically).
    assert restored.to_dict() == layout.to_dict()
    # And serializing twice is byte-identical (idempotent serialization).
    assert layout.to_json() == restored.to_json()


def test_level_null_is_preserved_not_invented():
    obj = LayoutObject(id="z", category="resource", type="gold_mine",
                       tile_x=1, tile_y=1, level=None)
    d = obj.to_dict()
    assert d["level"] is None
    assert LayoutObject.from_dict(d).level is None
