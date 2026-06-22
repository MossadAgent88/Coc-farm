"""Placement planning and dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from loguru import logger

from src.paste.layout import LayoutBundle, PasteObject, WallChain, load_layout
from src.paste.state import PasteState, install_flush_handlers

if TYPE_CHECKING:
    from src.paste.editor import EditorSession

MAX_RETRIES = 3
DEFAULT_TARGET_TH = 18
# type -> minimum target TH at which this building is stale/invalid as a
# standalone shop item and must be skipped rather than pasted (e.g. a detector
# label that no longer maps to a real, separately-placeable building).
STALE_AT_TH = {"eagle_artillery": 17}
PLACE_ORDER = {
    "defense": 0,
    "resource": 1,
    "army": 2,
    "decoration": 3,
    "wall": 4,
    "trap": 5,
    "obstacle": 6,
}


class PasteExecutionError(RuntimeError):
    """Raised when a placement cannot be completed."""


@dataclass(frozen=True)
class PlacementAction:
    kind: str
    key: str
    obj: PasteObject | None = None
    wall_chain: WallChain | None = None
    reason: str | None = None

    @property
    def tile_x(self) -> int:
        if self.obj:
            return self.obj.tile_x
        if self.wall_chain and self.wall_chain.points:
            return self.wall_chain.points[0].tile_x
        return -1

    @property
    def tile_y(self) -> int:
        if self.obj:
            return self.obj.tile_y
        if self.wall_chain and self.wall_chain.points:
            return self.wall_chain.points[0].tile_y
        return -1

    @property
    def type(self) -> str:
        if self.obj:
            return self.obj.type
        if self.wall_chain:
            return "wall_chain"
        return "skip"


@dataclass(frozen=True)
class PasteSummary:
    placed: int
    skipped: int
    failed: int


class PasteRunner:
    def __init__(
        self,
        editor: EditorSession,
        state: PasteState,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self.editor = editor
        self.state = state
        self.max_retries = max_retries

    def run(self, actions: Iterable[PlacementAction]) -> PasteSummary:
        placed = skipped = failed = 0
        # Editor-mode loss and refused off-screen taps are FATAL: stop at once,
        # never keep clicking. Imported lazily (editor pulls cv2/numpy).
        from src.paste.editor import EditorModeError, EditorSafetyError

        fatal_errors = (EditorModeError, EditorSafetyError)
        try:
            for action in actions:
                if self.state.is_complete(action.key):
                    logger.info(f"Already completed {action.key}; skipping resume duplicate")
                    continue
                if action.kind == "skip":
                    logger.warning(f"Skipping {action.type} at {action.tile_x},{action.tile_y}: {action.reason}")
                    self._record(action, "skipped", self.state.retry_count(action.key))
                    skipped += 1
                    continue

                retry_count = self.state.retry_count(action.key)
                while retry_count < self.max_retries:
                    try:
                        self._perform(action)
                        self._record(action, "placed", retry_count)
                        placed += 1
                        break
                    except KeyboardInterrupt:
                        self.state.flush()
                        raise
                    except fatal_errors as exc:
                        # Editor mode lost or an unsafe/off-screen tap was refused:
                        # STOP now. Do NOT retry by clicking more random places.
                        logger.error(
                            f"Aborting paste (no retry) on {action.key}: {exc}"
                        )
                        self._record(action, "failed", retry_count, str(exc))
                        self.state.flush()
                        raise
                    except Exception as exc:
                        retry_count += 1
                        failed += 1
                        logger.warning(
                            f"Placement failed for {action.key} "
                            f"(retry {retry_count}/{self.max_retries}): {exc}"
                        )
                        self._record(action, "failed", retry_count, str(exc))
                        if retry_count >= self.max_retries:
                            raise PasteExecutionError(
                                f"Placement failed after {self.max_retries} retries: {action.key}"
                            ) from exc
        finally:
            self.state.flush()
        return PasteSummary(placed=placed, skipped=skipped, failed=failed)

    def _perform(self, action: PlacementAction) -> None:
        if action.kind == "wall_chain":
            if action.wall_chain is None:
                raise PasteExecutionError("Wall-chain action missing chain")
            self.editor.select_wall_tool()
            self.editor.place_wall_chain(action.wall_chain)
            return
        if action.kind == "place":
            if action.obj is None:
                raise PasteExecutionError("Placement action missing object")
            place_object(self.editor, action.obj)
            return
        raise PasteExecutionError(f"Unknown placement action kind: {action.kind}")

    def _record(
        self,
        action: PlacementAction,
        status: str,
        retry_count: int,
        error: str | None = None,
    ) -> None:
        self.state.append(
            key=action.key,
            tile_x=action.tile_x,
            tile_y=action.tile_y,
            type=action.type,
            status=status,  # type: ignore[arg-type]
            retry_count=retry_count,
            error=error,
        )


def build_plan(
    layout: LayoutBundle, *, target_th: int = DEFAULT_TARGET_TH
) -> list[PlacementAction]:
    # Imported lazily (editor pulls cv2/numpy). Reusing the editor's own lookup
    # keeps "is this placeable?" identical to what the editor will actually do,
    # so we never plan a placement the editor would later refuse or a tap that
    # would land off-screen.
    from src.paste.editor import _shop_slot_from_object, shop_slot_point_for

    actions: list[PlacementAction] = []
    for obj in sorted(layout.objects, key=_object_sort_key):
        if obj.is_wall:
            continue
        if obj.is_obstacle:
            actions.append(
                PlacementAction(
                    kind="skip",
                    key=obj.key,
                    obj=obj,
                    reason="obstacles spawn naturally and are never pasted",
                )
            )
            continue
        if obj.is_trap and obj.low_confidence:
            actions.append(
                PlacementAction(
                    kind="skip",
                    key=obj.key,
                    obj=obj,
                    reason=f"trap confidence {obj.confidence:.2f} below 0.70",
                )
            )
            continue
        # Check stale TH rules before shop-slot lookup so invalid TH18 objects
        # do not get mislabeled as off-screen shop items.
        stale_min_th = STALE_AT_TH.get(obj.type)
        if stale_min_th is not None and target_th >= stale_min_th:
            actions.append(
                PlacementAction(
                    kind="skip",
                    key=obj.key,
                    obj=obj,
                    reason=(
                        f"{obj.type!r} is invalid/stale for TH{target_th} "
                        "(not a standalone placeable building); not pasted"
                    ),
                )
            )
            continue
        if shop_slot_point_for(obj) is None:
            if _shop_slot_from_object(obj) is None:
                reason = (
                    f"no shop slot mapping for {obj.type!r}; "
                    "not placeable from current editor shop layout"
                )
            else:
                reason = (
                    f"shop slot for {obj.type!r} is off-screen on this resolution "
                    "(needs horizontal scrolling, which is unsupported); skipping "
                    "instead of tapping an impossible coordinate"
                )
            actions.append(
                PlacementAction(kind="skip", key=obj.key, obj=obj, reason=reason)
            )
            continue
        if obj.low_confidence:
            logger.warning(
                f"Low-confidence object will still be placed and flagged: "
                f"{obj.type} at {obj.tile}"
            )
        actions.append(PlacementAction(kind="place", key=obj.key, obj=obj))

    for chain in layout.wall_chains:
        actions.append(PlacementAction(kind="wall_chain", key=chain.key, wall_chain=chain))
    return actions


def place_object(editor: EditorSession, obj: PasteObject) -> None:
    if obj.is_trap:
        editor.ensure_trap_mode()

    editor.open_shop()
    editor.tap_shop_category(obj.category)
    editor.tap_shop_icon(obj)
    editor.rotate_selected(obj.rotation)
    editor.place(obj)
    editor.confirm_level(obj)
    editor.confirm_placement()


def paste_layout(
    layout_path: str | Path,
    *,
    resume: bool = True,
    dry_run: bool = False,
    editor: EditorSession | None = None,
) -> PasteSummary:
    bundle = load_layout(layout_path)
    # Target TH is the destination account (default TH18), NOT the source
    # layout's town_hall (which may be stale, e.g. the TH15 sample). Using the
    # configured default ensures TH18 stale/invalid rules (eagle_artillery) apply.
    plan = build_plan(bundle, target_th=DEFAULT_TARGET_TH)
    if dry_run:
        print(format_plan(plan))
        return PasteSummary(placed=0, skipped=sum(a.kind == "skip" for a in plan), failed=0)

    from src.paste.editor import EditorSession

    state = PasteState.load_for_layout(bundle.path, bundle.layout_hash, resume=resume)
    install_flush_handlers(state)
    active_editor = editor or EditorSession()
    active_editor.enter_edit_mode()
    summary = PasteRunner(active_editor, state).run(plan)
    active_editor.exit_edit_mode(save=True)
    return summary


def format_plan(actions: Iterable[PlacementAction]) -> str:
    lines = ["Placement plan:"]
    for index, action in enumerate(actions, start=1):
        if action.kind == "skip":
            lines.append(
                f"{index:03d}. SKIP {action.type} @ "
                f"{action.tile_x},{action.tile_y} - {action.reason}"
            )
        elif action.kind == "wall_chain":
            count = len(action.wall_chain.points) if action.wall_chain else 0
            lines.append(f"{index:03d}. WALL_CHAIN {count} tile(s)")
        else:
            obj = action.obj
            assert obj is not None
            suffix = " LOW_CONFIDENCE" if obj.low_confidence else ""
            lines.append(
                f"{index:03d}. PLACE {obj.category}/{obj.type} @ "
                f"{obj.tile_x},{obj.tile_y} level={obj.level or 1}{suffix}"
            )
    return "\n".join(lines)


def _object_sort_key(obj: PasteObject) -> tuple[int, int, int, str]:
    return (PLACE_ORDER.get(obj.category, 0), obj.tile_y, obj.tile_x, obj.type)
