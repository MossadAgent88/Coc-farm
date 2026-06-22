"""Command line entry point for ``python -m src.copy``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from src.copy.detect import DetectionError, detect
from src.copy.schema import Layout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.copy")
    parser.add_argument("screenshot", type=Path, help="screenshot PNG/JPG to detect")
    parser.add_argument("output", type=Path, nargs="?", help="output Layout JSON path")
    args = parser.parse_args(argv)

    output_path = args.output or args.screenshot.with_suffix(".json")
    try:
        layout = detect(str(args.screenshot))
    except DetectionError as exc:
        _print_detection_error(exc)
        return 1
    except Exception as exc:
        if _is_anthropic_error(exc):
            _print_exception_chain(exc)
            return 2
        _print_exception_chain(exc)
        return 1

    output_path.write_text(layout.to_json(), encoding="utf-8")
    print(_summary(layout))
    return 0


def _summary(layout: Layout) -> str:
    return (
        f"{len(layout.objects)} objects, "
        f"{len(layout.wall_chains)} wall_chains, "
        f"{layout.trap_count()} traps, "
        f"schema_version={layout.schema_version}, "
        f"confidence_avg={_confidence_avg(layout):.3f}"
    )


def _confidence_avg(layout: Layout) -> float:
    values = [obj.confidence for obj in layout.objects]
    values.extend(chain.confidence for chain in layout.wall_chains)
    if not values:
        return 0.0
    return sum(values) / len(values)


def _print_detection_error(exc: DetectionError) -> None:
    print(f"DetectionError: {exc}", file=sys.stderr)
    for reason in exc.errors:
        print(f"- {reason}", file=sys.stderr)


def _print_exception_chain(exc: BaseException) -> None:
    for item in _exception_chain(exc):
        print(f"{type(item).__module__}.{type(item).__name__}: {item}", file=sys.stderr)


def _exception_chain(exc: BaseException) -> Iterable[BaseException]:
    current: BaseException | None = exc
    while current is not None:
        yield current
        current = current.__cause__ or current.__context__


def _is_anthropic_error(exc: BaseException) -> bool:
    for item in _exception_chain(exc):
        module = type(item).__module__
        qualified = f"{module}.{type(item).__name__}".lower()
        message = str(item).lower()
        if qualified.startswith("anthropic."):
            return True
        if "anthropic." in message:
            return True
        if "incomplete chunked read" in message:
            return True
    return False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
