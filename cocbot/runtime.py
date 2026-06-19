"""Runtime compatibility diagnostics."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterable
from typing import Any


_PY315_RUNTIME_IMPORTS: tuple[tuple[str, str], ...] = (
    ("numpy", "numpy"),
    ("opencv-python", "cv2"),
    ("Pillow", "PIL.Image"),
    ("loguru", "loguru"),
    ("customtkinter", "customtkinter"),
    ("PySide6", "PySide6.QtWebEngineWidgets"),
)


def supported_python_range() -> str:
    return "Python >=3.14,<3.15"


def python_runtime_messages() -> list[tuple[str, str]]:
    """Return startup log messages for the active Python runtime."""

    messages = [("info", f"Python runtime: {sys.version}")]
    if sys.version_info[:2] == (3, 15):
        messages.append(("warning", "Python 3.15 detected — experimental compatibility mode"))
    return messages


def log_python_runtime(logger: Any) -> None:
    """Write startup runtime diagnostics to a loguru-compatible logger."""

    for level, message in python_runtime_messages():
        log_method = getattr(logger, level, logger.info)
        log_method(message)


def _format_failures(failures: Iterable[tuple[str, BaseException]]) -> str:
    return "; ".join(f"{name}: {exc.__class__.__name__}: {exc}" for name, exc in failures)


def ensure_python_runtime_compatible() -> None:
    """Fail clearly for unsupported Python runtimes."""

    if sys.version_info < (3, 14):
        raise RuntimeError(
            f"Unsupported Python runtime: {sys.version.split()[0]}. "
            f"Use {supported_python_range()} for source runs."
        )

    if sys.version_info[:2] != (3, 15):
        return

    failures: list[tuple[str, BaseException]] = []
    for package_name, import_name in _PY315_RUNTIME_IMPORTS:
        try:
            importlib.import_module(import_name)
        except Exception as exc:  # noqa: BLE001 - surface the real dependency error.
            failures.append((package_name, exc))

    if failures:
        blocked_by = ", ".join(name for name, _exc in failures)
        details = _format_failures(failures)
        raise RuntimeError(
            "Python 3.15 support is experimental and currently blocked by: "
            f"{blocked_by}. Dependency import errors: {details}"
        )
