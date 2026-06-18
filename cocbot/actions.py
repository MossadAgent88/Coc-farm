"""Composite primitives — one level above io/vision.

An action is a small, self-contained operation that combines ADB input
with vision to produce a useful effect: tap a template, reach home,
dismiss popups, deploy troops for one plan.

Imports flow: io + vision + plans + session + debug + config → actions.
Nothing in actions imports from loop — one-way dependency.
"""

import random
import time
from typing import Callable

from loguru import logger

from cocbot.config import cfg
from cocbot.debug import dbg
from cocbot.army import active_preset_name, get_army_config
from cocbot.event_broom import deploy_broom_witches
from cocbot.io import (
    capture_screenshot,
    force_restart_coc,
    launch_coc,
    press_back,
    swipe,
    tap,
    zoom_out,
)
from cocbot.plans import (
    BOTTOM_RIGHT_EDGE,
    DeployPlan,
    LEFT_CORNER,
    LEFT_EDGE,
    RIGHT_CORNER,
    RIGHT_EDGE,
    TOP_CORNER,
    TROOP_BAR_Y,
)
from cocbot.session import BotStopRequested, check_deadline, deadline, emit, session
from cocbot.vision import (
    find_available_donation_cards,
    find_green_button,
    find_template,
    find_template_exact,
    find_troop_slots,
    has_chat_notification,
    is_troop_available,
    read_battle_timer_seconds,
    read_damage_percent,
    read_loot,
    detect_battle_speed,
)


# ── Small helpers ──


def human_delay(center: float, spread: float, minimum: float = 0.0) -> float:
    """Gaussian delay centered on `center` with `spread` std dev."""
    delay = random.gauss(center, spread)
    return max(minimum, delay)


def get_fatigue_multiplier() -> float:
    """Session fatigue: delays gradually increase as the session goes on.

    Ramps from 1.0 to max_mult over ramp_minutes, then stays at max.
    """
    if not cfg.fatigue:
        return 1.0
    elapsed = (time.time() - session.started_at) / 60.0
    progress = min(elapsed / cfg.fatigue_ramp, 1.0)
    return 1.0 + progress * (cfg.fatigue_max - 1.0)


def _ui_jitter(x: int, y: int, w: int = 60, h: int = 30) -> tuple[int, int]:
    """Randomize click position within a UI button area.

    Scaled to ~30% of button size.
    """
    jx = int(w * 0.3)
    jy = int(h * 0.3)
    return x + random.randint(-jx, jx), y + random.randint(-jy, jy)


# ── Fail-obviously: consecutive template-miss tracking ──
#
# If `find_and_tap` misses the same template N times in a row, the game
# has drifted (UI changed, template needs re-capture) and further taps
# at phantom locations increase ban risk. Stop the cycle loudly.
#
# ANY successful template hit clears ALL miss counters — rationale: if
# the vision system can find anything, the UI isn't totally broken, and
# the previous misses were probably fallback-chain exploration (e.g.
# `surrender_button or end_battle` — one always misses by design).

_MAX_CONSECUTIVE_MISSES = 5
_template_miss_counts: dict[str, int] = {}


def _register_template_hit(_name: str) -> None:
    _template_miss_counts.clear()


def _register_template_miss(name: str) -> None:
    count = _template_miss_counts.get(name, 0) + 1
    _template_miss_counts[name] = count
    if count >= _MAX_CONSECUTIVE_MISSES:
        emit("template_failing", name=name, misses=count)
        raise BotStopRequested(
            f"Template '{name}' missed {count}x consecutively with no other "
            "template hit in between — UI likely drifted"
        )


def safe_press_back():
    """Press back and dismiss 'Confirm Exit' dialog if it appears."""
    press_back()
    time.sleep(0.5)
    screen = capture_screenshot()
    cancel_pos = find_template(screen, "cancel", threshold=0.7)
    if cancel_pos:
        jx, jy = _ui_jitter(cancel_pos[0], cancel_pos[1], cancel_pos[2], cancel_pos[3])
        tap(jx, jy)
        logger.info(f"Dismissed Confirm Exit dialog, tapped Cancel at ({jx}, {jy})")
        time.sleep(0.5)


def find_and_tap(
    template_name: str,
    threshold: float = 0.7,
    screenshot=None,
    wait: float = 0,
    label: str = "",
) -> tuple[int, int] | None:
    """Find a template on screen and tap it with randomized position.

    Returns the (x, y) position if found and tapped, None otherwise.
    If wait > 0, waits up to that many seconds for the template to appear.
    """
    display_name = label or template_name

    if wait > 0:
        start = time.time()
        while time.time() - start < wait:
            screen = capture_screenshot()
            pos = find_template(screen, template_name, threshold=threshold)
            if pos:
                jx, jy = _ui_jitter(pos[0], pos[1], pos[2], pos[3])
                dbg.add_match(pos[0], pos[1], pos[2], pos[3], display_name, 0)
                dbg.add_tap(jx, jy, display_name)
                tap(jx, jy)
                dbg.save(screen, "tap")
                logger.info(f"Tapped '{display_name}' at ({jx}, {jy})")
                _register_template_hit(template_name)
                return pos
            time.sleep(1)
        logger.warning(f"'{display_name}' not found after {wait}s")
        _register_template_miss(template_name)
        return None

    screen = screenshot if screenshot is not None else capture_screenshot()
    pos = find_template(screen, template_name, threshold=threshold)
    if pos:
        jx, jy = _ui_jitter(pos[0], pos[1], pos[2], pos[3])
        dbg.add_match(pos[0], pos[1], pos[2], pos[3], display_name, 0)
        dbg.add_tap(jx, jy, display_name)
        tap(jx, jy)
        dbg.save(screen, "tap")
        logger.info(f"Tapped '{display_name}' at ({jx}, {jy})")
        _register_template_hit(template_name)
        return pos

    logger.warning(f"'{display_name}' not found on screen")
    if dbg.is_enabled():
        dbg.add_text(400, 540, f"NOT FOUND: {display_name}", "red")
        dbg.save(screen, "miss")
    _register_template_miss(template_name)
    return None


def wait_for_screen(
    template_name: str, timeout: float = 30.0, interval: float = 0.5
) -> bool:
    """Wait until a template appears on screen. Polls every interval seconds."""
    start = time.time()
    while time.time() - start < timeout:
        screen = capture_screenshot()
        if find_template(screen, template_name):
            return True
        time.sleep(interval)
    logger.warning(f"Timeout waiting for '{template_name}'")
    return False


def wait_for_any_screen(
    template_names: list[str], timeout: float = 30.0, interval: float = 0.5
) -> str | None:
    """Wait until any of the templates appears. Returns the matched name or None."""
    start = time.time()
    while time.time() - start < timeout:
        screen = capture_screenshot()
        for name in template_names:
            if find_template(screen, name):
                return name
        time.sleep(interval)
    logger.warning(f"Timeout waiting for any of {template_names}")
    return None


# ── Navigation ──


def check_connection_lost() -> bool:
    """Check if 'Connection lost' or 'Anyone there?' is on screen.

    If so, reload. "Anyone there?" fires immediately; "Connection lost"
    waits cfg.reconnect_wait seconds first (anti-ban).
    """
    screen = capture_screenshot()

    reload_pos = find_template(screen, "reload_game", threshold=0.7)
    if reload_pos:
        logger.warning("Inactivity disconnect detected, tapping RELOAD GAME...")
        jx, jy = _ui_jitter(reload_pos[0], reload_pos[1], reload_pos[2], reload_pos[3])
        tap(jx, jy)
        time.sleep(10)
        ensure_coc_running()
        return True

    if not find_template(screen, "connection_lost", threshold=0.7):
        return False

    logger.warning(
        f"Connection lost detected! Waiting {cfg.reconnect_wait}s before reload..."
    )
    time.sleep(cfg.reconnect_wait)

    logger.info("Looking for RELOAD button...")
    screen = capture_screenshot()
    reload_pos = find_template(screen, "reload_game", threshold=0.7)
    if reload_pos:
        jx, jy = _ui_jitter(reload_pos[0], reload_pos[1], reload_pos[2], reload_pos[3])
        tap(jx, jy)
        logger.info(f"Tapped RELOAD GAME at ({jx}, {jy})")
    else:
        reload_pos = find_green_button(screen, region=(400, 700, 300, 800))
        if reload_pos:
            jx, jy = _ui_jitter(reload_pos[0], reload_pos[1])
            tap(jx, jy)
        else:
            logger.warning("RELOAD button not found, tapping center of screen")
            tap(530, 590)
    time.sleep(10)

    ensure_coc_running()
    return True


def dismiss_popups():
    """Tap through post-battle popups to get back to village.

    Uses back button and green dialog buttons only — never blind center taps
    which can hit Shop items or other dangerous UI elements.
    """
    for _attempt in range(8):
        screen = capture_screenshot()
        if find_template(screen, "0_attack_button", threshold=0.7):
            logger.info("Back on village screen")
            return

        exit_pos = find_template(screen, "exit_popups", threshold=0.7)
        if exit_pos:
            jx, jy = _ui_jitter(exit_pos[0], exit_pos[1], exit_pos[2], exit_pos[3])
            tap(jx, jy)
            logger.debug(f"Tapped exit X at ({jx}, {jy})")
            time.sleep(2)
            continue

        green_pos = find_green_button(screen, region=(620, 950, 300, 1600))
        if green_pos:
            jx, jy = _ui_jitter(green_pos[0], green_pos[1])
            tap(jx, jy)
            logger.debug(f"Tapped dialog button at ({jx}, {jy})")
            time.sleep(2)
            continue

        safe_press_back()
        time.sleep(2)


def go_home() -> bool:
    """Get to the home village screen no matter what state the game is in.

    Handles: popups, dialogs, shop, army overview, battle selection, chat, etc.
    Returns True if home screen (attack_button visible) was reached.

    `green_repeat_count < 2` guards against persistent Star Bonus-style
    dialogs where the same green button re-appears and keeps getting
    tapped — after 2 hits we switch to the back button.
    """
    last_green_pos = None
    green_repeat_count = 0

    for _attempt in range(12):
        check_deadline("Home screen check")
        screen = capture_screenshot()

        if find_template(screen, "0_attack_button", threshold=0.7):
            logger.info("Home screen verified")
            return True

        if find_template(screen, "reload_game", threshold=0.7) or find_template(
            screen, "connection_lost", threshold=0.7
        ):
            logger.warning("Disconnect detected during go_home")
            check_connection_lost()
            continue

        if find_template(screen, "3_next_button", threshold=0.7) or find_template(
            screen, "4_end_battle_button", threshold=0.7
        ):
            logger.info("Detected scout/battle screen during go_home, ending battle...")
            end_battle_and_go_home()
            continue

        exit_pos = find_template(screen, "exit_popups", threshold=0.7)
        if exit_pos:
            jx, jy = _ui_jitter(exit_pos[0], exit_pos[1], exit_pos[2], exit_pos[3])
            tap(jx, jy)
            logger.info(f"Tapped exit X at ({jx}, {jy})")
            time.sleep(2)
            continue

        green_pos = find_green_button(screen, region=(620, 950, 300, 1600))
        if green_pos and green_repeat_count < 2:
            if (
                last_green_pos
                and abs(green_pos[0] - last_green_pos[0]) < 30
                and abs(green_pos[1] - last_green_pos[1]) < 30
            ):
                green_repeat_count += 1
            else:
                green_repeat_count = 0
            last_green_pos = green_pos
            jx, jy = _ui_jitter(green_pos[0], green_pos[1])
            tap(jx, jy)
            logger.info(f"Tapped dialog button at ({jx}, {jy})")
            time.sleep(2)
            continue

        logger.info("Using back button to navigate home")
        safe_press_back()
        green_repeat_count = 0
        last_green_pos = None
        time.sleep(2)

    logger.error("Could not reach home screen after 12 attempts")
    # Save a postmortem screenshot for debugging which popup/state blocked us.
    try:
        import cv2

        screen = capture_screenshot()
        ts = int(time.time())
        path = f"debug/go_home_gave_up_{ts}.png"
        cv2.imwrite(path, screen)
        logger.error(f"Saved postmortem: {path}")
        emit("go_home_failed", screenshot=path)
    except Exception as e:
        logger.error(f"Failed to save go_home postmortem: {e}")
    return False


def ensure_coc_running():
    """Make sure CoC is open and on the main village screen."""
    with deadline(120):
        already_running = launch_coc()
        if not already_running:
            logger.info("Waiting for CoC to load...")
            time.sleep(20)

        if not go_home():
            logger.warning("Failed to reach home, trying dismiss_popups...")
            dismiss_popups()

        logger.info("CoC is ready")


# ── Clan / donations ──


def request_cc_troops() -> bool:
    """Request clan castle troops if no cooldown active.

    Uses exact color matching — only the colored (active) CC icon matches.
    Greyed-out (cooldown) icon has different colors and won't match.
    """
    screen = capture_screenshot()
    pos = find_template_exact(screen, "cc_request_available", threshold=0.05)

    if not pos:
        logger.info("CC request not available (cooldown or not found)")
        return False

    logger.info(f"CC request available at ({pos[0]}, {pos[1]}), requesting troops...")
    jx, jy = _ui_jitter(pos[0], pos[1])
    tap(jx, jy)
    time.sleep(1.5)

    screen = capture_screenshot()
    send_pos = find_template(screen, "cc_request_send", threshold=0.7)
    if send_pos:
        jx, jy = _ui_jitter(send_pos[0], send_pos[1], send_pos[2], send_pos[3])
        tap(jx, jy)
        logger.info(f"Tapped Send button at ({jx}, {jy})")
    else:
        logger.warning("Send dialog not found, pressing back")
        safe_press_back()
        return False

    time.sleep(1)
    logger.info("CC troop request sent")
    return True


def check_and_fill_donations():
    """Open chat if notifications exist, find and fill donations.

    Flow:
      1. Check for red notification badge on chat icon
      2. If found, open chat
      3. Look for "Donate" buttons via template matching
      4. For each donate button: tap it, donate all troops/spells
      5. Close chat when done
    """
    screen = capture_screenshot()
    if not has_chat_notification(screen):
        logger.info("No chat notifications, skipping donation check")
        return

    logger.info("Chat notification detected, opening chat...")
    chat_pos = find_template(screen, "chat_icon", threshold=0.7)
    if chat_pos:
        jx, jy = _ui_jitter(chat_pos[0], chat_pos[1], chat_pos[2], chat_pos[3])
        tap(jx, jy)
    else:
        logger.info("Chat icon template miss, tapping known position")
        tap(110 + random.randint(-10, 10), 410 + random.randint(-10, 10))
    time.sleep(2)

    donations_filled = 0
    last_donate_y = -1

    while True:
        check_deadline("Donations")
        screen = capture_screenshot()
        donate_pos = find_template(screen, "donate_button", threshold=0.8)

        if not donate_pos:
            break

        if abs(donate_pos[1] - last_donate_y) < 20:
            break

        last_donate_y = donate_pos[1]
        logger.info(f"Found donate button at ({donate_pos[0]}, {donate_pos[1]})")
        jx, jy = _ui_jitter(donate_pos[0], donate_pos[1], donate_pos[2], donate_pos[3])
        tap(jx, jy)
        time.sleep(1.5)

        donated_any = False
        for _ in range(20):  # Safety limit
            screen = capture_screenshot()
            cards = find_available_donation_cards(screen)
            if not cards:
                break
            for cx, cy in cards:
                tap(cx, cy, delay=0.15)
            donated_any = True
            time.sleep(1.5)

        if donated_any:
            donations_filled += 1
            logger.info(f"Donated troops/spells (request #{donations_filled})")
            last_donate_y = -1

        time.sleep(1)

    logger.info("Closing chat...")
    for _ in range(3):
        close_pos = find_and_tap("chat_close", threshold=0.7, label="Chat Close")
        if close_pos:
            break
        time.sleep(1)
    time.sleep(1)

    logger.info(f"Donation check complete, filled {donations_filled} requests")


# ── Battle: loot search, deploy, wait for end ──


def _wait_for_scout_screen(timeout: float = 20.0) -> bool:
    """Poll until the scout screen appears (Next button or loot visible)."""
    start = time.time()
    while time.time() - start < timeout:
        screen = capture_screenshot()
        if find_template(screen, "3_next_button", threshold=0.7):
            elapsed = time.time() - start
            logger.info(f"Scout screen ready in {elapsed:.1f}s")
            return True
        loot = read_loot(screen, label="Available Loot")
        if loot["gold"] > 0 or loot["elixir"] > 0:
            elapsed = time.time() - start
            logger.info(f"Scout screen ready in {elapsed:.1f}s (loot detected)")
            return True
        time.sleep(0.5)
    logger.warning("Scout screen not detected after timeout")
    return False


def _wait_for_new_base(old_loot: dict[str, int], timeout: float = 5.0):
    """Poll until loot values change (new base loaded).

    Returns (screenshot, loot_dict) or (None, None) on timeout.
    """
    time.sleep(0.3)
    start = time.time()
    while time.time() - start < timeout:
        screen = capture_screenshot()
        loot = read_loot(screen, label="Available Loot")
        total = int(loot["gold"]) + int(loot["elixir"]) + int(loot["dark_elixir"])
        if total == 0:
            time.sleep(0.2)
            continue
        if (
            int(loot["gold"]) != int(old_loot["gold"])
            or int(loot["elixir"]) != int(old_loot["elixir"])
            or int(loot["dark_elixir"]) != int(old_loot["dark_elixir"])
        ):
            elapsed = time.time() - start
            logger.debug(f"New base detected in {elapsed:.1f}s")
            return screen, loot
        time.sleep(0.2)
    return None, None


def _default_loot_accepts(loot: dict[str, int]) -> bool:
    """Default loot filter — config-driven.

    If any of cfg.min_gold/elixir/de is set, require every set minimum to
    be met. Otherwise require `total >= cfg.min_loot`.
    """
    has_filter = cfg.min_gold > 0 or cfg.min_elixir > 0 or cfg.min_de > 0
    if has_filter:
        if cfg.min_gold > 0 and loot["gold"] < cfg.min_gold:
            return False
        if cfg.min_elixir > 0 and loot["elixir"] < cfg.min_elixir:
            return False
        if cfg.min_de > 0 and loot["dark_elixir"] < cfg.min_de:
            return False
        return True
    total = int(loot["gold"]) + int(loot["elixir"]) + int(loot["dark_elixir"])
    return total >= cfg.min_loot


def search_for_good_loot(
    accepts_fn: Callable[[dict[str, int]], bool] | None = None,
) -> bool:
    """Search through opponents until `accepts_fn(loot)` returns True.

    Uses adaptive waits — polls for new base instead of fixed sleep.
    If `accepts_fn` is omitted, uses `_default_loot_accepts` (config-driven).
    This parameter is the extension point for future attack schemes that
    want different loot criteria without modifying this function.
    """
    accepts = accepts_fn or _default_loot_accepts

    pending_loot = None
    last_loot_signature: tuple[int, int, int] | None = None
    stuck_count = 0

    for attempt in range(1, cfg.max_search + 1):
        check_deadline("Loot search")

        if pending_loot is not None:
            loot = pending_loot
            pending_loot = None
            screen = capture_screenshot()
        else:
            screen = capture_screenshot()
            loot = read_loot(screen, label="Available Loot")

        total = int(loot["gold"]) + int(loot["elixir"]) + int(loot["dark_elixir"])

        # Wait for loot to become readable (max 5s)
        retries = 0
        while total == 0 and retries < 10:
            time.sleep(0.5)
            screen = capture_screenshot()
            loot = read_loot(screen, label="Available Loot")
            total = int(loot["gold"]) + int(loot["elixir"]) + int(loot["dark_elixir"])
            retries += 1

        if total == 0:
            logger.warning(f"#{attempt} Loot 0/0/0, skipping...")
            tap(1850, 830)
            time.sleep(1.5)
            continue

        # Guard against the "stuck on same base" bug — if loot is identical
        # for 3 consecutive reads, the Next tap isn't actually advancing.
        signature = (int(loot["gold"]), int(loot["elixir"]), int(loot["dark_elixir"]))
        if signature == last_loot_signature:
            stuck_count += 1
            if stuck_count >= 3:
                logger.error(
                    f"Loot stuck at {signature} for 3 reads — aborting cycle"
                )
                emit("loot_stuck", gold=signature[0], elixir=signature[1], de=signature[2])
                return False
        else:
            stuck_count = 0
            last_loot_signature = signature

        if accepts(loot):
            logger.info(
                f"#{attempt} GOOD LOOT!"
                f" (G={loot['gold']:,}"
                f" E={loot['elixir']:,}"
                f" DE={loot['dark_elixir']:,}"
                f" total={total:,})"
            )
            emit(
                "loot_accepted",
                gold=int(loot["gold"]),
                elixir=int(loot["elixir"]),
                de=int(loot["dark_elixir"]),
                total=total,
            )
            return True

        logger.info(f"#{attempt} BAD LOOT {total:,} < {cfg.min_loot:,}")

        # Human hesitation before skipping
        if random.random() < cfg.skip_long_chance:
            c = (cfg.skip_long_min + cfg.skip_long_max) / 2
            s = (cfg.skip_long_max - cfg.skip_long_min) / 4
            hesitation = human_delay(c, s, cfg.skip_long_min)
        else:
            c = (cfg.skip_min + cfg.skip_max) / 2
            s = (cfg.skip_max - cfg.skip_min) / 4
            hesitation = human_delay(c, s, cfg.skip_min)
        hesitation *= get_fatigue_multiplier()
        logger.info(f"#{attempt} next in {hesitation:.1f}s...")
        time.sleep(hesitation)

        # Tap Next button
        screen = capture_screenshot()
        next_pos = find_template(screen, "3_next_button", threshold=0.7)
        if next_pos:
            jx, jy = _ui_jitter(next_pos[0], next_pos[1], next_pos[2], next_pos[3])
            tap(jx, jy)
        else:
            logger.info("Next template miss, tapping known pos")
            tap(
                1850 + random.randint(-15, 15),
                830 + random.randint(-10, 10),
            )

        # Wait for new base — reuse its loot on next iteration
        _new_screen, new_loot = _wait_for_new_base(loot, timeout=5.0)
        if new_loot is not None:
            pending_loot = new_loot
        else:
            logger.warning("New base timeout, continuing")

    logger.warning(f"No good loot after {cfg.max_search} attempts")
    return False


def end_battle_and_go_home():
    """Surrender/end battle and return to village."""
    logger.info("Ending battle...")
    screen = capture_screenshot()
    if not (
        find_and_tap("surrender_button", screenshot=screen, label="Surrender")
        or find_and_tap("end_battle", screenshot=screen, label="End Battle")
        or find_and_tap(
            "4_end_battle_button", screenshot=screen, label="End Battle (old)"
        )
    ):
        logger.warning("Surrender/End Battle button not found")
        return
    time.sleep(2)

    if not find_and_tap("confirm_surrender_end_battle", wait=3, label="Confirm Okay"):
        logger.warning("Confirm button not found, trying green button fallback")
        screen = capture_screenshot()
        ok_pos = find_green_button(screen, region=(550, 750, 900, 1400))
        if ok_pos:
            jx, jy = _ui_jitter(ok_pos[0], ok_pos[1])
            tap(jx, jy)
        else:
            logger.warning("No confirm button found, tapping center")
            jx, jy = _ui_jitter(1150, 660)
            tap(jx, jy)
    time.sleep(5)
    dismiss_popups()


def _loot_total(loot: dict[str, int] | None) -> int | None:
    """Return total loot from a read_loot dict, or None for invalid OCR reads."""
    if not loot:
        return None
    total = int(loot.get("gold", 0)) + int(loot.get("elixir", 0)) + int(loot.get("dark_elixir", 0))
    return total if total > 0 else None


def _filtered_remaining_loot(loot: dict[str, int] | None) -> int | None:
    """Return the remaining-loot number used for early-end decisions."""
    if not loot:
        return None
    has_resource_filter = cfg.min_gold > 0 or cfg.min_elixir > 0 or cfg.min_de > 0
    if not has_resource_filter:
        return _loot_total(loot)
    remaining = 0
    if cfg.min_gold > 0:
        remaining += int(loot.get("gold", 0))
    if cfg.min_elixir > 0:
        remaining += int(loot.get("elixir", 0))
    if cfg.min_de > 0:
        remaining += int(loot.get("dark_elixir", 0))
    return remaining if remaining > 0 else None


def _should_auto_end_battle(
    *,
    now: float,
    battle_start_time: float,
    last_deploy_time: float,
    last_progress_time: float,
    deployment_finished: bool,
    remaining_loot: int | None,
) -> tuple[bool, str]:
    """Decide whether the current battle has stopped being useful."""
    if not bool(getattr(cfg, "auto_end_enabled", True)):
        return False, "disabled"
    if not deployment_finished:
        return False, "deployment_not_finished"
    battle_age = now - battle_start_time
    if battle_age < float(getattr(cfg, "auto_end_min_battle_age", 20.0)):
        return False, "battle_too_young"
    if now - last_deploy_time < float(getattr(cfg, "auto_end_min_after_last_deploy", 12.0)):
        return False, "recent_deploy"
    low_remaining = (
        remaining_loot is not None
        and remaining_loot <= int(getattr(cfg, "auto_end_low_remaining_loot", 50_000))
    )
    no_progress = now - last_progress_time >= float(getattr(cfg, "auto_end_no_progress_seconds", 15.0))
    if low_remaining:
        return True, "low_remaining_loot"
    if no_progress:
        return True, "no_progress"
    return False, "still_progressing"


def _maybe_enable_4x(screen, remaining_seconds: int | None) -> bool:
    """Enable 4x during the final battle minute when the HUD says 1x."""
    if remaining_seconds is None:
        return False
    threshold = int(getattr(cfg, "auto_enable_4x_last_seconds", 60))
    if threshold <= 0 or remaining_seconds > threshold:
        return False
    speed = detect_battle_speed(screen)
    if speed == "4x":
        logger.debug("Battle speed already 4x")
        return False
    if speed != "1x":
        logger.debug("Battle speed unreadable; not tapping speed button blindly")
        return False
    tap(1845 + random.randint(-8, 8), 590 + random.randint(-8, 8), delay=0.05)
    logger.info("Enabled 4x battle speed for final {}s", threshold)
    emit("battle_speed_4x_enabled", remaining_seconds=int(remaining_seconds))
    return True


def _note_progress(
    *,
    remaining_loot: int | None,
    previous_remaining_loot: int | None,
    damage_percent: int | None,
    previous_damage_percent: int | None,
) -> bool:
    """Return True when loot decreased or damage increased."""
    loot_progress = (
        remaining_loot is not None
        and previous_remaining_loot is not None
        and remaining_loot < previous_remaining_loot
    )
    damage_progress = (
        damage_percent is not None
        and previous_damage_percent is not None
        and damage_percent > previous_damage_percent
    )
    return loot_progress or damage_progress


def wait_for_battle_end(timeout: float = 180.0):
    """Wait for battle end with 4x support and smart auto-end."""
    logger.info("Waiting for battle to end...")
    battle_start_time = time.time()
    session.battle_start_time = battle_start_time
    session.deployment_finished = True
    if not session.last_deploy_time:
        session.last_deploy_time = battle_start_time
    session.last_progress_time = battle_start_time
    session.speed_4x_checked = False
    previous_remaining_loot: int | None = None
    previous_damage_percent: int | None = None
    while time.time() - battle_start_time < timeout:
        check_deadline("Battle end")
        now = time.time()
        elapsed = now - battle_start_time
        screen = capture_screenshot()
        pos = find_template(screen, "5_return_home", threshold=0.7)
        if pos:
            logger.info("Found Return Home button")
            jx, jy = _ui_jitter(pos[0], pos[1], pos[2], pos[3])
            tap(jx, jy)
            time.sleep(2)
            return True
        remaining_loot: int | None = None
        damage_percent: int | None = None
        if elapsed >= 5.0:
            loot = read_loot(screen, label="Remaining Loot")
            remaining_loot = _filtered_remaining_loot(loot)
            damage_percent = read_damage_percent(screen)
            if _note_progress(
                remaining_loot=remaining_loot,
                previous_remaining_loot=previous_remaining_loot,
                damage_percent=damage_percent,
                previous_damage_percent=previous_damage_percent,
            ):
                session.last_progress_time = now
            if remaining_loot is not None:
                previous_remaining_loot = remaining_loot
            if damage_percent is not None:
                previous_damage_percent = damage_percent
        remaining_seconds = read_battle_timer_seconds(screen)
        if remaining_seconds is None:
            remaining_seconds = max(0, int(timeout - elapsed))
        if not session.speed_4x_checked and remaining_seconds <= int(getattr(cfg, "auto_enable_4x_last_seconds", 60)):
            _maybe_enable_4x(screen, remaining_seconds)
            session.speed_4x_checked = True
        should_end, reason = _should_auto_end_battle(
            now=now,
            battle_start_time=battle_start_time,
            last_deploy_time=session.last_deploy_time or battle_start_time,
            last_progress_time=session.last_progress_time or battle_start_time,
            deployment_finished=session.deployment_finished,
            remaining_loot=remaining_loot,
        )
        if should_end:
            logger.info("Auto-ending battle: {}", reason)
            emit("auto_end_battle", reason=reason, remaining=remaining_loot or 0)
            end_battle_and_go_home()
            return True
        time.sleep(1)
    logger.warning("Battle timeout, tapping to continue...")
    tap(960, 540)
    time.sleep(3)
    return False


# Troop deployment helpers


def _mark_deploy_activity() -> None:
    """Record that a troop/hero/spell/ability deployment action just happened."""
    session.last_deploy_time = time.time()


def _begin_deployment() -> None:
    session.deployment_finished = False
    _mark_deploy_activity()


def _finish_deployment() -> None:
    _mark_deploy_activity()
    session.deployment_finished = True

def _tap_troop(slots: dict[str, int], name: str):
    """Select a troop from the bar by its visual template name."""
    if name not in slots:
        logger.warning(f"Troop '{name}' not found in bar, skipping")
        return False
    tap(slots[name], TROOP_BAR_Y, delay=0.08)
    _mark_deploy_activity()
    return True


# Deployable "green ring" around a base — reuse the tuned edge points from all
# three plans so dumped troops land on valid ground no matter the base layout.
_DUMP_PERIMETER = (
    LEFT_EDGE + RIGHT_EDGE + BOTTOM_RIGHT_EDGE
    + (TOP_CORNER, LEFT_CORNER, RIGHT_CORNER)
)
# Sweep of X positions across the troop bar (covers all ~11 slots at 1920x1080;
# overlapping taps just re-select the same slot, which is harmless).
_DUMP_SLOT_XS = tuple(range(150, 1510, 80))


def _deploy_generic_dump():
    """Fallback dump: empty visible slots across the perimeter using safe taps."""
    logger.info("Generic dump deploy: emptying configured/visible army onto base")
    for sx in _DUMP_SLOT_XS:
        check_deadline("Dump deploy")
        tap(sx, TROOP_BAR_Y, delay=0.04)
        _mark_deploy_activity()
        points = list(_DUMP_PERIMETER)
        random.shuffle(points)
        for x, y in points:
            tap(x + random.randint(-8, 8), y + random.randint(-8, 8), delay=0.07)
            _mark_deploy_activity()
        tap(sx, TROOP_BAR_Y, delay=0.04)
        _mark_deploy_activity()


def deploy_dump():
    """Deploy the active army preset for event/dump mode."""
    preset = active_preset_name()
    logger.info(f"Dump mode using army preset: {preset}")
    _begin_deployment()
    try:
        if preset == "broom_witch":
            deploy_broom_witches()
        else:
            _deploy_generic_dump()
    finally:
        _finish_deployment()


def deploy_troops(plan: DeployPlan):
    """Deploy all troops according to the given plan.

    Ordering:
      1. Queen at queen_corner + ability
      2. Barracks at barracks_points
      3. Middle troops (baby dragon, edrags, dragon rider, warden, minion
         prince) in random order per attack
      4. Duke at duke_corner
      5. Rage spells at rage_points (+- 70px random)
      6. Totem spells at totem_points + 4 extra taps in totem zones
      7. Re-center camera
    """
    _begin_deployment()
    army_config = get_army_config()
    if army_config["name"] == "broom_witch":
        logger.info("Normal attack using Broom Witch preset")
        try:
            deploy_broom_witches()
        finally:
            _finish_deployment()
        return

    screen = capture_screenshot()
    slots = find_troop_slots(screen)

    if not slots:
        logger.error("No troops found in bar!")
        _finish_deployment()
        return

    logger.info(f"Troop positions: {slots} | Attacking from {plan.name} | preset={army_config['name']}")

    # 1. Queen at attack corner + activate ability
    if _tap_troop(slots, "queen"):
        logger.info(f"Deploying Queen at {plan.name} corner...")
        jx, jy = plan.jitter(plan.queen_corner[0], plan.queen_corner[1])
        tap(jx, jy, delay=0.03)
        time.sleep(0.05)
        logger.info("Activating Queen ability...")
        tap(slots["queen"], TROOP_BAR_Y, delay=0.05)
    time.sleep(0.05)

    # 2. Barracks at attack corner area
    if _tap_troop(slots, "barracks"):
        logger.info(f"Deploying Barracks at {plan.name} corner...")
        for x, y in plan.barracks_points:
            jx, jy = plan.jitter(x, y)
            tap(jx, jy, delay=0.03)
        time.sleep(0.1)

    # 3-6. Deploy middle troops in random order each attack
    def _deploy_baby_dragon():
        if _tap_troop(slots, "baby_dragon"):
            logger.info(f"Deploying Baby Dragon at {plan.name}...")
            jx, jy = plan.jitter(plan.baby_spot[0], plan.baby_spot[1])
            tap(jx, jy, delay=0.02)
            tap(jx - 40, jy + 30, delay=0.02)
            tap(jx + 40, jy + 30, delay=0.02)

    def _deploy_edrags():
        if _tap_troop(slots, "edrag"):
            logger.info(f"Deploying Edrags along {plan.name} edge until depleted...")
            edge_points = list(plan.edge)
            rounds = 0
            while True:
                if rounds >= 20:
                    logger.warning("Edrag deploy safety cap hit")
                    break
                check_deadline("Deploy troops")
                random.shuffle(edge_points)
                for x, y in edge_points:
                    jx, jy = plan.jitter(x, y)
                    tap(jx, jy, delay=0.03)
                    tap(jx + 10, jy + 5, delay=0.03)
                    tap(jx - 7, jy + 9, delay=0.03)
                rounds += 1
                screen = capture_screenshot()
                if not is_troop_available(screen, "edrag", slots["edrag"]):
                    logger.info(f"Edrags depleted after {rounds} rounds")
                    break
                tap(slots["edrag"], TROOP_BAR_Y, delay=0.03)

    def _deploy_dragon_rider():
        if _tap_troop(slots, "dragon_rider"):
            logger.info(
                f"Deploying Dragon Riders along {plan.name} edge until depleted..."
            )
            edge_points = list(plan.edge)
            rounds = 0
            while True:
                if rounds >= 20:
                    logger.warning("Dragon Rider deploy safety cap hit")
                    break
                check_deadline("Deploy troops")
                random.shuffle(edge_points)
                for x, y in edge_points:
                    jx, jy = plan.jitter(x, y)
                    tap(jx, jy, delay=0.03)
                    tap(jx + 10, jy + 5, delay=0.03)
                    tap(jx - 7, jy + 9, delay=0.03)
                rounds += 1
                screen = capture_screenshot()
                if not is_troop_available(
                    screen, "dragon_rider", slots["dragon_rider"]
                ):
                    logger.info(f"Dragon Riders depleted after {rounds} rounds")
                    break
                tap(slots["dragon_rider"], TROOP_BAR_Y, delay=0.03)

    def _deploy_warden():
        if _tap_troop(slots, "warden"):
            logger.info(f"Deploying Warden along {plan.name} edge...")
            for x, y in plan.edge[3:7]:
                jx, jy = plan.jitter(x, y)
                tap(jx, jy, delay=0.02)

    def _deploy_minion_prince():
        if _tap_troop(slots, "minion_prince"):
            logger.info(f"Deploying Minion Prince along {plan.name} edge...")
            for x, y in plan.edge:
                jx, jy = plan.jitter(x, y)
                tap(jx, jy, delay=0.02)
            time.sleep(0.2)
            logger.info("Activating Minion Prince ability...")
            tap(slots["minion_prince"], TROOP_BAR_Y, delay=0.05)

    mid_deploys = [
        _deploy_baby_dragon,
        _deploy_edrags,
        _deploy_dragon_rider,
        _deploy_warden,
        _deploy_minion_prince,
    ]
    random.shuffle(mid_deploys)
    for deploy_fn in mid_deploys:
        deploy_fn()

    # 7. Duke at opposite corner
    if _tap_troop(slots, "duke"):
        logger.info("Deploying Duke at opposite corner...")
        dx = plan.duke_corner[0] + random.randint(*plan.duke_jitter_x)
        dy = plan.duke_corner[1] + random.randint(-10, 10)
        tap(dx, dy, delay=0.03)

    # 8. Rage spells — deep inside the base (large random offset per spell)
    if _tap_troop(slots, "spell_rage"):
        logger.info("Deploying Rage spells deep inside base...")
        for rx, ry in plan.rage_points:
            ox = rx + random.randint(-70, 70)
            oy = ry + random.randint(-70, 70)
            tap(ox, oy, delay=0.05)

    # 9. Totem spells — even deeper inside the base (large random offset per spell)
    if _tap_troop(slots, "spell_totem"):
        logger.info("Deploying Totem spells deeper inside base...")
        for tx, ty in plan.totem_points:
            ox = tx + random.randint(-70, 70)
            oy = ty + random.randint(-70, 70)
            tap(ox, oy, delay=0.05)
        for _ in range(4):
            tx, ty = random.choice(list(plan.totem_points))
            ox = tx + random.randint(-70, 70)
            oy = ty + random.randint(-70, 70)
            tap(ox, oy, delay=0.05)

    # Swipe camera back to center so we can see the battle
    swipe(
        960,
        540,
        960 + random.randint(-50, 50),
        540 + random.randint(-50, 50),
        random.randint(250, 400),
    )
    _finish_deployment()
    logger.info("All troops deployed")
