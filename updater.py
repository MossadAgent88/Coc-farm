"""Diagnostic tool for the loot OCR pipeline.

Run `python -m cocbot loot_debug [screenshot.png]` to dump annotated
images of every stage for every loot region. Lets you see exactly where
the pipeline fails:

  debug/loot_debug/{name}_01_region.png     — raw region crop
  debug/loot_debug/{name}_02_threshold.png  — binary mask + mask-zone outline
  debug/loot_debug/{name}_03_contours.png   — every contour, pass vs reject (with reason)
  debug/loot_debug/{name}_04_digits.png     — each cropped digit + top-3 matches & scores
  debug/loot_debug/summary.txt              — numeric breakdown

If no path is given, takes a live screenshot from the emulator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from loguru import logger

from cocbot.io import capture_screenshot
from cocbot.vision import (
    DIGIT_SIZE,
    ICON_MASK_WIDTH,
    LOOT_REGIONS,
    _crop_and_resize_digit,
    _find_digit_contours,
    _load_digit_templates,
    _threshold_loot_text,
)

_OUT_DIR = Path("debug") / "loot_debug"


def _contour_reject_reason(w: int, h: int) -> Optional[str]:
    """Return None if accepted, else the filter rule that rejected it."""
    if h < 15:
        return f"h={h}<15"
    if w < 5:
        return f"w={w}<5"
    if w > h * 2:
        return f"w={w}>2*h={h}"
    return None


def _score_digit(digit_img: np.ndarray, templates: dict[str, np.ndarray]) -> list[tuple[str, float]]:
    """Match digit against every template, return sorted (label, score) descending."""
    scored = []
    for digit, tpl in templates.items():
        if tpl.shape != digit_img.shape:
            continue
        s = cv2.matchTemplate(digit_img, tpl, cv2.TM_CCOEFF_NORMED)[0][0]
        scored.append((digit, float(s)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _upscale(img: np.ndarray, factor: int = 4) -> np.ndarray:
    h, w = img.shape[:2]
    return cv2.resize(img, (w * factor, h * factor), interpolation=cv2.INTER_NEAREST)


def _all_contours_image(region_bgr: np.ndarray, binary: np.ndarray) -> np.ndarray:
    """Draw every contour found on the region. Green = accepted. Red = rejected."""
    out = region_bgr.copy()
    # Shade the icon-mask zone so it's obvious what gets erased.
    overlay = out.copy()
    cv2.rectangle(overlay, (0, 0), (ICON_MASK_WIDTH, out.shape[0]), (0, 0, 255), -1)
    cv2.addWeighted(overlay, 0.25, out, 0.75, 0, out)
    cv2.putText(
        out,
        f"icon mask (0..{ICON_MASK_WIDTH})",
        (2, 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.3,
        (0, 0, 255),
        1,
    )

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        reject = _contour_reject_reason(w, h)
        color = (0, 0, 255) if reject else (0, 220, 0)
        cv2.rectangle(out, (x, y), (x + w, y + h), color, 1)
        label = reject or f"ok {w}x{h}"
        cv2.putText(
            out,
            label,
            (x, max(10, y - 2)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.28,
            color,
            1,
        )
    return out


def _digits_strip(
    binary: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
    templates: dict[str, np.ndarray],
) -> tuple[np.ndarray, list[dict]]:
    """Build a horizontal strip of every cropped digit with its top-3 matches.

    Returns (strip_image, per_digit_records).
    """
    if not boxes:
        strip = np.zeros((60, 200, 3), dtype=np.uint8)
        cv2.putText(
            strip,
            "no digits",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            1,
        )
        return strip, []

    tile_w = DIGIT_SIZE[0] * 4
    tile_h = DIGIT_SIZE[1] * 4 + 60  # room for text labels below the digit
    strip = np.zeros((tile_h, tile_w * len(boxes), 3), dtype=np.uint8)

    records = []
    for i, (bx, by, bw, bh) in enumerate(boxes):
        digit_img = _crop_and_resize_digit(binary, bx, by, bw, bh)
        scored = _score_digit(digit_img, templates)

        # Paint the digit on the strip at 4x
        digit_big = cv2.cvtColor(_upscale(digit_img, 4), cv2.COLOR_GRAY2BGR)
        y_off = 0
        x_off = i * tile_w
        strip[y_off : y_off + digit_big.shape[0], x_off : x_off + digit_big.shape[1]] = (
            digit_big
        )

        # Labels: best 3 candidates with scores
        text_y = digit_big.shape[0] + 14
        for rank, (lbl, sc) in enumerate(scored[:3]):
            color = (0, 220, 0) if rank == 0 else (200, 200, 200)
            cv2.putText(
                strip,
                f"{rank + 1}. {lbl}: {sc:.2f}",
                (x_off + 4, text_y + rank * 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                color,
                1,
            )

        top = scored[0] if scored else ("?", 0.0)
        records.append(
            {
                "index": i,
                "bbox": (bx, by, bw, bh),
                "top_match": top[0],
                "top_score": top[1],
                "second": scored[1] if len(scored) > 1 else (None, 0.0),
                "accepted": top[1] > 0.5,
            }
        )

    return strip, records


def run_loot_debug(screenshot_path: Optional[str] = None) -> None:
    """Dump annotated images for every loot region.

    If screenshot_path is None, take a live screenshot.
    """
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    if screenshot_path:
        screen = cv2.imread(screenshot_path, cv2.IMREAD_COLOR)
        if screen is None:
            logger.error(f"Could not read {screenshot_path}")
            return
        logger.info(f"Loaded {screenshot_path} ({screen.shape[1]}x{screen.shape[0]})")
    else:
        screen = capture_screenshot()
        shot_path = _OUT_DIR / "00_full_screenshot.png"
        cv2.imwrite(str(shot_path), screen)
        logger.info(f"Saved full screenshot: {shot_path}")

    templates = _load_digit_templates()
    if not templates:
        logger.error("No digit templates found in templates/digits/")
        return

    summary_lines: list[str] = [
        f"# Loot OCR diagnostic — {screenshot_path or 'live capture'}",
        f"# Screen shape: {screen.shape}",
        f"# ICON_MASK_WIDTH = {ICON_MASK_WIDTH}",
        f"# Score accept threshold: 0.5",
        f"# Contour filter: h >= 15 AND w >= 5 AND w <= 2h",
        "",
    ]

    for name, (y1, y2, x1, x2) in LOOT_REGIONS.items():
        region = screen[y1:y2, x1:x2]
        binary = _threshold_loot_text(region)
        boxes = _find_digit_contours(binary)

        # 01 raw region
        cv2.imwrite(str(_OUT_DIR / f"{name}_01_region.png"), _upscale(region, 3))

        # 02 threshold binary (gray visualized in BGR, so users can overlay mentally)
        thr_vis = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        # Draw the icon-mask zone as a faint red overlay
        cv2.rectangle(thr_vis, (0, 0), (ICON_MASK_WIDTH, thr_vis.shape[0]), (0, 0, 80), -1)
        cv2.imwrite(str(_OUT_DIR / f"{name}_02_threshold.png"), _upscale(thr_vis, 3))

        # 03 contours pass/reject
        cv2.imwrite(
            str(_OUT_DIR / f"{name}_03_contours.png"),
            _upscale(_all_contours_image(region, binary), 3),
        )

        # 04 digit strip
        strip, records = _digits_strip(binary, boxes, templates)
        cv2.imwrite(str(_OUT_DIR / f"{name}_04_digits.png"), strip)

        # Summary text
        raw_digits = "".join(r["top_match"] for r in records if r["accepted"])
        summary_lines.append(f"## {name}  ({y1}..{y2}, {x1}..{x2})")
        summary_lines.append(f"  contours found: {len(boxes)}")
        for r in records:
            bx, by, bw, bh = r["bbox"]
            sec_lbl, sec_sc = r["second"]
            summary_lines.append(
                f"  [{r['index']}] bbox=({bx},{by},{bw}x{bh})  "
                f"top={r['top_match']}@{r['top_score']:.3f}  "
                f"2nd={sec_lbl}@{sec_sc:.3f}  "
                f"{'ACCEPT' if r['accepted'] else 'reject'}"
            )
        summary_lines.append(f"  -> reads as: '{raw_digits}' = {int(raw_digits) if raw_digits else 0}")
        summary_lines.append("")

    summary_path = _OUT_DIR / "summary.txt"
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

    logger.info(f"Loot debug written to {_OUT_DIR.resolve()}")
    logger.info(f"Read summary.txt first, then look at *_03_contours.png and *_04_digits.png")
