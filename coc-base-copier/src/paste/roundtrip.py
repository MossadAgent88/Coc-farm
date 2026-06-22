"""Paste/detect acceptance harness."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from loguru import logger

from src.paste.layout import LayoutBundle, PasteObject, load_layout
from src.paste.place import paste_layout


@dataclass(frozen=True)
class RoundTripItem:
    key: str
    status: str
    expected: PasteObject | None = None
    actual: PasteObject | None = None
    detail: str = ""


@dataclass(frozen=True)
class RoundTripReport:
    matched: int
    mismatched: int
    missing: int
    extra: int
    items: tuple[RoundTripItem, ...]

    @property
    def total(self) -> int:
        return self.matched + self.mismatched + self.missing + self.extra

    @property
    def match_percentage(self) -> float:
        denominator = max(1, self.total)
        return self.matched / denominator * 100.0

    @property
    def passed(self) -> bool:
        return self.match_percentage >= 95.0


class RoundTripError(RuntimeError):
    """Raised when round-trip detection cannot run."""


class RoundTripFailure(AssertionError):
    def __init__(self, report: RoundTripReport) -> None:
        super().__init__(f"Round-trip match {report.match_percentage:.2f}% is below 95%")
        self.report = report


def roundtrip(layout_path: str | Path) -> RoundTripReport:
    """Paste a layout, run detector on the result, and diff source vs detected."""
    source = load_layout(layout_path)
    paste_layout(source.path, resume=True, dry_run=False)

    detect = _load_detect_module()
    if not hasattr(detect, "detect_from_device"):
        raise RoundTripError("Detector module src.copy.detect lacks detect_from_device()")
    detected_layout = detect.detect_from_device()
    detected = _bundle_from_detected(source.path, detected_layout)
    report = diff_layouts(source, detected)
    logger.info(f"Round-trip match: {report.match_percentage:.2f}%")
    if not report.passed:
        raise RoundTripFailure(report)
    return report


def diff_layouts(source: LayoutBundle, detected: LayoutBundle) -> RoundTripReport:
    expected = _roundtrip_objects(source.objects)
    actual = _roundtrip_objects(detected.objects)

    items: list[RoundTripItem] = []
    matched = mismatched = missing = extra = 0
    for key, expected_obj in expected.items():
        actual_obj = actual.get(key)
        if actual_obj is None:
            missing += 1
            items.append(RoundTripItem(key=key, status="missing", expected=expected_obj))
            continue
        detail = _mismatch_detail(expected_obj, actual_obj)
        if detail:
            mismatched += 1
            items.append(
                RoundTripItem(
                    key=key,
                    status="mismatched",
                    expected=expected_obj,
                    actual=actual_obj,
                    detail=detail,
                )
            )
            continue
        matched += 1
        status = "matched_low_confidence" if expected_obj.low_confidence else "matched"
        items.append(
            RoundTripItem(key=key, status=status, expected=expected_obj, actual=actual_obj)
        )

    for key, actual_obj in actual.items():
        if key not in expected:
            extra += 1
            items.append(RoundTripItem(key=key, status="extra", actual=actual_obj))

    return RoundTripReport(
        matched=matched,
        mismatched=mismatched,
        missing=missing,
        extra=extra,
        items=tuple(items),
    )


def _load_detect_module() -> object:
    try:
        return importlib.import_module("src.copy.detect")
    except ModuleNotFoundError as exc:
        raise RoundTripError(
            "Detector module src.copy.detect is missing; cannot run roundtrip()"
        ) from exc


def _bundle_from_detected(source_path: Path, detected_layout: object) -> LayoutBundle:
    # Reuse load_layout's adapter by wrapping detector output as a LayoutBundle.
    from src.paste.layout import _iter_objects, _iter_wall_chains  # local adapter only

    return LayoutBundle(
        path=source_path,
        layout=detected_layout,
        raw_json={},
        layout_hash="detected",
        town_hall=None,
        objects=tuple(_iter_objects(detected_layout, {})),
        wall_chains=tuple(_iter_wall_chains(detected_layout, {})),
    )


def _roundtrip_objects(objects: Iterable[PasteObject]) -> dict[str, PasteObject]:
    result = {}
    for obj in objects:
        if obj.is_obstacle:
            continue
        if obj.is_trap and obj.low_confidence:
            continue
        key = f"{obj.type}:{obj.tile_x}:{obj.tile_y}"
        result[key] = obj
    return result


def _mismatch_detail(expected: PasteObject, actual: PasteObject) -> str:
    differences = []
    if expected.level and actual.level and expected.level != actual.level:
        differences.append(f"level expected {expected.level}, got {actual.level}")
    if expected.rotation != actual.rotation:
        differences.append(f"rotation expected {expected.rotation}, got {actual.rotation}")
    return "; ".join(differences)
