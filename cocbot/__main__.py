"""CLI entry: `python -m cocbot [test|attack|loop|bottom|homess|manual_attack [side]|detect_loot|loot_debug|--version]`.

The GUI spawns this as a subprocess with "loop", or with "manual_attack" /
"detect_loot" for the Manual tab buttons. Typing a command manually is
supported for one-shot testing.
"""

import sys

from loguru import logger

from cocbot import __version__


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "test"

    if command in ("--version", "-V", "version"):
        print(f"cocbot v{__version__}")
        return

    if command == "loot_debug":
        # Accepts an optional screenshot path. If omitted, requires ADB for live capture.
        from cocbot.loot_debug import run_loot_debug

        path = sys.argv[2] if len(sys.argv) > 2 else None
        if path is None:
            from cocbot.io import check_connection

            if not check_connection():
                logger.error("ADB not connected and no screenshot path given.")
                sys.exit(1)
        run_loot_debug(path)
        return

    # Import lazily so --version doesn't need ADB
    from cocbot.io import capture_screenshot, check_connection
    from cocbot.loop import (
        ensure_coc_running,
        run_attack,
        run_bottom_scout,
        run_detect_loot,
        run_loop,
        run_manual_attack,
        run_screenshot_test,
    )

    if not check_connection():
        logger.error("ADB not connected. Start LDPlayer first.")
        sys.exit(1)

    if command == "test":
        run_screenshot_test()
    elif command == "attack":
        run_attack()
    elif command == "loop":
        run_loop()
    elif command == "bottom":
        run_bottom_scout()
    elif command == "manual_attack":
        side = sys.argv[2] if len(sys.argv) > 2 else "Random"
        run_manual_attack(side)
    elif command == "detect_loot":
        run_detect_loot()
    elif command == "homess":
        import cv2

        ensure_coc_running()
        screen = capture_screenshot()
        cv2.imwrite("home_screen.png", screen)
        logger.info("Saved home_screen.png — check army/builder button positions")
    else:
        logger.error(f"Unknown command: {command}")
        logger.info(
            "Usage: python -m cocbot "
            "[test|attack|loop|bottom|homess|"
            "manual_attack [side]|detect_loot|loot_debug [file.png]|--version]"
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
