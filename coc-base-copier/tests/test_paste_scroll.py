"""Editor-side calibrated scroll behavior + dry-run classification.

These import src.paste.editor (which pulls cocbot.io / Windows) so they run on
the target machine. The pure scroll math is covered separately in
test_shop_scroll_calibration.py (runs anywhere).
"""

from __future__ import annotations

import pytest

import src.paste.editor as editor
from src.paste.calibrate import ShopScrollCalibration
from src.paste.editor import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    EditorModeError,
    EditorSession,
    _shop_slot_point,
    _slot_is_visible,
)
from src.paste.layout import LayoutBundle, PasteObject
from src.paste.place import build_plan


def _cal(**over):
    base = dict(
        screen_width=1920, screen_height=1080,
        strip_x_min=90, strip_x_max=1830, strip_y_min=930, strip_y_max=1010,
        visible_slot_count=9, first_slot_x=105, slot_y=965, slot_width=202,
        swipe_start_x=1700, swipe_end_x=300,
        slots_per_swipe=4, swipe_duration_ms=450, max_scroll_steps=12,
        verified=True,
    )
    base.update(over)
    return ShopScrollCalibration(**base)


def _obj(type_):
    return PasteObject(tile_x=0, tile_y=0, type=type_, category="defense",
                       name=type_, level=1, rotation=0, confidence=0.95, raw={})


def _session(monkeypatch, *, cal=None, edit_ok=True):
    s = EditorSession()
    s._scroll_calibration = cal
    if edit_ok:
        monkeypatch.setattr(s, "assert_edit_mode", lambda: None)
    return s


def test_visible_slot_returns_point_without_swiping(monkeypatch):
    swipes: list = []
    monkeypatch.setattr(editor, "swipe", lambda *a, **k: swipes.append(a))
    s = _session(monkeypatch, cal=_cal())
    assert s.ensure_shop_slot_visible(1, "cannon") == _shop_slot_point(1)
    assert swipes == []


def test_uncalibrated_offscreen_slot_skips_without_tap(monkeypatch):
    swipes: list = []
    monkeypatch.setattr(editor, "swipe", lambda *a, **k: swipes.append(a))
    monkeypatch.setattr("src.paste.calibrate.load_calibration", lambda *a, **k: None)
    s = _session(monkeypatch, cal=None)
    assert s.ensure_shop_slot_visible(11, "eagle_artillery") is None
    assert swipes == []


def test_calibrated_scroll_returns_inbounds_point(monkeypatch):
    swipes: list = []
    monkeypatch.setattr(
        editor, "swipe",
        lambda x1, y1, x2, y2, duration_ms=0: swipes.append((x1, y1, x2, y2)),
    )
    s = _session(monkeypatch, cal=_cal())
    point = s.ensure_shop_slot_visible(10, "inferno_tower")  # slot 10
    assert point is not None
    px, py = point
    assert 0 <= px < SCREEN_WIDTH and 0 <= py < SCREEN_HEIGHT
    assert len(swipes) >= 1
    for x1, y1, x2, y2 in swipes:
        for x, y in ((x1, y1), (x2, y2)):
            assert 0 <= x < SCREEN_WIDTH and 0 <= y < SCREEN_HEIGHT


def test_calibrated_scroll_aborts_on_edit_mode_loss(monkeypatch):
    monkeypatch.setattr(editor, "swipe", lambda *a, **k: None)
    s = EditorSession()
    s._scroll_calibration = _cal()

    def _lost():
        raise EditorModeError("editor mode lost during scroll")

    monkeypatch.setattr(s, "assert_edit_mode", _lost)
    with pytest.raises(EditorModeError):
        s.ensure_shop_slot_visible(10, "inferno_tower")


def test_calibrated_scroll_unreachable_skips(monkeypatch):
    monkeypatch.setattr(editor, "swipe", lambda *a, **k: None)
    # only 1 swipe possible -> window start 0 or 4 -> slot 99 unreachable
    s = _session(monkeypatch, cal=_cal(max_scroll_steps=1))
    assert s.ensure_shop_slot_visible(99, "x_bow") is None


def test_offscreen_defenses_never_produce_out_of_bounds_point():
    from src.paste.editor import shop_slot_point_for
    for t in ("inferno_tower", "x_bow", "scattershot", "spell_tower", "monolith"):
        assert shop_slot_point_for(_obj(t)) is None  # never an x > screen width


# ---- dry-run classification distinguishes the calibration states ----

def _bundle(objs):
    from pathlib import Path
    return LayoutBundle(path=Path("layout.json"), layout=None, raw_json={},
                        layout_hash="h", town_hall=None, objects=tuple(objs),
                        wall_chains=())


def test_dry_run_calibration_missing_marks_requires_scroll(monkeypatch):
    monkeypatch.setattr("src.paste.calibrate.load_calibration", lambda *a, **k: None)
    plan = build_plan(_bundle([_obj("inferno_tower")]))
    assert len(plan) == 1 and plan[0].kind == "skip"
    r = (plan[0].reason or "").lower()
    assert "scroll" in r and "calibration missing" in r


def test_dry_run_calibrated_reachable_marks_place(monkeypatch):
    monkeypatch.setattr("src.paste.calibrate.load_calibration", lambda *a, **k: _cal())
    plan = build_plan(_bundle([_obj("inferno_tower")]))
    assert [a.kind for a in plan] == ["place"]  # calibrated-scrollable -> place


def test_eagle_still_skips_at_th18_even_when_calibrated(monkeypatch):
    monkeypatch.setattr("src.paste.calibrate.load_calibration", lambda *a, **k: _cal())
    plan = build_plan(_bundle([_obj("eagle_artillery")]), target_th=18)
    assert len(plan) == 1 and plan[0].kind == "skip"
    assert "stale" in (plan[0].reason or "").lower()


def test_slot_visibility_helpers():
    assert _slot_is_visible(0) and _slot_is_visible(8)
    assert not _slot_is_visible(9)
