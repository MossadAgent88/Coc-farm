from __future__ import annotations

import subprocess

import pytest

from src.paste import cli as paste_cli
from src.paste import editor as paste_editor


def test_paste_cli_missing_layout_is_friendly(tmp_path, capsys):
    layout_path = tmp_path / "missing.json"

    assert paste_cli.main([str(layout_path)]) == 1

    assert capsys.readouterr().out.splitlines() == [
        f"Layout file not found: {layout_path}",
        "Did you run the detector first?",
        "  python -m src.copy <screenshot.png> <layout.json>",
    ]


def test_paste_cli_empty_layout_is_friendly(tmp_path, capsys):
    layout_path = tmp_path / "empty.json"
    layout_path.write_text("", encoding="utf-8")

    assert paste_cli.main([str(layout_path)]) == 1

    assert capsys.readouterr().out.splitlines() == [
        f"Layout file is empty: {layout_path}",
        "Detector probably failed. Re-run: python -m src.copy ...",
    ]


def test_paste_cli_bad_json_has_no_traceback(tmp_path, capsys):
    layout_path = tmp_path / "bad.json"
    layout_path.write_text("{", encoding="utf-8")

    assert paste_cli.main(["--dry-run", str(layout_path)]) == 1

    out = capsys.readouterr().out
    assert f"Could not load layout JSON: {layout_path}" in out
    assert "JSONDecodeError:" in out
    assert "Traceback" not in out


def test_roundtrip_png_detector_failure_stops_before_paste(
    monkeypatch, tmp_path, capsys
):
    screenshot_path = tmp_path / "village.png"
    screenshot_path.write_bytes(b"png")

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args,
            2,
            stdout="detector stdout\n",
            stderr="detector stderr\n",
        )

    monkeypatch.setattr(paste_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(
        paste_cli,
        "roundtrip",
        lambda path: pytest.fail("roundtrip should not run after detector failure"),
    )

    assert paste_cli.main(["--roundtrip", str(screenshot_path)]) == 2

    captured = capsys.readouterr()
    assert captured.out == "Step 1/2: Detecting...\ndetector stdout\n"
    assert captured.err == "detector stderr\n"


def test_adb_auto_detect_multiple_devices_requires_override(monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=(
                "List of devices attached\n"
                "127.0.0.1:5555\tdevice\n"
                "emulator-5554\tdevice\n"
                "emulator-5556\toffline\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(paste_editor.subprocess, "run", fake_run)
    monkeypatch.setattr(paste_editor.coc_io, "DEVICE_SERIAL", None)

    with pytest.raises(paste_editor.AdbDeviceSelectionError) as exc_info:
        paste_editor.configure_adb_device()

    assert str(exc_info.value).splitlines() == [
        "Multiple devices found:",
        "  127.0.0.1:5555",
        "  emulator-5554",
        "Pass --device <serial> to choose one.",
    ]
