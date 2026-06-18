"""Pytest collection guards for binary fixtures with test-like names."""

from pathlib import Path


collect_ignore = [
    str(path)
    for path in Path(__file__).parent.glob("test_*.py")
    if path.read_bytes().startswith(b"\x89PNG")
]
