"""Runtime debug screenshot annotator.

When enabled, saves annotated screenshots showing:
- ROI regions searched (blue rectangles)
- Template matches found (green rectangles + confidence)
- Tap points (red crosshairs)
- Loot OCR readings (yellow text)

Toggle via settings.json: "debug_screenshots": true
Saves to debug/runtime/ with step names and timestamps.
"""

import time
from pathlib import Path

import cv2
import numpy as np
from loguru import logger

DEBUG_DIR = Path.cwd() / "debug" / "runtime"

COLORS = {
    "blue": (255, 150, 0),
    "green": (0, 220, 0),
    "red": (0, 0, 255),
    "yellow": (0, 220, 255),
    "cyan": (255, 255, 0),
    "white": (255, 255, 255),
    "magenta": (255, 0, 255),
    "orange": (0, 140, 255),
}


class DebugContext:
    """Accumulates annotations for the current step, then writes them on save.

    One process-scoped instance (`dbg`) — state lives in attributes, not
    module globals. When disabled, all methods are cheap no-ops.
    """

    def __init__(self):
        self._enabled = False
        self._frame_counter = 0
        self._current_step = ""
        self._annotations: list[dict] = []

    def init(self, enabled: bool = False):
        """Enable/disable. Call once at startup."""
        self._enabled = enabled
        if enabled:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            logger.info(f"Debug screenshots enabled -> {DEBUG_DIR}")

    def set_step(self, name: str):
        """Set current step label for filenames. Clears pending annotations."""
        self._current_step = name
        self._annotations = []

    def is_enabled(self) -> bool:
        return self._enabled

    def add_roi(self, y1: int, y2: int, x1: int, x2: int, label: str = ""):
        if not self._enabled:
            return
        self._annotations.append(
            {"type": "roi", "y1": y1, "y2": y2, "x1": x1, "x2": x2, "label": label}
        )

    def add_match(
        self,
        cx: int,
        cy: int,
        w: int,
        h: int,
        name: str = "",
        confidence: float = 0.0,
    ):
        if not self._enabled:
            return
        self._annotations.append(
            {
                "type": "match",
                "cx": cx,
                "cy": cy,
                "w": w,
                "h": h,
                "name": name,
                "confidence": confidence,
            }
        )

    def add_tap(self, x: int, y: int, label: str = ""):
        if not self._enabled:
            return
        self._annotations.append({"type": "tap", "x": x, "y": y, "label": label})

    def add_loot(self, gold: int, elixir: int, dark: int):
        if not self._enabled:
            return
        self._annotations.append(
            {"type": "loot", "gold": gold, "elixir": elixir, "dark": dark}
        )

    def add_text(self, x: int, y: int, text: str, color: str = "white"):
        if not self._enabled:
            return
        self._annotations.append(
            {"type": "text", "x": x, "y": y, "text": text, "color": color}
        )

    def save(self, screenshot: np.ndarray, suffix: str = ""):
        """Draw all pending annotations and save the image."""
        if not self._enabled or screenshot is None:
            return

        self._frame_counter += 1
        img = screenshot.copy()

        for ann in self._annotations:
            if ann["type"] == "roi":
                x1, y1 = ann["x1"], ann["y1"]
                x2, y2 = ann["x2"], ann["y2"]
                cv2.rectangle(img, (x1, y1), (x2, y2), COLORS["blue"], 2)
                if ann["label"]:
                    cv2.putText(
                        img,
                        ann["label"],
                        (x1 + 4, y1 + 16),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.45,
                        COLORS["blue"],
                        1,
                    )

            elif ann["type"] == "match":
                cx, cy = ann["cx"], ann["cy"]
                w, h = ann["w"], ann["h"]
                x1 = cx - w // 2
                y1 = cy - h // 2
                cv2.rectangle(
                    img, (x1, y1), (x1 + w, y1 + h), COLORS["green"], 2
                )
                label = ann["name"]
                if ann["confidence"] > 0:
                    label += f" ({ann['confidence']:.2f})"
                cv2.putText(
                    img,
                    label,
                    (x1, y1 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    COLORS["green"],
                    1,
                )

            elif ann["type"] == "tap":
                x, y = ann["x"], ann["y"]
                cv2.drawMarker(
                    img, (x, y), COLORS["red"], cv2.MARKER_CROSS, 20, 2
                )
                if ann["label"]:
                    cv2.putText(
                        img,
                        ann["label"],
                        (x + 14, y - 6),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.45,
                        COLORS["red"],
                        1,
                    )

            elif ann["type"] == "loot":
                txt = f"G={ann['gold']:,} E={ann['elixir']:,} DE={ann['dark']:,}"
                cv2.putText(
                    img,
                    txt,
                    (50, 320),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    COLORS["yellow"],
                    2,
                )

            elif ann["type"] == "text":
                color = COLORS.get(ann["color"], COLORS["white"])
                cv2.putText(
                    img,
                    ann["text"],
                    (ann["x"], ann["y"]),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    1,
                )

        ts = time.strftime("%H:%M:%S")
        cv2.putText(
            img,
            f"[{ts}] {self._current_step}",
            (10, 1060),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            COLORS["white"],
            1,
        )

        step_clean = self._current_step.replace(" ", "_").replace(":", "")
        name = f"{self._frame_counter:04d}_{step_clean}"
        if suffix:
            name += f"_{suffix}"
        path = DEBUG_DIR / f"{name}.png"
        cv2.imwrite(str(path), img)
        self._annotations.clear()

        # Cleanup: keep max 500 files
        if self._frame_counter % 50 == 0:
            files = sorted(DEBUG_DIR.glob("*.png"))
            if len(files) > 500:
                for old in files[:-500]:
                    old.unlink()


dbg = DebugContext()
