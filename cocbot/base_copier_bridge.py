"""Safe in-process bridge between the desktop GUI and the coc-base-copier.

The GUI only ever calls the *planning* half of the paster here — never the
executor. Concretely this module imports the pure helpers
``src.paste.layout.load_layout`` and ``src.paste.place.{build_plan,format_plan}``
and runs them on a layout JSON. It does **not** import ``paste_layout`` /
``EditorSession`` / ADB and it never passes ``--live``.

If the coc-base-copier package or its inputs are missing, every function
returns a clear error dict instead of raising, so the GUI stays usable.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# coc-base-copier lives as a sibling sub-project. Add it to sys.path exactly
# once so ``import src...`` resolves both in dev and in a frozen PyInstaller
# build (where the coc-base-copier/src tree is bundled under _MEIPASS).
_BASE_COPIER_ROOT: Path | None = None


def _ensure_base_copier_on_path() -> Path | None:
    """Insert the coc-base-copier package root on sys.path; return it (or None)."""
    global _BASE_COPIER_ROOT
    if _BASE_COPIER_ROOT is not None:
        return _BASE_COPIER_ROOT

    candidates: list[Path] = []
    # Dev / repo layout: <repo>/coc-base-copier
    candidates.append(Path(__file__).resolve().parents[1] / "coc-base-copier")
    # Frozen layout (PyInstaller _MEIPASS): bundled at the root.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "coc-base-copier")

    for root in candidates:
        if (root / "src" / "paste" / "place.py").exists():
            root_str = str(root)
            if root_str not in sys.path:
                sys.path.insert(0, root_str)
            _BASE_COPIER_ROOT = root
            return root
    return None


def base_copier_root() -> Path | None:
    """Return the resolved coc-base-copier directory, or None if absent."""
    return _ensure_base_copier_on_path()


def _import_planners() -> tuple[Any, Any, Any] | None:
    """Import (load_layout, build_plan, format_plan); None on failure."""
    if _ensure_base_copier_on_path() is None:
        return None
    try:
        from src.paste.layout import load_layout
        from src.paste.place import build_plan, format_plan
    except Exception:
        return None
    return load_layout, build_plan, format_plan


def _sample_layout_path() -> Path | None:
    """Locate a sample layout JSON to plan against.

    Preference order:
      1. coc-base-copier/samples/test_village.json (real detector output, if
         present and tracked).
      2. coc-base-copier/samples/sample_layout.json (fallback we ship).
    Returns None if neither exists.
    """
    root = _ensure_base_copier_on_path()
    if root is None:
        return None
    primary = root / "samples" / "test_village.json"
    if primary.exists():
        return primary
    fallback = root / "samples" / "sample_layout.json"
    if fallback.exists():
        return fallback
    return None


def ensure_sample_layout() -> Path:
    """Create a tiny synthetic sample_layout.json if no sample exists.

    This lets the GUI's Dry Run button always produce a meaningful plan
    without requiring the detector (which needs an Anthropic API key) to have
    run first. The synthetic layout is intentionally minimal and flagged as
    stale via the returned dict.
    """
    root = _ensure_base_copier_on_path()
    target = Path.cwd() / "sample_layout.json"
    if root is not None:
        target = root / "samples" / "sample_layout.json"
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)

    # A minimal but schema-conformant v1.1.0 layout with one town hall, one
    # cannon, one trap, and a 3-tile wall chain. Enough to exercise every
    # branch of build_plan + format_plan without ADB or the API.
    import json

    sample = {
        "schema_version": "1.1.0",
        "source": {
            "kind": "screenshot",
            "image_id": "synthetic-gui-demo",
            "captured_at": None,
            "image_width": 1920,
            "image_height": 1080,
        },
        "town_hall_level": 15,
        "grid": {"size": 44, "corners_px": None, "corner_confidence": 0.0},
        "objects": [
            {
                "id": "obj_0000",
                "category": "defense",
                "type": "town_hall",
                "tile_x": 20,
                "tile_y": 20,
                "rotation": 0,
                "level": 15,
                "footprint": [4, 4],
                "footprint_w": 4,
                "footprint_h": 4,
                "is_trap": False,
                "confidence": 0.97,
                "notes": None,
                "pixel_x": 960.0,
                "pixel_y": 540.0,
            },
            {
                "id": "obj_0001",
                "category": "defense",
                "type": "cannon",
                "tile_x": 12,
                "tile_y": 14,
                "rotation": 0,
                "level": 14,
                "footprint": [3, 3],
                "footprint_w": 3,
                "footprint_h": 3,
                "is_trap": False,
                "confidence": 0.91,
                "notes": None,
                "pixel_x": 700.0,
                "pixel_y": 460.0,
            },
            {
                "id": "obj_0002",
                "category": "trap",
                "type": "spring_trap",
                "tile_x": 30,
                "tile_y": 30,
                "rotation": 0,
                "level": 4,
                "footprint": [1, 1],
                "footprint_w": 1,
                "footprint_h": 1,
                "is_trap": True,
                "confidence": 0.55,
                "notes": "low confidence — will be skipped by build_plan",
                "pixel_x": 1180.0,
                "pixel_y": 620.0,
            },
        ],
        "wall_chains": [
            {
                "id": "wall_00",
                "tiles": [[5, 5], [6, 5], [7, 5]],
                "level": 15,
                "closed": False,
                "piece_levels": None,
                "confidence": 0.88,
            }
        ],
        "warnings": ["synthetic sample layout for GUI dry-run demo"],
        "stats": {
            "object_count": 3,
            "wall_piece_count": 3,
            "trap_count": 1,
            "low_confidence_count": 1,
        },
    }
    target.write_text(json.dumps(sample, indent=2), encoding="utf-8")
    return target


def dry_run_sample() -> dict[str, Any]:
    """Plan the sample layout and return the plan text + staleness flag.

    This is the safest possible base-copier action from the GUI: it loads a
    layout JSON, computes where each building *would* be placed, and returns
    that plan as a string. It never imports the editor, never calls ADB, and
    never passes ``--live``.
    """
    planners = _import_planners()
    if planners is None:
        return {
            "ok": False,
            "error": (
                "coc-base-copier is not available. The base copier backend "
                "(coc-base-copier/src) was not found next to the app."
            ),
        }
    load_layout, build_plan, format_plan = planners

    sample_path = _sample_layout_path()
    stale = False
    if sample_path is None:
        try:
            sample_path = ensure_sample_layout()
            stale = True
        except Exception as exc:
            return {"ok": False, "error": f"Could not create sample layout: {exc}"}

    try:
        bundle = load_layout(sample_path)
        actions = build_plan(bundle)
        plan_text = format_plan(actions)
    except Exception as exc:
        return {"ok": False, "error": f"Planning failed: {exc}", "plan": ""}

    return {
        "ok": True,
        "plan": plan_text,
        "stale": stale,
        "source": str(sample_path),
        "action_count": len(actions),
    }


def dry_run_layout(path: str) -> dict[str, Any]:
    """Plan an arbitrary user-supplied layout JSON path (still safe — no ADB)."""
    planners = _import_planners()
    if planners is None:
        return {"ok": False, "error": "coc-base-copier is not available."}
    load_layout, build_plan, format_plan = planners

    layout_path = Path(path).expanduser().resolve()
    if not layout_path.exists():
        return {"ok": False, "error": f"Layout file not found: {layout_path}"}
    try:
        bundle = load_layout(layout_path)
        actions = build_plan(bundle)
        plan_text = format_plan(actions)
    except Exception as exc:
        return {"ok": False, "error": f"Planning failed: {exc}", "plan": ""}
    return {
        "ok": True,
        "plan": plan_text,
        "stale": False,
        "source": str(layout_path),
        "action_count": len(actions),
    }