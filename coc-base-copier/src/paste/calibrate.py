"""Shop-scroll calibration: schema, persistence, and PURE scroll math.

Deliberately imports no device/ADB/Windows modules, so it is fully unit-testable
on any platform. The on-device capture step lives in editor.py / cli.py.

Calibration VALUES are measured on the user's device at calibration time -- this
module never invents coordinates. A calibration only "activates" live scrolling
when ``verified`` is True (set when the user supplies measured values); an
unverified draft is treated as absent so nothing scrolls/taps from a guess.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

CALIBRATION_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "shop_scroll_calibration.json"
)


@dataclass(frozen=True)
class ShopScrollCalibration:
    """Measured geometry of the editor inventory strip + scroll behavior."""

    screen_width: int
    screen_height: int
    strip_x_min: int
    strip_x_max: int
    strip_y_min: int
    strip_y_max: int
    visible_slot_count: int
    first_slot_x: int
    slot_y: int
    slot_width: int
    swipe_start_x: int
    swipe_end_x: int
    slots_per_swipe: int
    swipe_duration_ms: int = 450
    max_scroll_steps: int = 12
    verified: bool = False
    notes: str = ""

    def validate(self) -> list[str]:
        """Return a list of problems; empty means usable. Enforces on-screen +
        in-strip invariants so a bad calibration can never yield an off-screen
        tap/swipe."""
        errs: list[str] = []
        w, h = self.screen_width, self.screen_height
        if w <= 0 or h <= 0:
            errs.append("screen dimensions must be positive")
            return errs  # nothing else is meaningful
        for name in (
            "strip_x_min", "strip_x_max", "first_slot_x",
            "swipe_start_x", "swipe_end_x",
        ):
            v = getattr(self, name)
            if not (0 <= v < w):
                errs.append(f"{name}={v} outside 0..{w - 1}")
        for name in ("strip_y_min", "strip_y_max", "slot_y"):
            v = getattr(self, name)
            if not (0 <= v < h):
                errs.append(f"{name}={v} outside 0..{h - 1}")
        if self.strip_x_min >= self.strip_x_max:
            errs.append("strip_x_min must be < strip_x_max")
        if self.strip_y_min > self.strip_y_max:
            errs.append("strip_y_min must be <= strip_y_max")
        if not (self.strip_y_min <= self.slot_y <= self.strip_y_max):
            errs.append("slot_y must lie inside the strip y-range")
        if self.visible_slot_count <= 0:
            errs.append("visible_slot_count must be positive")
        if self.slot_width <= 0:
            errs.append("slot_width must be positive")
        if self.slots_per_swipe <= 0:
            errs.append("slots_per_swipe must be positive")
        if self.max_scroll_steps <= 0:
            errs.append("max_scroll_steps must be positive")
        return errs

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ShopScrollCalibration":
        names = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in names})


def save_calibration(cal: ShopScrollCalibration, path: Path = CALIBRATION_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cal.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def load_calibration(path: Path = CALIBRATION_PATH) -> ShopScrollCalibration | None:
    """Load calibration if present, VERIFIED, and valid; else None (safe skip).

    An unverified draft or an out-of-bounds/invalid file returns None so the
    paster falls back to skipping slot 9+ rather than scrolling on a guess.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cal = ShopScrollCalibration.from_dict(data)
    except (json.JSONDecodeError, OSError, TypeError, KeyError):
        return None
    if not cal.verified:
        return None
    if cal.validate():
        return None
    return cal


# --------------------------- pure scroll math ---------------------------


def visible_window_start(steps: int, cal: ShopScrollCalibration) -> int:
    """Index of the leftmost visible slot after ``steps`` left-swipes."""
    return steps * cal.slots_per_swipe


def point_for_slot(
    slot_index: int, steps: int, cal: ShopScrollCalibration
) -> tuple[int, int] | None:
    """On-screen (x, y) for ``slot_index`` at the given scroll ``steps``, or None
    if it is not currently in the visible window or would be off-screen / out of
    the strip. Pure and fully bounds-checked."""
    start = visible_window_start(steps, cal)
    col = slot_index - start
    if col < 0 or col >= cal.visible_slot_count:
        return None
    x = cal.first_slot_x + col * cal.slot_width
    y = cal.slot_y
    if not (0 <= x < cal.screen_width and 0 <= y < cal.screen_height):
        return None
    if not (cal.strip_x_min <= x <= cal.strip_x_max):
        return None
    return (x, y)


def steps_needed(slot_index: int, cal: ShopScrollCalibration) -> int | None:
    """Minimum left-swipes to bring ``slot_index`` into the visible window, or
    None if unreachable within ``max_scroll_steps``."""
    for steps in range(cal.max_scroll_steps + 1):
        if point_for_slot(slot_index, steps, cal) is not None:
            return steps
    return None


def swipe_points(cal: ShopScrollCalibration) -> tuple[int, int, int, int]:
    """One bounded left-swipe inside the strip: (x1, y1, x2, y2)."""
    return (cal.swipe_start_x, cal.slot_y, cal.swipe_end_x, cal.slot_y)
