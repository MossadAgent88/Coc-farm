"""Unsupported objects (no shop-slot mapping) skip safely instead of crashing.

Covers the town_hall blocker and decorations/obstacles/odd names: build_plan
turns them into skip actions, and the runner continues past them while still
placing mapped defenses.
"""

from __future__ import annotations

from pathlib import Path

from src.paste.layout import LayoutBundle, PasteObject
from src.paste.place import PasteRunner, build_plan
from src.paste.state import PasteState


def _obj(type_, category, tile=(10, 10), conf=0.95, name=None):
    return PasteObject(
        tile_x=tile[0],
        tile_y=tile[1],
        type=type_,
        category=category,
        name=name or type_,
        level=1,
        rotation=0,
        confidence=conf,
        raw={},
    )


def _bundle(objs):
    return LayoutBundle(
        path=Path("layout.json"),
        layout=None,
        raw_json={},
        layout_hash="hash",
        town_hall=None,
        objects=tuple(objs),
        wall_chains=(),
    )


def _kind_by_type(plan):
    return {a.obj.type: a.kind for a in plan if a.obj is not None}


def test_town_hall_is_skipped_not_placed():
    plan = build_plan(_bundle([_obj("cannon", "defense"), _obj("town_hall", "resource", (20, 20))]))
    kinds = _kind_by_type(plan)
    assert kinds["town_hall"] == "skip"
    assert kinds["cannon"] == "place"


def test_unsupported_types_are_skipped_not_crashed():
    # town_hall, decorations, seasonal obstacles, and both builder_hut spellings.
    unsupported = [
        ("town_hall", "resource"),
        ("snowman", "decoration"),
        ("boat", "decoration"),
        ("gem_box", "obstacle"),
        ("christmas_tree", "decoration"),
        ("barbarian_statue", "decoration"),
        ("decoration", "decoration"),
        ("builder_hut", "army"),
        ("builders_hut", "army"),
    ]
    for type_, category in unsupported:
        plan = build_plan(_bundle([_obj(type_, category, (5, 5))]))
        assert [a.kind for a in plan if a.obj] == ["skip"], f"{type_} should skip"


def test_known_mapped_defenses_still_place():
    # Only slots 0..8 are on-screen at 1920x1080 (105 + col*202). Higher slots
    # (x_bow 9, inferno 10, eagle 11, scattershot 12, ...) are off-screen and are
    # intentionally skipped now; see test_paste_safety.py.
    for type_ in (
        "cannon", "archer_tower", "mortar", "air_defense", "wizard_tower",
        "air_sweeper", "bomb_tower", "hidden_tesla",
    ):
        plan = build_plan(_bundle([_obj(type_, "defense")]))
        assert [a.kind for a in plan] == ["place"], f"{type_} should place"


def test_slot_zero_mapped_types_still_place():
    # Regression: slot 0 is valid; these must not be treated as unmapped even
    # when the object's name is a detector id (e.g. "obj_0000") rather than the
    # type. Covers gold_mine (resource), army_camp (army), bomb (trap).
    cases = [("gold_mine", "resource"), ("army_camp", "army"), ("bomb", "trap")]
    for type_, category in cases:
        obj = _obj(type_, category, name="obj_0000")
        plan = build_plan(_bundle([obj]))
        assert [a.kind for a in plan] == ["place"], f"{type_} should place"


class _StubEditor:
    """Records placements; never raises for mapped types (no real ADB)."""

    def __init__(self):
        self.placed_types: list[str] = []

    def ensure_trap_mode(self):  # pragma: no cover - traps not in this test
        pass

    def open_shop(self):
        pass

    def tap_shop_category(self, category):
        pass

    def tap_shop_icon(self, obj):
        pass

    def rotate_selected(self, rotation):
        pass

    def place(self, obj):
        self.placed_types.append(obj.type)

    def confirm_level(self, obj):
        pass

    def confirm_placement(self):
        pass


def test_runner_continues_past_skips_and_places_supported(tmp_path):
    plan = build_plan(
        _bundle([
            _obj("cannon", "defense", (10, 10)),
            _obj("town_hall", "resource", (20, 20)),
            _obj("snowman", "decoration", (5, 5)),
        ])
    )
    editor = _StubEditor()
    state = PasteState(path=tmp_path / "paste_state.json", layout_hash="hash")

    summary = PasteRunner(editor, state).run(plan)  # must not raise

    assert summary.placed == 1
    assert summary.skipped == 2
    assert summary.failed == 0
    assert editor.placed_types == ["cannon"]
