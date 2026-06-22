"""Command line entry point for the paster."""

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

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
    args = parser.parse_args(argv)

    resume = True
    if args.no_resume:
        resume = False
    elif args.resume:
        resume = True

    if args.dry_run:
        bundle = load_layout(args.layout)
        print(format_plan(build_plan(bundle)))
        return 0

    try:
        if args.roundtrip:
            report = roundtrip(args.layout)
            print(f"Round-trip match: {report.match_percentage:.2f}%")
            return 0

        summary = paste_layout(args.layout, resume=resume)
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
    except Exception as exc:
        logger.exception(f"Paste failed: {exc}")
        return 1

