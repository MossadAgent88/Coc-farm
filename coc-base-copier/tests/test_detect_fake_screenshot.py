"""End-to-end detector test on a fake screenshot with an injected vision model.

No network, no API key: a synthetic diamond image drives real grid registration,
and a FakeTransport supplies the building list.
"""

from __future__ import annotations

import pytest

from src.copy.detect import DetectionError, detect
from src.copy.schema import SCHEMA_VERSION, Layout
from tests.conftest import FakeTransport, detection


def _good_payload(grid):
    return {
        "view": "editor",
        "town_hall_level": 15,
        "detections": [
            detection(grid, (20, 20), "town_hall", "defense", level=15, conf=0.98),
            detection(grid, (10, 12), "cannon", "defense", level=14, conf=0.93),
            detection(grid, (30, 8), "air_defense", "defense", level=11, conf=0.9),
            # two adjacent wall pieces -> one chain
            detection(grid, (15, 30), "wall", "defense", level=15, conf=0.9),
            detection(grid, (16, 30), "wall", "defense", level=15, conf=0.9),
        ],
    }


def test_full_pipeline_produces_valid_layout(screenshot_path, grid):
    transport = FakeTransport(_good_payload(grid))
    layout = detect(screenshot_path, transport=transport)

    assert isinstance(layout, Layout)
    assert layout.schema_version == SCHEMA_VERSION
    assert layout.town_hall_level == 15

    types = [o.type for o in layout.objects]
    assert types.count("town_hall") == 1
    assert "cannon" in types and "air_defense" in types
    # walls are NOT objects
    assert "wall" not in types

    assert len(layout.wall_chains) == 1
    assert set(layout.wall_chains[0].tiles) == {(15, 30), (16, 30)}

    # round-trips through JSON
    assert Layout.from_json(layout.to_json()).to_dict() == layout.to_dict()


def test_idempotent_content(screenshot_path, grid):
    """Same screenshot + same vision output -> same detected content."""
    a = detect(screenshot_path, transport=FakeTransport(_good_payload(grid)))
    b = detect(screenshot_path, transport=FakeTransport(_good_payload(grid)))

    def content(layout):
        d = layout.to_dict()
        d["source"].pop("captured_at", None)  # timestamp is the only volatile field
        return d

    assert content(a) == content(b)
    assert a.source.image_id == b.source.image_id  # stable hash of identical bytes


def test_missing_town_hall_raises_after_retries(screenshot_path, grid):
    payload = {
        "view": "editor",
        "detections": [detection(grid, (10, 10), "cannon", "defense", conf=0.95)],
    }
    transport = FakeTransport(payload)
    with pytest.raises(DetectionError) as exc:
        detect(screenshot_path, transport=transport)
    assert "town_hall" in str(exc.value)
    assert exc.value.layout is not None  # best-effort layout is attached
    assert transport.calls == 3  # 1 try + 2 retries


def test_low_confidence_is_flagged_not_dropped(screenshot_path, grid):
    payload = {
        "view": "editor",
        "town_hall_level": 13,
        "detections": [
            detection(grid, (20, 20), "town_hall", "defense", level=13, conf=0.98),
            detection(grid, (8, 8), "mortar", "defense", level=9, conf=0.49),  # low
        ],
    }
    transport = FakeTransport(payload)
    layout = detect(screenshot_path, transport=transport)
    # building is NOT dropped...
    assert any(o.type == "mortar" for o in layout.objects)
    # ...it is surfaced as a warning, and vision was re-asked the max times.
    assert transport.calls == 3
    assert any("confidence" in w.lower() for w in layout.warnings)
    assert layout.low_confidence_count() == 1


def test_known_building_confidence_is_calibrated_and_accepted(screenshot_path, grid):
    payload = {
        "view": "editor",
        "town_hall_level": 13,
        "detections": [
            detection(grid, (20, 20), "town_hall", "defense", level=13, conf=0.98),
            detection(grid, (8, 8), "cannon", "defense", level=9, conf=0.65),
        ],
    }
    transport = FakeTransport(payload)
    layout = detect(screenshot_path, transport=transport)

    cannon = next(o for o in layout.objects if o.type == "cannon")
    assert transport.calls == 1
    assert cannon.confidence >= 0.75
    assert cannon.confidence <= 0.85
    assert cannon.original_confidence == 0.65
    assert cannon.notes is not None
    assert "confidence calibrated" in cannon.notes
    assert layout.low_confidence_count() == 0
    assert any("confidence calibrated" in w.lower() for w in layout.warnings)


@pytest.mark.parametrize(
    ("type_key", "category"),
    [
        ("barbarian_statue", "decoration"),
        ("tree", "obstacle"),
    ],
)
def test_non_actionable_low_confidence_is_not_calibrated(
    screenshot_path, grid, type_key, category
):
    payload = {
        "view": "editor",
        "town_hall_level": 13,
        "detections": [
            detection(grid, (20, 20), "town_hall", "defense", level=13, conf=0.98),
            detection(grid, (8, 8), type_key, category, level=None, conf=0.65),
        ],
    }
    transport = FakeTransport(payload)
    layout = detect(screenshot_path, transport=transport)

    obj = next(o for o in layout.objects if o.type == type_key)
    assert transport.calls == 3
    assert obj.confidence == 0.65
    assert obj.original_confidence is None
    assert not (obj.notes and "confidence calibrated" in obj.notes)
    assert layout.low_confidence_count() == 1


def test_normal_view_warns_about_traps(screenshot_path, grid):
    payload = {
        "view": "normal",
        "town_hall_level": 12,
        "detections": [
            detection(grid, (20, 20), "town_hall", "defense", level=12, conf=0.97),
        ],
    }
    layout = detect(screenshot_path, transport=FakeTransport(payload))
    assert any("trap" in w.lower() for w in layout.warnings)


def test_unknown_type_is_kept_and_warned(screenshot_path, grid):
    payload = {
        "view": "editor",
        "town_hall_level": 16,
        "detections": [
            detection(grid, (20, 20), "town_hall", "defense", level=16, conf=0.97),
            detection(grid, (5, 5), "frostmancer_tower", "defense", level=1, conf=0.9),
        ],
    }
    layout = detect(screenshot_path, transport=FakeTransport(payload))
    assert any(o.type == "frostmancer_tower" for o in layout.objects)
    assert any("frostmancer_tower" in w for w in layout.warnings)
