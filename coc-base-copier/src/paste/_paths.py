"""Runtime path helpers for running from coc-base-copier/."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_project_paths() -> None:
    """Make the parent Coc-farm package importable from the copier subfolder."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "cocbot" / "io.py").exists():
            path = str(parent)
            if path not in sys.path:
                sys.path.insert(0, path)
            return

