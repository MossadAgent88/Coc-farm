"""Safety guards for the live paster: no off-screen taps, stale/invalid skips,
edit-mode-loss abort, and the --live confirmation gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.paste import cli as paste_cli
from src.paste import editor as paste_editor
from src.paste.editor import (
    EditorModeError,
    EditorSafetyError,
    shop_slot_point_for,
)
from src.paste.layout import LayoutBundle, PasteObject
from src.paste.place import DEFAULT_TARGET_TH, PasteRunner, build_plan
from src.paste.state import PasteState


def _obj(type_, category, tile=(10, 10), conf=0.95, name=None):
    return PasteObject(
        tile_x=tile[0], tile_y=tile[1], type=type_, category=category,
        name=name or type_, level=1, rotation=0, confidence=conf, raw={},
    )


def _bundle(objs):
    return LayoutBundle(
        path=Path("layout.json"), layout=None, raw_json={}, layout_hash="hash",
        town_hall=None, objects=tuple(objs), wall_chains=(),
    )


def _skip_reason(plan):
    assert len(plan) == 1 and plan[0].kind == "skip"
    return plan[0].reason or ""


# ---- 1. off-screen tap is blocked ----

def test_offscreen_tap_is_blocked(monkeypatch):
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(paste_editor, "_raw_tap", lambda x, y, delay=0.1: sent.append((x, y)))

    paste_editor.tap(100, 100)  # on-screen -> allowed
    assert sent == [(100, 100)]

    with pytest.raises(EditorSafetyError):
        paste_editor.tap(2322, 500)  # eagle_artillery slot 11 x -> off-screen
    with pytest.raises(EditorSafetyError):
        paste_editor.tap(500, 1080)  # y == height is out of bounds
    assert sent == [(100, 100)]  # nothing else was sent to the device


def test_offscreen_swipe_and_batch_blocked(monkeypatch):
    monkeypatch.setattr(paste_editor, "_raw_swipe", lambda *a, **k: None)
    monkeypatch.setattr(paste_editor, "_raw_batch_tap", lambda taps: None)
    with pytest.raises(EditorSafetyError):
        paste_editor.swipe(10, 10, 5000, 10)
    with pytest.raises(EditorSafetyError):
        paste_editor.batch_tap([(10, 10, 0.1), (2600, 10, 0.1)])


def test_shop_slot_point_for_rejects_offscreen_slots():
    # cannon slot 1 -> on-screen; eagle_artillery slot 11 -> off-screen (None)
    assert shop_slot_point_for(_obj("cannon", "defense")) is not None
    assert shop_slot_point_for(_obj("eagle_artillery", "defense")) is None
    assert shop_slot_point_for(_obj("x_bow", "defense")) is None  # slot 9


# ---- 2/3. off-screen + stale skips, visible places ----

@pytest.mark.parametrize("type_", ["x_bow", "inferno_tower", "scattershot"])
def test_offscreen_defense_is_skipped_not_tapped(type_):
    # Off-screen (slot 9+) mapped defenses are skipped (not tapped) and marked
    # as requiring horizontal scroll in the dry-run plan.
    plan = build_plan(_bundle([_obj(type_, "defense")]))
    reason = _skip_reason(plan).lower()
    assert "scroll" in reason and "calibration missing" in reason


def test_eagle_artillery_skipped_for_th18():
    plan = build_plan(_bundle([_obj("eagle_artillery", "defense")]), target_th=18)
    reason = _skip_reason(plan).lower()
    assert "invalid/stale" in reason
    assert "th18" in reason
    assert "not pasted" in reason
    assert "off-screen" not in reason


def test_dry_run_preview_uses_target_th18_not_source_town_hall(tmp_path, monkeypatch, capsys):
    layout = tmp_path / "layout.json"
    layout.write_text("{}", encoding="utf-8")
    bundle = LayoutBundle(
        path=layout,
        layout=None,
        raw_json={},
        layout_hash="hash",
        town_hall=15,
        objects=(_obj("eagle_artillery", "defense"),),
        wall_chains=(),
    )
    monkeypatch.setattr(paste_cli, "load_layout", lambda _path: bundle)

    rc = paste_cli.main(["--dry-run", str(layout)])
    out = capsys.readouterr().out.lower()

    assert rc == 0
    assert "invalid/stale" in out
    assert "th18" in out
    assert "not pasted" in out
    assert "off-screen" not in out


def test_visible_defense_still_places():
    plan = build_plan(_bundle([_obj("cannon", "defense")]))
    assert [a.kind for a in plan] == ["place"]


# ---- 6. editor-mode loss aborts immediately, no retry ----

class _EditorLostStub:
    def __init__(self):
        self.place_calls = 0

    def open_shop(self):
        pass

    def tap_shop_category(self, category):
        pass

    def tap_shop_icon(self, obj):
        pass

    def rotate_selected(self, rotation):
        pass

    def place(self, obj):
        self.place_calls += 1
        raise EditorModeError("Not in village editor mode")

    def confirm_level(self, obj):
        pass

    def confirm_placement(self):
        pass


def test_runner_aborts_on_editor_mode_loss_without_retry(tmp_path):
    plan = build_plan(_bundle([_obj("cannon", "defense", (10, 10))]))
    assert [a.kind for a in plan] == ["place"]
    editor = _EditorLostStub()
    state = PasteState(path=tmp_path / "paste_state.json", layout_hash="hash")

    with pytest.raises(EditorModeError):
        PasteRunner(editor, state).run(plan)

    assert editor.place_calls == 1  # aborted immediately, did NOT retry-click


# ---- 4/5. sample JSON cannot live-paste without --live ----

def test_sample_layout_is_detected():
    assert paste_cli._is_sample_layout(Path("samples/test_village.json"))
    assert paste_cli._is_sample_layout(Path("/x/test_village.json"))
    assert not paste_cli._is_sample_layout(Path("/x/my_base.json"))


def test_sample_json_requires_live_flag(tmp_path, monkeypatch, capsys):
    layout = tmp_path / "test_village.json"
    layout.write_text("{}", encoding="utf-8")

    def _boom(*a, **k):
        pytest.fail("paste_layout must not run without --live")

    monkeypatch.setattr(paste_cli, "paste_layout", _boom)

    rc = paste_cli.main([str(layout)])  # no --live
    out = capsys.readouterr().out
    assert rc == 0
    assert "SAMPLE" in out
    assert "Safe mode" in out and "--live" in out

