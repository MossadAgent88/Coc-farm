"""Complementary schema coverage — pure functions only, no device/API.

Existing `test_schema.py` already covers the 4x4 town_hall occupied_tiles case
and a basic round-trip. These tests add:
  - occupied_tiles() for 3x3, 2x2, and 1x1 footprints (the remaining shapes).
  - BUILDING_FOOTPRINTS completeness: every key in KNOWN_TYPES has an entry,
    and the set matches the canonical type list documented in
    docs/layout-schema.md section 6.
  - A fuller Layout.from_json/to_json round-trip exercising every nested
    dataclass (SourceInfo, GridInfo, LayoutObject, WallChain) including the
    pixel_x/pixel_y + footprint_w/footprint_h fields added in schema v1.1.0.
"""

from __future__ import annotations

import json

from src.copy.schema import (
    BUILDING_FOOTPRINTS,
    GridInfo,
    KNOWN_TYPES,
    Layout,
    LayoutObject,
    SCHEMA_VERSION,
    SourceInfo,
    WallChain,
)


# ---------------------------------------------------------------------------
# occupied_tiles() across footprint sizes
# ---------------------------------------------------------------------------


def test_occupied_tiles_3x3_defense():
    cannon = LayoutObject(
        id="c1", category="defense", type="cannon", tile_x=10, tile_y=20
    )
    assert cannon.footprint == (3, 3)
    tiles = set(cannon.occupied_tiles())
    # anchor is the top tile; footprint spans anchor..anchor+w-1 / +h-1
    assert (10, 20) in tiles
    assert (12, 22) in tiles  # bottom-right
    assert (9, 20) not in tiles  # one left of anchor
    assert len(tiles) == 9


def test_occupied_tiles_2x2_trap():
    gb = LayoutObject(
        id="gb1", category="trap", type="giant_bomb", tile_x=5, tile_y=5
    )
    assert gb.footprint == (2, 2)
    tiles = set(gb.occupied_tiles())
    assert tiles == {(5, 5), (5, 6), (6, 5), (6, 6)}


def test_occupied_tiles_1x1_trap():
    bomb = LayoutObject(id="b1", category="trap", type="bomb", tile_x=0, tile_y=0)
    assert bomb.footprint == (1, 1)
    assert set(bomb.occupied_tiles()) == {(0, 0)}


# ---------------------------------------------------------------------------
# BUILDING_FOOTPRINTS completeness
# ---------------------------------------------------------------------------


def test_building_footprints_covers_every_known_type():
    """Every canonical type in KNOWN_TYPES must have a footprint entry."""
    missing = [t for t in KNOWN_TYPES if t not in BUILDING_FOOTPRINTS]
    assert not missing, f"types missing from BUILDING_FOOTPRINTS: {missing}"


def test_building_footprints_match_known_types_values():
    """BUILDING_FOOTPRINTS values must equal the (w,h) from KNOWN_TYPES."""
    for t, (w, h) in BUILDING_FOOTPRINTS.items():
        assert KNOWN_TYPES[t][:2] == (w, h), f"footprint mismatch for {t}"


def test_canonical_type_list_matches_schema_doc():
    """Cross-reference KNOWN_TYPES keys against the type list the README/docs
    promise. These are the canonical keys enumerated in layout-schema.md §6
    (excluding 'wall', which lives only in wall_chains and intentionally has
    no building footprint)."""
    documented = {
        "town_hall", "cannon", "archer_tower", "mortar", "wizard_tower",
        "air_defense", "x_bow", "inferno_tower", "eagle_artillery",
        "scattershot", "bomb_tower", "air_sweeper", "monolith", "spell_tower",
        "gold_mine", "elixir_collector", "dark_elixir_drill", "gold_storage",
        "elixir_storage", "dark_elixir_storage", "clan_castle", "army_camp",
        "barracks", "dark_barracks", "laboratory", "spell_factory",
        "pet_house", "blacksmith", "king_altar", "queen_altar",
        "warden_altar", "champion_altar", "minion_prince_altar", "builder_hut",
        # traps (§5) are also canonical types with footprints:
        "bomb", "spring_trap", "giant_bomb", "air_bomb", "seeking_air_mine",
        "skeleton_trap", "tornado_trap",
    }
    keys = set(KNOWN_TYPES)
    # everything documented must be known
    missing_from_known = documented - keys
    assert not missing_from_known, (
        f"documented types missing from KNOWN_TYPES: {sorted(missing_from_known)}"
    )


# ---------------------------------------------------------------------------
# Full round-trip exercising v1.1.0 fields
# ---------------------------------------------------------------------------


def _full_layout() -> Layout:
    return Layout(
        source=SourceInfo(
            kind="device",
            image_id="sha256:abc",
            captured_at="2026-06-22T00:00:00Z",
            image_width=1920,
            image_height=1080,
        ),
        grid=GridInfo(
            size=44,
            corners_px={
                "top": (960.0, 120.0),
                "right": (1700.0, 540.0),
                "bottom": (960.0, 960.0),
                "left": (220.0, 540.0),
            },
            corner_confidence=0.94,
        ),
        objects=[
            LayoutObject(
                id="obj_0000",
                category="defense",
                type="town_hall",
                tile_x=20,
                tile_y=20,
                level=15,
                confidence=0.78,
                original_confidence=0.65,
                notes="confidence calibrated from 0.65 to 0.78",
                pixel_x=960.0,
                pixel_y=540.0,
            ),
            LayoutObject(
                id="obj_0001",
                category="trap",
                type="spring_trap",
                tile_x=30,
                tile_y=30,
                confidence=0.55,
                pixel_x=1100.0,
                pixel_y=620.0,
            ),
        ],
        wall_chains=[
            WallChain(
                id="wall_00",
                tiles=[(5, 5), (6, 5), (7, 5)],
                level=15,
                closed=False,
                confidence=0.88,
            ),
        ],
        town_hall_level=15,
        warnings=["traps not visible in normal view"],
    )


def test_full_layout_roundtrip_preserves_v1_1_0_fields():
    layout = _full_layout()
    serialized = layout.to_json()
    # the serialized blob advertises the current schema version
    assert json.loads(serialized)["schema_version"] == SCHEMA_VERSION

    restored = Layout.from_json(serialized)
    # idempotent: re-serializing is byte-identical
    assert restored.to_json() == serialized
    # pixel + footprint mirrors survive the round-trip
    obj = next(o for o in restored.objects if o.id == "obj_0000")
    assert obj.pixel_x == 960.0 and obj.pixel_y == 540.0
    assert obj.original_confidence == 0.65
    assert obj.notes == "confidence calibrated from 0.65 to 0.78"
    d = obj.to_dict()
    assert d["original_confidence"] == 0.65
    assert d["footprint"] == [4, 4]
    assert d["footprint_w"] == 4 and d["footprint_h"] == 4
    # grid corners survive (list<->tuple coercion)
    assert restored.grid.corners_px is not None
    assert restored.grid.corners_px["top"] == (960.0, 120.0)
    # wall chain survives
    assert restored.wall_chains[0].tiles == [(5, 5), (6, 5), (7, 5)]
    # low-confidence object is counted in stats
    assert restored.stats()["low_confidence_count"] == 1


def test_layout_to_dict_has_all_top_level_keys():
    d = _full_layout().to_dict()
    for key in (
        "schema_version",
        "source",
        "town_hall_level",
        "grid",
        "objects",
        "wall_chains",
        "warnings",
        "stats",
    ):
        assert key in d, f"missing top-level key {key}"
    assert d["stats"]["object_count"] == 2
    assert d["stats"]["wall_piece_count"] == 3
    assert d["stats"]["trap_count"] == 1
