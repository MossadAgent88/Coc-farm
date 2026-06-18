"""Pure image → answer functions. No ADB, no global game state.

All vision thresholds and ROI coordinates are empirically tuned for
1920x1080 LDPlayer screenshots. Do not "optimize" them.
"""

import sys
from pathlib import Path

import cv2
import numpy as np
from loguru import logger

from cocbot.debug import dbg


def _templates_dir() -> Path:
    """Locate the templates/ folder.

    When running from source, templates live alongside the package
    (../templates). When bundled into a PyInstaller exe, they are
    unpacked into the temporary _MEIPASS directory at runtime.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "templates"
    return Path(__file__).parent.parent / "templates"


TEMPLATES_DIR = _templates_dir()

_template_cache: dict[str, np.ndarray | None] = {}


def _get_template(name: str, grayscale: bool = True) -> np.ndarray | None:
    key = f"{name}_{'gray' if grayscale else 'color'}"
    if key not in _template_cache:
        path = TEMPLATES_DIR / f"{name}.png"
        if not path.exists():
            _template_cache[key] = None
        else:
            flag = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
            _template_cache[key] = cv2.imread(str(path), flag)
    return _template_cache[key]


TEMPLATE_ROIS: dict[str, tuple[int, int, int, int]] = {
    # (y1, y2, x1, x2) — must be larger than template
    "0_attack_button": (820, 1080, 0, 300),
    "3_next_button": (750, 950, 1600, 1920),
    "5_return_home": (780, 1000, 550, 1400),
    "connection_lost": (250, 650, 400, 1500),
    "reload_game": (550, 720, 400, 700),
    "exit_popups": (50, 250, 1650, 1920),
    "chat_icon": (340, 500, 40, 200),
}


def find_template(
    screenshot: np.ndarray,
    template_name: str,
    threshold: float = 0.8,
    region: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int] | None:
    """Find a template on screen.

    Returns (center_x, center_y, width, height) or None.
    """
    template = _get_template(template_name, grayscale=False)
    if template is None:
        path = TEMPLATES_DIR / f"{template_name}.png"
        logger.error(f"Template not found: {path}")
        return None

    roi = region or TEMPLATE_ROIS.get(template_name)
    h, w = template.shape[:2]
    if roi:
        y1, y2, x1, x2 = roi
        roi_h, roi_w = y2 - y1, x2 - x1
        if roi_h > h and roi_w > w:
            search_area = screenshot[y1:y2, x1:x2]
            offset_x, offset_y = x1, y1
            dbg.add_roi(y1, y2, x1, x2, template_name)
        else:
            search_area = screenshot
            offset_x, offset_y = 0, 0
    else:
        search_area = screenshot
        offset_x, offset_y = 0, 0

    result = cv2.matchTemplate(search_area, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        h, w = template.shape[:2]
        center_x = max_loc[0] + w // 2 + offset_x
        center_y = max_loc[1] + h // 2 + offset_y
        dbg.add_match(center_x, center_y, w, h, template_name, max_val)
        logger.debug(
            f"Found '{template_name}'"
            f" at ({center_x}, {center_y})"
            f" {w}x{h} confidence={max_val:.3f}"
        )
        return (center_x, center_y, w, h)

    logger.debug(
        f"Template '{template_name}' not found"
        f" (best={max_val:.3f}, threshold={threshold})"
    )
    return None


def find_template_exact(
    screenshot: np.ndarray,
    template_name: str,
    threshold: float = 0.05,
) -> tuple[int, int] | None:
    """Find a template using exact color matching (TM_SQDIFF_NORMED).

    Only matches if colors are nearly identical — greyed-out versions won't match.
    Lower threshold = stricter match. 0 = perfect, threshold default 0.05.
    """
    template = _get_template(template_name, grayscale=False)
    if template is None:
        template_path = TEMPLATES_DIR / f"{template_name}.png"
        logger.error(f"Template not found: {template_path}")
        return None

    result = cv2.matchTemplate(screenshot, template, cv2.TM_SQDIFF_NORMED)
    min_val, _, min_loc, _ = cv2.minMaxLoc(result)

    if min_val <= threshold:
        h, w = template.shape[:2]
        center_x = min_loc[0] + w // 2
        center_y = min_loc[1] + h // 2
        logger.debug(
            f"Found exact '{template_name}' at"
            f" ({center_x}, {center_y}) sqdiff={min_val:.4f}"
        )
        return (center_x, center_y)

    logger.debug(
        f"Exact '{template_name}' not found"
        f" (best_sqdiff={min_val:.4f}, thresh={threshold})"
    )
    return None


def find_all_templates(
    screenshot: np.ndarray,
    template_name: str,
    threshold: float = 0.8,
) -> list[tuple[int, int]]:
    """Find all occurrences of a template. Returns list of center (x, y)."""
    template = _get_template(template_name, grayscale=False)
    if template is None:
        path = TEMPLATES_DIR / f"{template_name}.png"
        logger.error(f"Template not found: {path}")
        return []

    h, w = template.shape[:2]
    result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
    locations = np.where(result >= threshold)

    matches = []
    for pt in zip(*locations[::-1]):
        center = (pt[0] + w // 2, pt[1] + h // 2)
        too_close = any(
            abs(center[0] - m[0]) < w // 2 and abs(center[1] - m[1]) < h // 2
            for m in matches
        )
        if not too_close:
            matches.append(center)

    logger.debug(f"Found {len(matches)} instances of '{template_name}'")
    return matches


# Chat notification badge region (top-right of chat icon on home screen)
CHAT_BADGE_Y1, CHAT_BADGE_Y2 = 380, 450
CHAT_BADGE_X1, CHAT_BADGE_X2 = 80, 150

# Donation dialog card areas (troops + spells, excluding "Donated" section at bottom)
DONATE_CARDS_Y1, DONATE_CARDS_Y2 = 200, 850
DONATE_CARDS_X1, DONATE_CARDS_X2 = 750, 1780


def has_chat_notification(screenshot: np.ndarray) -> bool:
    """Check if chat icon has a red notification badge (works for any number 1-99+).

    Uses red color detection in the badge area rather than template matching,
    so it works regardless of the number displayed.
    """
    badge_region = screenshot[CHAT_BADGE_Y1:CHAT_BADGE_Y2, CHAT_BADGE_X1:CHAT_BADGE_X2]
    hsv = cv2.cvtColor(badge_region, cv2.COLOR_BGR2HSV)
    # Red wraps around in HSV, so check both ends
    mask_low = cv2.inRange(hsv, np.array([0, 120, 120]), np.array([10, 255, 255]))
    mask_high = cv2.inRange(hsv, np.array([170, 120, 120]), np.array([180, 255, 255]))
    red_pixels = cv2.countNonZero(mask_low | mask_high)
    has_badge = red_pixels > 100
    result = "badge found" if has_badge else "no badge"
    logger.debug(f"Chat badge check: {red_pixels} red pixels -> {result}")
    return has_badge


def find_available_donation_cards(
    screenshot: np.ndarray, threshold: float = 0.05
) -> list[tuple[int, int]]:
    """Find clickable (non-greyed) troop/spell cards in the donation dialog.

    Uses TM_SQDIFF_NORMED template matching which requires exact color match.
    Colored drop icons on available cards match the template; greyed-out ones don't.
    Returns list of unique (x, y) card center points to click.
    """
    check_tpl = _get_template("donate_troops_check", grayscale=False)
    if check_tpl is not None:
        res = cv2.matchTemplate(screenshot, check_tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        if max_val < 0.7:
            logger.debug(
                f"Donation dialog not open (header match={max_val:.3f}), skipping"
            )
            return []

    dialog_region = screenshot[
        DONATE_CARDS_Y1:DONATE_CARDS_Y2,
        DONATE_CARDS_X1:DONATE_CARDS_X2,
    ]
    raw_icons = []

    for icon_name in ["donation_elixir", "donation_dark_elixir"]:
        template = _get_template(icon_name, grayscale=False)
        if template is None:
            path = TEMPLATES_DIR / f"{icon_name}.png"
            logger.warning(f"Donation icon template not found: {path}")
            continue
        h, w = template.shape[:2]
        # TM_SQDIFF_NORMED: 0 = perfect color match, 1 = no match.
        # Greyed-out icons score high (bad); colored drops score low (good).
        result = cv2.matchTemplate(dialog_region, template, cv2.TM_SQDIFF_NORMED)
        locations = np.where(result <= threshold)

        for pt in zip(*locations[::-1]):
            cx = pt[0] + w // 2 + DONATE_CARDS_X1
            cy = pt[1] + h // 2 + DONATE_CARDS_Y1
            score = result[pt[1], pt[0]]
            logger.debug(f"Card at ({cx},{cy}): sqdiff={score:.3f}")
            raw_icons.append((cx, cy))

    # Deduplicate: merge icons within 40px X and 30px Y (same card icon)
    cards = []
    for cx, cy in sorted(raw_icons):
        too_close = any(abs(cx - ex) < 40 and abs(cy - ey) < 30 for ex, ey in cards)
        if not too_close:
            cards.append((cx, cy))
            logger.debug(f"Available donation card at ({cx}, {cy})")

    logger.info(f"Found {len(cards)} available donation cards")
    return cards


def find_green_button(
    screenshot: np.ndarray, region: tuple[int, int, int, int] | None = None
) -> tuple[int, int] | None:
    """Find a large green button (like Send, Okay) on screen by color.

    Green buttons in CoC have a distinct bright green color.
    Returns center (x, y) or None.
    If region is given as (y1, y2, x1, x2), search only within that area.
    """
    if region:
        y1, y2, x1, x2 = region
        area = screenshot[y1:y2, x1:x2]
        offset_x, offset_y = x1, y1
    else:
        area = screenshot
        offset_x, offset_y = 0, 0

    hsv = cv2.cvtColor(area, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([35, 100, 100]), np.array([85, 255, 255]))

    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    best_area = 0
    for c in contours:
        a = cv2.contourArea(c)
        if a > best_area and a > 500:  # Minimum area for a button
            best_area = a
            x, y, w, h = cv2.boundingRect(c)
            best = (x + w // 2 + offset_x, y + h // 2 + offset_y)

    if best:
        logger.debug(f"Found green button at ({best[0]}, {best[1]}) area={best_area}")
    else:
        logger.debug("No green button found")
    return best


DIGITS_DIR = TEMPLATES_DIR / "digits"
DIGIT_SIZE = (30, 40)
ICON_MASK_WIDTH = 38

# Minimum digit-match score. Empirically legit digits score >0.89; noise
# contours score <0.65. 0.70 gives safe margin for rejecting noise without
# dropping weak-but-real digits.
_DIGIT_MATCH_THRESHOLD = 0.70

# A top-score below this logs a WARNING so it's visible in the log. Useful
# to catch borderline reads for later review without rejecting them.
_LOW_CONFIDENCE_THRESHOLD = 0.85

LOOT_REGIONS = {
    "gold": (145, 185, 45, 290),
    "elixir": (205, 240, 45, 290),
    "dark_elixir": (255, 300, 45, 290),
}

_digit_templates: dict[str, np.ndarray] | None = None

# ── Auto-capture of suspect loot reads ──
#
# When `read_loot` produces a digit with score < _LOW_CONFIDENCE_THRESHOLD,
# we save the full screenshot to debug/loot_suspect/ with a timestamped
# filename encoding which region flagged and what digits were uncertain.
# Capped at 50 files to avoid filling disk on a long run — oldest first out.
_SUSPECT_DIR = Path("debug") / "loot_suspect"
_SUSPECT_MAX_FILES = 50
_suspect_throttle_last_ts: float = 0.0
_SUSPECT_MIN_SECONDS_BETWEEN = 5.0  # don't burst-save within one battle


def _save_suspect_screenshot(
    screenshot: np.ndarray, region: str, raw: str, low_scores: list[float]
) -> None:
    """Write the screenshot to debug/loot_suspect/ for post-hoc review.

    Throttled so back-to-back uncertain reads don't flood the folder.
    Call `python -m cocbot loot_debug debug/loot_suspect/<file>.png`
    on any saved shot to see where the pipeline went wrong.
    """
    import time as _time

    global _suspect_throttle_last_ts
    now = _time.time()
    if now - _suspect_throttle_last_ts < _SUSPECT_MIN_SECONDS_BETWEEN:
        return
    _suspect_throttle_last_ts = now

    try:
        _SUSPECT_DIR.mkdir(parents=True, exist_ok=True)
        worst = min(low_scores)
        ts = int(now)
        path = _SUSPECT_DIR / f"{ts}_{region}_{raw}_worst{worst:.2f}.png"
        cv2.imwrite(str(path), screenshot)
        logger.info(f"Saved suspect loot screenshot: {path}")

        # Cap the folder: delete oldest PNGs if we exceed _SUSPECT_MAX_FILES.
        files = sorted(_SUSPECT_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime)
        if len(files) > _SUSPECT_MAX_FILES:
            for old in files[: len(files) - _SUSPECT_MAX_FILES]:
                try:
                    old.unlink()
                except OSError:
                    pass
    except Exception as e:
        logger.warning(f"Failed to save suspect screenshot: {e}")


def _load_digit_templates() -> dict[str, np.ndarray]:
    """Load digit templates from templates/digits/ (cached after first call)."""
    global _digit_templates
    if _digit_templates is None:
        _digit_templates = {}
        for p in DIGITS_DIR.glob("*.png"):
            if p.stem.isdigit():
                tpl = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
                if tpl is not None:
                    _digit_templates[p.stem] = tpl
        logger.info(f"Loaded {len(_digit_templates)} digit templates")
    return _digit_templates


def _threshold_loot_text(region: np.ndarray) -> np.ndarray:
    """Isolate bright loot text using HSV brightness threshold.

    Handles gold (yellowish), elixir (pinkish), and dark elixir (white) text.
    """
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 0, 200]), np.array([180, 120, 255]))
    mask[:, :ICON_MASK_WIDTH] = 0
    return mask


def _find_digit_contours(binary: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Find bounding boxes of individual digits, sorted left-to-right.

    Filter rules:
      - h >= 15: drop short shapes (commas, dots, stray pixels)
      - w >= 3: allow narrow "1" glyphs (typically 5-9px, but can drop
        to ~3px if the leading digit is partially clipped by the icon mask)
      - w <= 2*h: drop horizontal streaks (underlines, borders)
    """
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if h < 15 or w < 3 or w > h * 2:
            continue
        boxes.append((x, y, w, h))
    boxes.sort(key=lambda b: b[0])
    return boxes


def _crop_and_resize_digit(
    binary: np.ndarray, x: int, y: int, w: int, h: int
) -> np.ndarray:
    """Crop a digit with padding and resize to standard template size."""
    img_h, img_w = binary.shape[:2]
    x1, y1 = max(0, x - 2), max(0, y - 2)
    x2, y2 = min(img_w, x + w + 2), min(img_h, y + h + 2)
    return cv2.resize(binary[y1:y2, x1:x2], DIGIT_SIZE, interpolation=cv2.INTER_AREA)


def read_loot(screenshot: np.ndarray, label: str = "Loot") -> dict[str, int]:
    """Read gold, elixir, dark elixir values using digit template matching.

    Returns dict with keys 'gold', 'elixir', 'dark_elixir' and int values.
    """
    templates = _load_digit_templates()
    if not templates:
        logger.error("No digit templates found in templates/digits/")
        return {"gold": 0, "elixir": 0, "dark_elixir": 0}

    loot = {}
    for name, (y1, y2, x1, x2) in LOOT_REGIONS.items():
        region = screenshot[y1:y2, x1:x2]
        binary = _threshold_loot_text(region)
        boxes = _find_digit_contours(binary)

        digits = []
        low_conf_scores: list[float] = []
        for bx, by, bw, bh in boxes:
            digit_img = _crop_and_resize_digit(binary, bx, by, bw, bh)
            best_digit, best_score = "", -1.0
            for digit, tpl in templates.items():
                if tpl.shape != digit_img.shape:
                    continue
                score = cv2.matchTemplate(digit_img, tpl, cv2.TM_CCOEFF_NORMED)[0][0]
                if score > best_score:
                    best_score = score
                    best_digit = digit
            if best_digit and best_score >= _DIGIT_MATCH_THRESHOLD:
                digits.append(best_digit)
                if best_score < _LOW_CONFIDENCE_THRESHOLD:
                    low_conf_scores.append(best_score)
            elif best_digit:
                logger.debug(
                    f"{name} digit rejected: bbox=({bx},{by},{bw}x{bh}) "
                    f"best={best_digit}@{best_score:.3f} "
                    f"< {_DIGIT_MATCH_THRESHOLD}"
                )

        raw = "".join(digits)
        try:
            loot[name] = int(raw) if raw else 0
        except ValueError:
            logger.warning(f"Could not parse {name} loot: '{raw}'")
            loot[name] = 0

        if low_conf_scores:
            logger.warning(
                f"{name} read '{raw}' has {len(low_conf_scores)} low-confidence "
                f"digit(s) (scores: {[f'{s:.2f}' for s in low_conf_scores]})"
            )
            _save_suspect_screenshot(screenshot, name, raw, low_conf_scores)

    for rname, (ry1, ry2, rx1, rx2) in LOOT_REGIONS.items():
        dbg.add_roi(ry1, ry2, rx1, rx2, rname)
    dbg.add_loot(loot["gold"], loot["elixir"], loot["dark_elixir"])

    logger.info(
        f"{label}: G={loot['gold']:,} E={loot['elixir']:,} DE={loot['dark_elixir']:,}"
    )
    return loot


TROOP_NAMES = [
    "broom_witch",
    "edrag",
    "dragon_rider",
    "baby_dragon",
    "barracks",
    "duke",
    "queen",
    "warden",
    "minion_prince",
    "spell_rage",
    "spell_totem",
]

# Troop bar search region (y range to scan for troop icons)
TROOP_BAR_Y_TOP = 945
TROOP_BAR_Y_BOT = 1015
TROOP_BAR_X_MAX = 1600


def is_troop_available(
    screenshot: np.ndarray, name: str, slot_x: int, saturation_threshold: float = 30.0
) -> bool:
    """Check if a troop in the bar is still available (colored, not greyed out).

    Measures average saturation of the troop icon region. Colored icons have high
    saturation (60+), greyed-out depleted icons have near-zero saturation (<20).
    """
    half_w = 30
    y1 = TROOP_BAR_Y_TOP
    y2 = TROOP_BAR_Y_BOT
    x1 = max(0, slot_x - half_w)
    x2 = min(screenshot.shape[1], slot_x + half_w)
    icon_region = screenshot[y1:y2, x1:x2]
    hsv = cv2.cvtColor(icon_region, cv2.COLOR_BGR2HSV)
    avg_saturation = float(hsv[:, :, 1].mean())
    available = avg_saturation >= saturation_threshold
    logger.debug(
        f"Troop '{name}' at x={slot_x}"
        f" avg_sat={avg_saturation:.1f} available={available}"
    )
    return available


def find_troop_slots(screenshot: np.ndarray, threshold: float = 0.7) -> dict[str, int]:
    """Find each troop's X position in the troop bar via template matching.

    Returns dict mapping troop name -> center X coordinate of the slot.
    Only returns troops that were found above the confidence threshold.
    Supports alternate templates (troop_{name}_alt.png).
    """
    bar_region = screenshot[TROOP_BAR_Y_TOP:TROOP_BAR_Y_BOT, 0:TROOP_BAR_X_MAX]
    gray_bar = cv2.cvtColor(bar_region, cv2.COLOR_BGR2GRAY)
    slots = {}

    for name in TROOP_NAMES:
        best_val = 0.0
        best_x = 0

        candidates = [
            f"troops/troop_{name}",
            f"troops/troop_{name}_alt",
        ]
        for tpl_name in candidates:
            template = _get_template(tpl_name, grayscale=True)
            if template is None:
                continue
            result = cv2.matchTemplate(gray_bar, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_val:
                best_val = max_val
                best_x = max_loc[0] + template.shape[1] // 2

        if best_val >= threshold:
            slots[name] = best_x
            logger.debug(
                f"Found troop '{name}' at x={best_x} (confidence={best_val:.3f})"
            )
        else:
            logger.debug(f"Troop '{name}' not found (best={best_val:.3f})")

    logger.info(f"Found {len(slots)}/{len(TROOP_NAMES)} troops in bar")
    return slots


def save_screenshot_region(
    screenshot: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    name: str,
):
    """Crop and save a region as a template image."""
    region = screenshot[y : y + h, x : x + w]
    output_path = TEMPLATES_DIR / f"{name}.png"
    cv2.imwrite(str(output_path), region)
    logger.info(f"Saved template '{name}' ({w}x{h}) to {output_path}")


# Battle HUD helpers. These are intentionally conservative: if the optional
# templates are not present or confidence is low, return None instead of making a
# blind decision. The battle loop falls back to elapsed-time estimates where safe.
SPEED_BUTTON_CENTER = (1845, 590)
SPEED_BUTTON_REGION = (540, 640, 1785, 1915)  # y1, y2, x1, x2 at 1920x1080


def _match_optional_templates(
    screenshot: np.ndarray,
    template_names: tuple[str, ...],
    region: tuple[int, int, int, int],
    threshold: float = 0.72,
) -> float:
    """Return best template confidence for optional templates, or 0.0."""
    y1, y2, x1, x2 = region
    search_area = screenshot[y1:y2, x1:x2]
    if search_area.size == 0:
        return 0.0
    gray_area = cv2.cvtColor(search_area, cv2.COLOR_BGR2GRAY)
    best = 0.0
    for name in template_names:
        template = _get_template(name, grayscale=True)
        if template is None:
            continue
        h, w = template.shape[:2]
        if gray_area.shape[0] <= h or gray_area.shape[1] <= w:
            continue
        result = cv2.matchTemplate(gray_area, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        best = max(best, float(max_val))
    return best if best >= threshold else 0.0


def detect_battle_speed(screenshot: np.ndarray) -> str | None:
    """Detect the battle speed button state: "1x", "4x", or None.

    Optional template names:
    - templates/speed_1x.png or templates/battle_speed_1x.png
    - templates/speed_4x.png or templates/battle_speed_4x.png
    """
    one_x = _match_optional_templates(
        screenshot,
        ("speed_1x", "battle_speed_1x", "hud_speed_1x"),
        SPEED_BUTTON_REGION,
    )
    four_x = _match_optional_templates(
        screenshot,
        ("speed_4x", "battle_speed_4x", "hud_speed_4x"),
        SPEED_BUTTON_REGION,
    )
    if one_x <= 0.0 and four_x <= 0.0:
        return None
    return "4x" if four_x > one_x else "1x"


def read_battle_timer_seconds(_screenshot: np.ndarray) -> int | None:
    """Read remaining battle time in seconds when timer OCR/templates exist.

    Dedicated timer templates are not bundled yet. Returning None is intentional;
    the battle loop then uses the battle-age fallback.
    """
    return None


def read_damage_percent(_screenshot: np.ndarray) -> int | None:
    """Read battle damage percentage when damage OCR/templates exist.

    Dedicated damage templates are not bundled yet. Returning None keeps
    auto-end driven by remaining-loot progress instead of guessing.
    """
    return None
