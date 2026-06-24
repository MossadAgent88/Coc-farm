"""Pure calibration schema + scroll-math tests (no device/Windows imports)."""

from __future__ import annotations

import pytest

from src.paste.calibrate import (
    ShopScrollCalibration,
    load_calibration,
    point_for_slot,
    save_calibration,
    steps_needed,
    swipe_points,
    visible_window_start,
)


def _cal(**over):
    base = dict(
        screen_width=1920, screen_height=1080,
        strip_x_min=90, strip_x_max=1830,
        strip_y_min=930, strip_y_max=1010,
        visible_slot_count=9, first_slot_x=105, slot_y=965, slot_width=202,
        swipe_start_x=1700, swipe_end_x=300,
        slots_per_swipe=4, swipe_duration_ms=450, max_scroll_steps=12,
        verified=True,
    )
    base.update(over)
    return ShopScrollCalibration(**base)


def test_valid_calibration_has_no_errors():
    assert _cal().validate() == []


def test_validate_rejects_offscreen_values():
    assert _cal(swipe_start_x=2500).validate()      # x >= width
    assert _cal(slot_y=2000).validate()             # y >= height
    assert _cal(slots_per_swipe=0).validate()       # must be positive
    assert _cal(strip_x_min=1000, strip_x_max=900).validate()  # min<max


def test_load_missing_returns_none(tmp_path):
    assert load_calibration(tmp_path / "nope.json") is None


def test_load_unverified_draft_returns_none(tmp_path):
    path = tmp_path / "cal.json"
    save_calibration(_cal(verified=False), path)
    assert load_calibration(path) is None  # safety gate: draft never activates


def test_load_invalid_returns_none(tmp_path):
    path = tmp_path / "cal.json"
    save_calibration(_cal(verified=True, swipe_start_x=9999), path)
    assert load_calibration(path) is None


def test_load_roundtrip_verified(tmp_path):
    path = tmp_path / "cal.json"
    cal = _cal(verified=True)
    save_calibration(cal, path)
    loaded = load_calibration(path)
    assert loaded is not None
    assert loaded.slots_per_swipe == 4 and loaded.verified is True


def test_visible_slots_0_8_at_step_zero():
    cal = _cal()
    for slot in range(9):
        assert point_for_slot(slot, 0, cal) is not None
    assert point_for_slot(9, 0, cal) is None  # x_bow not visible without scroll


def test_point_for_slot_is_always_in_bounds_and_in_strip():
    cal = _cal()
    for slot in range(0, 40):
        steps = steps_needed(slot, cal)
        if steps is None:
            continue
        x, y = point_for_slot(slot, steps, cal)
        assert 0 <= x < cal.screen_width and 0 <= y < cal.screen_height
        assert cal.strip_x_min <= x <= cal.strip_x_max
        assert cal.strip_y_min <= y <= cal.strip_y_max


def test_steps_needed_reaches_offscreen_slots():
    cal = _cal()
    # slot 11 (eagle's old slot / inferno=10, x_bow=9, scattershot=12 region)
    assert steps_needed(10, cal) is not None
    assert steps_needed(12, cal) is not None
    assert visible_window_start(steps_needed(12, cal), cal) <= 12


def test_steps_needed_unreachable_returns_none():
    cal = _cal(max_scroll_steps=1)  # only 0 or 1 swipe -> window start 0 or 4
    assert steps_needed(99, cal) is None


def test_swipe_points_in_bounds():
    cal = _cal()
    x1, y1, x2, y2 = swipe_points(cal)
    for x, y in ((x1, y1), (x2, y2)):
        assert 0 <= x < cal.screen_width and 0 <= y < cal.screen_height
        assert cal.strip_x_min <= x <= cal.strip_x_max
