"""Footprint-aware, robust placement (schema v1.1.0).

Vision returns pixel centers; the detector converts to tiles, centers each
type's footprint, clamps in-bounds, and nudges/skips overlaps instead of
hard-failing the whole layout.
"""

from __future__ import annotations

import pytest

from src.copy.detect import DetectionError, detect
from src.copy.schema import BUILDING_FOOTPRINTS, MAX_TILE, default_footprint
from tests.conftest import FakeTransport, detection


def _payload(dets, view="editor", th_level=15):
    return {"view": view, "town_hall_level": th_level, "detections": dets}


def test_building_footprints_table():
    assert BUILDING_FOOTPRINTS["cannon"] == (3, 3)
    assert BUILDING_FOOTPRINTS["town_hall"] == (4, 4)
    assert default_footprint("cannon") == (3, 3)
    assert default_footprint("totally_unknown") == (1, 1)


def test_footprint_centered_on_center_tile(screenshot_path, grid):
    dets = [
        detection(grid, (20, 20), "town_hall", "defense", conf=0.97),
        detection(grid, (10, 10), "cannon", "defense", conf=0.95),
    ]
    layout = detect(screenshot_path, transport=FakeTransport(_payload(dets)), grid=grid)
    cannon = next(o for o in layout.objects if o.type == "cannon")
    # 3x3 centered on (10,10) -> anchor 10-(3-1)//2 = 9
    assert cannon.footprint == (3, 3)
    assert (cannon.tile_x, cannon.tile_y) == (9, 9)
    # raw pixel center + footprint scalars are persisted in the JSON
    d = cannon.to_dict()
    assert d["pixel_x"] is not None and d["pixel_y"] is not None
    assert d["footprint_w"] == 3 and d["footprint_h"] == 3
    assert layout.schema_version == "1.1.0"


def test_out_of_bounds_is_clamped_not_rejected(screenshot_path, grid):
    dets = [
        detection(grid, (20, 20), "town_hall", "defense", conf=0.97),
        detection(grid, (43, 21), "air_defense", "defense", conf=0.95),
    ]
    layout = detect(screenshot_path, transport=FakeTransport(_payload(dets)), grid=grid)
    ad = next(o for o in layout.objects if o.type == "air_defense")
    for tx, ty in ad.occupied_tiles():
        assert 0 <= tx <= MAX_TILE and 0 <= ty <= MAX_TILE
    assert ad.tile_x == MAX_TILE - 3 + 1  # 41: 3x3 clamped against the edge


def test_overlap_resolved_by_nudge(screenshot_path, grid):
    # centers 2 apart: B overlaps A, but a 1-tile nudge separates them.
    dets = [
        detection(grid, (20, 20), "town_hall", "defense", conf=0.97),
        detection(grid, (10, 10), "cannon", "defense", conf=0.95),
        detection(grid, (12, 10), "cannon", "defense", conf=0.95),
    ]
    layout = detect(screenshot_path, transport=FakeTransport(_payload(dets)), grid=grid)
    assert sum(o.type == "cannon" for o in layout.objects) == 2  # both kept
    tiles = [t for o in layout.objects for t in o.occupied_tiles()]
    assert len(tiles) == len(set(tiles))  # no overlaps remain


def test_too_many_unplaceable_buildings_fails(screenshot_path, grid):
    # three cannons stacked on the same center can't be separated by 1-tile nudges
    dets = [
        detection(grid, (20, 20), "town_hall", "defense", conf=0.97),
        detection(grid, (10, 10), "cannon", "defense", conf=0.95),
        detection(grid, (10, 10), "cannon", "defense", conf=0.95),
        detection(grid, (10, 10), "cannon", "defense", conf=0.95),
    ]
    with pytest.raises(DetectionError) as exc:
        detect(screenshot_path, transport=FakeTransport(_payload(dets)), grid=grid)
    assert "skipped" in str(exc.value).lower()


def test_wall_on_building_is_skipped_not_failed(screenshot_path, grid):
    dets = [
        detection(grid, (20, 20), "town_hall", "defense", conf=0.97),
        detection(grid, (20, 20), "wall", "defense", conf=0.9),  # inside TH footprint
        detection(grid, (5, 5), "wall", "defense", conf=0.9),    # free
    ]
    layout = detect(screenshot_path, transport=FakeTransport(_payload(dets)), grid=grid)
    wall_tiles = {t for c in layout.wall_chains for t in c.tiles}
    assert (5, 5) in wall_tiles          # free wall kept
    assert (20, 20) not in wall_tiles    # colliding wall skipped
    assert any("skipped wall" in w.lower() for w in layout.warnings)
