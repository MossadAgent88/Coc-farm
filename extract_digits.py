"""Interactive CLI for extracting digit templates from scout screenshots.

Usage:
    python extract_digits.py screenshots/scout1.png

Shows each detected digit and lets the user label it (0-9),
saving unique digits as templates in templates/digits/.
"""

import sys
from pathlib import Path

import cv2

from cocbot.vision import (
    LOOT_REGIONS,
    _threshold_loot_text as threshold_loot_text,
    _find_digit_contours as find_digit_contours,
    _crop_and_resize_digit as crop_digit,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
DIGITS_DIR = TEMPLATES_DIR / "digits"


def extract_digits_from_screenshot(screenshot_path: str) -> None:
    """Extract digit templates from a scout screenshot interactively.

    Shows each detected digit and asks the user to label it (0-9).
    Saves unique digits to templates/digits/{digit}.png.
    """
    screenshot = cv2.imread(screenshot_path, cv2.IMREAD_COLOR)
    if screenshot is None:
        print(f"Error: could not read {screenshot_path}")
        sys.exit(1)

    h, w = screenshot.shape[:2]
    if (w, h) != (1920, 1080):
        print(f"Warning: expected 1920x1080, got {w}x{h}")

    DIGITS_DIR.mkdir(parents=True, exist_ok=True)

    saved_digits = set()
    # Load any already-saved digit templates
    for p in DIGITS_DIR.glob("*.png"):
        if p.stem.isdigit():
            saved_digits.add(p.stem)

    for region_name, (y1, y2, x1, x2) in LOOT_REGIONS.items():
        region = screenshot[y1:y2, x1:x2]
        binary = threshold_loot_text(region)
        boxes = find_digit_contours(binary)

        print(f"\n--- {region_name} --- ({len(boxes)} digits found)")

        for i, (x, y, w_box, h_box) in enumerate(boxes):
            digit_img = crop_digit(binary, x, y, w_box, h_box)

            # Try to auto-match against saved templates
            best_label = None
            best_score = -1.0
            for existing in DIGITS_DIR.glob("*.png"):
                if not existing.stem.isdigit():
                    continue
                tpl = cv2.imread(str(existing), cv2.IMREAD_GRAYSCALE)
                if tpl is None or tpl.shape != digit_img.shape:
                    continue
                result = cv2.matchTemplate(digit_img, tpl, cv2.TM_CCOEFF_NORMED)
                score = result[0][0]
                if score > best_score:
                    best_score = score
                    best_label = existing.stem

            # Show the digit to the user
            display = cv2.resize(digit_img, (120, 160), interpolation=cv2.INTER_NEAREST)
            window_name = f"{region_name} digit {i}"
            cv2.imshow(window_name, display)
            cv2.moveWindow(window_name, 100 + i * 150, 100)

            if best_label and best_score > 0.85:
                prompt = (
                    f"  Digit {i} (auto-detected as"
                    f" '{best_label}', score={best_score:.3f})."
                    " Press Enter to accept or type correct digit: "
                )
            else:
                prompt = (
                    f"  Digit {i}: type the digit (0-9), 's' to skip, 'q' to quit: "
                )

            cv2.waitKey(1)  # Let OpenCV render
            user_input = input(prompt).strip()

            cv2.destroyWindow(window_name)

            if user_input.lower() == "q":
                print("Quitting.")
                cv2.destroyAllWindows()
                return
            if user_input.lower() == "s":
                continue

            # Accept auto-detected label if user pressed Enter
            if user_input == "" and best_label and best_score > 0.85:
                label = best_label
            elif user_input in [str(d) for d in range(10)]:
                label = user_input
            else:
                print(f"  Invalid input '{user_input}', skipping.")
                continue

            out_path = DIGITS_DIR / f"{label}.png"
            cv2.imwrite(str(out_path), digit_img)
            saved_digits.add(label)
            print(f"  Saved digit '{label}' -> {out_path}")

    cv2.destroyAllWindows()
    print(f"\nDone. {len(saved_digits)} digit templates saved in {DIGITS_DIR}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <screenshot.png>")
        sys.exit(1)

    extract_digits_from_screenshot(sys.argv[1])
