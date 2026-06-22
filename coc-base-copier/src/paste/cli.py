"""Command line entry point for the paster."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from loguru import logger

from src.copy.detect import DetectionError
from src.paste.layout import LayoutContractError
from src.paste.layout import load_layout
from src.paste.place import build_plan, format_plan, paste_layout
from src.paste.roundtrip import RoundTripFailure, roundtrip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.paste")
    parser.add_argument("layout", type=Path, help="Layout JSON exported by the detector")
    parser.add_argument("--resume", action="store_true", help="Resume from paste_state.json")
    parser.add_argument("--no-resume", action="store_true", help="Ignore paste_state.json")
    parser.add_argument("--dry-run", action="store_true", help="Print placement plan without ADB")
    parser.add_argument("--roundtrip", action="store_true", help="Run detector diff after pasting")
    parser.add_argument("--device", help="ADB device serial to use")
    args = parser.parse_args(argv)

    layout_path = args.layout
    if not _validate_input_file(layout_path):
        return 1

    resume = True
    if args.no_resume:
        resume = False
    elif args.resume:
        resume = True

    if args.dry_run:
        try:
            bundle = load_layout(layout_path)
            print(format_plan(build_plan(bundle)))
            return 0
        except (DetectionError, json.JSONDecodeError, LayoutContractError) as exc:
            _print_layout_load_error(layout_path, exc)
            return 1

    try:
        if args.roundtrip:
            if layout_path.suffix.lower() == ".png":
                detected_path, exit_code = _detect_layout_first(layout_path)
                if detected_path is None:
                    return exit_code
                layout_path = detected_path
                if not _validate_input_file(layout_path):
                    return 1
                print("Step 2/2: Pasting...")
            if args.device:
                _configure_device(args.device)
            report = roundtrip(layout_path)
            print(f"Round-trip match: {report.match_percentage:.2f}%")
            return 0

        if args.device:
            _configure_device(args.device)
        summary = paste_layout(layout_path, resume=resume)
        print(
            f"Paste complete: placed={summary.placed} "
            f"skipped={summary.skipped} failed={summary.failed}"
        )
        return 0
    except RoundTripFailure as exc:
        report = exc.report
        print(f"Round-trip match: {report.match_percentage:.2f}%")
        for item in report.items:
            if item.status != "matched":
                print(f"{item.status}: {item.key} {item.detail}".strip())
        return 2
    except (DetectionError, json.JSONDecodeError, LayoutContractError) as exc:
        _print_layout_load_error(layout_path, exc)
        return 1
    except Exception as exc:
        if exc.__class__.__name__ == "AdbDeviceSelectionError":
            print(exc)
            return 1
        logger.exception(f"Paste failed: {exc}")
        return 1


def _validate_input_file(layout_path: Path) -> bool:
    if not layout_path.exists():
        print(f"Layout file not found: {layout_path}")
        print("Did you run the detector first?")
        print("  python -m src.copy <screenshot.png> <layout.json>")
        return False
    if layout_path.stat().st_size == 0:
        print(f"Layout file is empty: {layout_path}")
        print("Detector probably failed. Re-run: python -m src.copy ...")
        return False
    return True


def _print_layout_load_error(layout_path: Path, exc: BaseException) -> None:
    print(f"Could not load layout JSON: {layout_path}")
    print(f"{type(exc).__name__}: {exc}")


def _detect_layout_first(screenshot_path: Path) -> tuple[Path | None, int]:
    output_path = screenshot_path.with_suffix(".json")
    print("Step 1/2: Detecting...")
    result = subprocess.run(
        [sys.executable, "-m", "src.copy", str(screenshot_path), str(output_path)],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        return None, result.returncode
    return output_path, 0


def _configure_device(device: str) -> None:
    from src.paste.editor import configure_adb_device

    configure_adb_device(device)
