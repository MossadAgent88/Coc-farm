"""Generate visual debug overlays showing where the bot looks and taps.

Usage:
    python generate_debug_overlay.py              # live screenshot from LDPlayer
    python generate_debug_overlay.py image.png    # use existing screenshot

Outputs:
    debug/vision_map.png     — all ROI search regions + detection zones
    debug/attack_left.png    — left strategy deploy points + tap zones
    debug/attack_right.png   — right strategy deploy points + tap zones
    debug/attack_bottom.png  — bottom-right strategy deploy points + tap zones
    debug/loot_regions.png   — OCR digit reading zones
"""

import sys
from pathlib import Path

import cv2
from loguru import logger

# ROI regions from screen_detect (y1, y2, x1, x2)
TEMPLATE_ROIS = {
    "0_attack_button": (820, 1080, 0, 300),
    "3_next_button": (750, 950, 1600, 1920),
    "5_return_home": (780, 1000, 550, 1400),
    "connection_lost": (250, 650, 400, 1500),
    "reload_game": (550, 720, 400, 700),
    "exit_popups": (50, 250, 1650, 1920),
    "chat_icon": (340, 500, 40, 200),
}

LOOT_REGIONS = {
    "gold": (145, 185, 45, 255),
    "elixir": (205, 240, 45, 255),
    "dark_elixir": (255, 300, 45, 255),
}

TROOP_BAR = (945, 1015, 0, 1600)
CHAT_BADGE = (380, 450, 80, 150)
DONATE_CARDS = (200, 850, 750, 1780)
GREEN_BUTTON_REGION = (620, 950, 300, 1600)

# Deploy coordinates
LEFT_EDGE = [
    (870, 180),
    (780, 230),
    (700, 280),
    (620, 330),
    (540, 380),
    (460, 430),
    (380, 480),
    (330, 530),
    (280, 580),
    (260, 620),
]
RIGHT_EDGE = [
    (1050, 160),
    (1120, 200),
    (1190, 240),
    (1260, 280),
    (1330, 330),
    (1400, 380),
    (1460, 430),
    (1510, 470),
    (1550, 510),
    (1580, 550),
]
BOTTOM_RIGHT_EDGE = [
    (1100, 800),
    (1170, 760),
    (1240, 720),
    (1310, 680),
    (1370, 640),
    (1430, 600),
    (1490, 560),
    (1540, 520),
    (1590, 480),
    (1630, 450),
]

CORNERS = {
    "LEFT_CORNER (Queen)": (250, 630),
    "RIGHT_CORNER (Queen)": (1680, 550),
    "TOP_CORNER (Baby Dragon)": (960, 100),
    "DUKE_RIGHT_SPOT": (1800, 670),
    "BR_QUEEN": (1700, 340),
    "BR_DUKE": (160, 340),
    "BR_BABY": (980, 820),
    "BR_BARRACKS": (1650, 310),
}

RAGE_LEFT = [(980, 320), (880, 400), (780, 480), (680, 560)]
RAGE_RIGHT = [(940, 320), (1040, 400), (1140, 480), (1240, 560)]
RAGE_BR = [(1000, 640), (1120, 560), (1240, 470), (1360, 390)]

TOTEM_LEFT = [(1030, 360), (930, 440), (830, 520)]
TOTEM_RIGHT = [(890, 360), (990, 440), (1090, 520)]
TOTEM_BR = [(950, 550), (1060, 470), (1180, 400)]

COLORS = {
    "blue": (255, 150, 0),
    "green": (0, 220, 0),
    "red": (0, 0, 255),
    "yellow": (0, 220, 255),
    "cyan": (255, 255, 0),
    "magenta": (255, 0, 255),
    "orange": (0, 140, 255),
    "white": (255, 255, 255),
    "pink": (180, 105, 255),
}


def draw_roi(img, name, roi, color, thickness=2):
    y1, y2, x1, x2 = roi
    cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)
    cv2.putText(
        img,
        name,
        (x1 + 4, y1 + 16),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        color,
        1,
    )


def draw_point(img, x, y, color, radius=8, label=""):
    cv2.circle(img, (x, y), radius, color, -1)
    cv2.circle(img, (x, y), radius, (0, 0, 0), 1)
    if label:
        cv2.putText(
            img,
            label,
            (x + 12, y + 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            color,
            1,
        )


def draw_edge(img, points, color, label):
    for i, (x, y) in enumerate(points):
        draw_point(img, x, y, color, radius=6)
        if i > 0:
            px, py = points[i - 1]
            cv2.line(img, (px, py), (x, y), color, 1)
    if points:
        cv2.putText(
            img,
            label,
            (points[0][0] + 10, points[0][1] - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
        )


def generate_vision_map(screenshot):
    img = screenshot.copy()
    overlay = img.copy()

    for name, roi in TEMPLATE_ROIS.items():
        y1, y2, x1, x2 = roi
        cv2.rectangle(overlay, (x1, y1), (x2, y2), COLORS["blue"], -1)
    cv2.addWeighted(overlay, 0.2, img, 0.8, 0, img)

    for name, roi in TEMPLATE_ROIS.items():
        draw_roi(img, name, roi, COLORS["blue"], 2)

    for name, roi in LOOT_REGIONS.items():
        draw_roi(img, f"LOOT: {name}", roi, COLORS["yellow"], 2)

    draw_roi(img, "TROOP BAR", TROOP_BAR, COLORS["green"], 2)
    draw_roi(img, "CHAT BADGE", CHAT_BADGE, COLORS["red"], 2)
    draw_roi(img, "DONATE CARDS", DONATE_CARDS, COLORS["magenta"], 2)
    draw_roi(img, "GREEN BUTTON", GREEN_BUTTON_REGION, COLORS["cyan"], 2)

    # Legend
    y = 30
    for label, color in [
        ("Blue = Template ROI search", COLORS["blue"]),
        ("Yellow = Loot OCR regions", COLORS["yellow"]),
        ("Green = Troop bar", COLORS["green"]),
        ("Red = Chat badge", COLORS["red"]),
        ("Magenta = Donation cards", COLORS["magenta"]),
        ("Cyan = Green button search", COLORS["cyan"]),
    ]:
        cv2.putText(
            img,
            label,
            (700, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
        )
        y += 20

    return img


def generate_attack_overlay(screenshot, side):
    img = screenshot.copy()

    if side == "left":
        edge = LEFT_EDGE
        rage = RAGE_LEFT
        totem = TOTEM_LEFT
        queen = CORNERS["LEFT_CORNER (Queen)"]
        duke = CORNERS["DUKE_RIGHT_SPOT"]
        baby = CORNERS["TOP_CORNER (Baby Dragon)"]
        title = "LEFT ATTACK"
    elif side == "right":
        edge = RIGHT_EDGE
        rage = RAGE_RIGHT
        totem = TOTEM_RIGHT
        queen = CORNERS["RIGHT_CORNER (Queen)"]
        duke = CORNERS["LEFT_CORNER (Queen)"]
        baby = CORNERS["TOP_CORNER (Baby Dragon)"]
        title = "RIGHT ATTACK"
    else:
        edge = BOTTOM_RIGHT_EDGE
        rage = RAGE_BR
        totem = TOTEM_BR
        queen = CORNERS["BR_QUEEN"]
        duke = CORNERS["BR_DUKE"]
        baby = CORNERS["BR_BABY"]
        title = "BOTTOM-RIGHT ATTACK"

    draw_edge(img, edge, COLORS["green"], "Deploy edge")

    for x, y in rage:
        draw_point(img, x, y, COLORS["orange"], 12, "Rage")
    for x, y in totem:
        draw_point(img, x, y, COLORS["magenta"], 12, "Totem")

    draw_point(img, queen[0], queen[1], COLORS["red"], 14, "Queen")
    draw_point(img, duke[0], duke[1], COLORS["cyan"], 14, "Duke")
    draw_point(img, baby[0], baby[1], COLORS["yellow"], 14, "Baby")

    cv2.putText(
        img,
        title,
        (30, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        COLORS["white"],
        2,
    )

    # Legend
    y = 70
    for label, color in [
        ("Green = Troop deploy edge", COLORS["green"]),
        ("Red = Queen corner", COLORS["red"]),
        ("Cyan = Duke corner", COLORS["cyan"]),
        ("Yellow = Baby Dragon spot", COLORS["yellow"]),
        ("Orange = Rage spell zones", COLORS["orange"]),
        ("Magenta = Totem spell zones", COLORS["magenta"]),
    ]:
        cv2.putText(
            img,
            label,
            (30, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
        )
        y += 20

    return img


def generate_loot_overlay(screenshot):
    img = screenshot.copy()
    overlay = img.copy()

    for name, (y1, y2, x1, x2) in LOOT_REGIONS.items():
        color = {
            "gold": COLORS["yellow"],
            "elixir": COLORS["pink"],
            "dark_elixir": COLORS["white"],
        }[name]
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
        draw_roi(img, name.upper(), (y1, y2, x1, x2), color, 2)

    cv2.addWeighted(overlay, 0.3, img, 0.7, 0, img)

    for name, (y1, y2, x1, x2) in LOOT_REGIONS.items():
        color = {
            "gold": COLORS["yellow"],
            "elixir": COLORS["pink"],
            "dark_elixir": COLORS["white"],
        }[name]
        draw_roi(img, name.upper(), (y1, y2, x1, x2), color, 2)
        # Icon mask
        cv2.line(img, (x1 + 38, y1), (x1 + 38, y2), COLORS["red"], 1)
        cv2.putText(
            img,
            "icon mask",
            (x1 + 2, y2 + 14),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            COLORS["red"],
            1,
        )

    cv2.putText(
        img,
        "LOOT OCR REGIONS",
        (30, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        COLORS["white"],
        2,
    )

    return img


def main():
    debug_dir = Path("debug")
    debug_dir.mkdir(exist_ok=True)

    if len(sys.argv) > 1:
        screenshot = cv2.imread(sys.argv[1])
        if screenshot is None:
            logger.info(f"Error: could not read {sys.argv[1]}")
            sys.exit(1)
    else:
        from cocbot.io import capture_screenshot

        logger.info("Capturing live screenshot...")
        screenshot = capture_screenshot()

    h, w = screenshot.shape[:2]
    logger.info(f"Screenshot: {w}x{h}")

    logger.info("Generating vision_map.png...")
    cv2.imwrite(str(debug_dir / "vision_map.png"), generate_vision_map(screenshot))

    logger.info("Generating attack_left.png...")
    cv2.imwrite(
        str(debug_dir / "attack_left.png"), generate_attack_overlay(screenshot, "left")
    )

    logger.info("Generating attack_right.png...")
    cv2.imwrite(
        str(debug_dir / "attack_right.png"),
        generate_attack_overlay(screenshot, "right"),
    )

    logger.info("Generating attack_bottom.png...")
    cv2.imwrite(
        str(debug_dir / "attack_bottom.png"),
        generate_attack_overlay(screenshot, "bottom_right"),
    )

    logger.info("Generating loot_regions.png...")
    cv2.imwrite(str(debug_dir / "loot_regions.png"), generate_loot_overlay(screenshot))

    logger.info("\nDone! Check debug/ folder for 5 overlay images.")


if __name__ == "__main__":
    main()
