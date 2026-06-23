"""Tests for the safe GUI base-copier bridge.

These verify the Dry Run button's backend never imports the live-paste
executor (no EditorSession / no ADB) and returns a clean plan dict.
"""

from __future__ import annotations

import sys

from cocbot import base_copier_bridge


def test_dry_run_sample_returns_ok_plan(tmp_path, monkeypatch):
    # Use a fresh temp coc-base-copier layout so the synthetic sample is
    # written deterministically and we don't depend on the repo's samples.
    root = tmp_path / "coc-base-copier"
    (root / "src" / "paste").mkdir(parents=True)
    (root / "src" / "paste" / "place.py").write_text(
        "# marker so _ensure_base_copier_on_path accepts this root\n",
        encoding="utf-8",
    )
    # Reset the cached root so the helper re-detects our temp root.
    monkeypatch.setattr(base_copier_bridge, "_BASE_COPIER_ROOT", None)
    monkeypatch.setattr(
        base_copier_bridge,
        "_ensure_base_copier_on_path",
        lambda: root,
    )

    # Stub the planner import so the test doesn't need the real base-copier
    # source tree (which lives in coc-base-copier/src and pulls cv2/numpy).
    captured = {}

    def fake_import_planners():
        def load_layout(path):
            captured["load_layout"] = path
            return object()

        def build_plan(bundle, *, target_th=18):
            captured["build_plan"] = bundle
            return []

        def format_plan(actions):
            captured["format_plan"] = actions
            return "Placement plan:\n001. PLACE defense/cannon @ 12,14"

        return load_layout, build_plan, format_plan

    monkeypatch.setattr(base_copier_bridge, "_import_planners", fake_import_planners)

    result = base_copier_bridge.dry_run_sample()

    assert result["ok"] is True
    assert isinstance(result["plan"], str)
    assert "Placement plan" in result["plan"]
    assert "action_count" in result
    # The pure planners were the only thing called — no executor.
    assert "load_layout" in captured
    assert "build_plan" in captured


def test_dry_run_never_executes_adb_or_live(monkeypatch):
    """The bridge must NOT execute any ADB command or pass --live.

    Note: build_plan lazy-imports src.paste.editor for pure shop-slot lookup
    functions, which transitively loads cocbot.io (module-level config logging
    only — no subprocess). That import is acceptable; what we forbid is actual
    ADB subprocess execution and the --live flag.
    """
    import subprocess

    taps = []
    real_run = subprocess.run
    real_popen = subprocess.Popen

    class _Sentinel(Exception):
        pass

    def spy_run(cmd, *a, **k):
        taps.append(cmd)
        # Any adb call means the bridge tried to click — fail fast.
        if any("adb" in str(c).lower() for c in cmd):
            raise _Sentinel("ADB command executed by dry-run bridge!")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", spy_run)
    monkeypatch.setattr(base_copier_bridge, "_BASE_COPIER_ROOT", None)
    # Run the real planner; it should not execute ADB.
    result = base_copier_bridge.dry_run_sample()
    # Restore before assertions so other tests aren't affected.
    monkeypatch.setattr(subprocess, "run", real_run)
    assert result.get("ok") is True
    # The plan string must never contain --live.
    assert "--live" not in result.get("plan", "")
    # No adb command should have been issued.
    adb_cmds = [c for c in taps if any("adb" in str(x).lower() for x in c)]
    assert not adb_cmds, f"dry-run executed ADB commands: {adb_cmds}"


def test_dry_run_missing_backend_returns_error(monkeypatch):
    monkeypatch.setattr(base_copier_bridge, "_BASE_COPIER_ROOT", None)
    monkeypatch.setattr(base_copier_bridge, "_ensure_base_copier_on_path", lambda: None)
    result = base_copier_bridge.dry_run_sample()
    assert result["ok"] is False
    assert "not available" in result["error"]