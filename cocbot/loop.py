"""Bot orchestration — the only module that defines top-level control flow.

Imports actions, plans, io, vision, config, session, debug. No one imports
from loop.py — it sits at the top of the dependency graph.

## Structured event channel (stdout)

The GUI spawns this module as a subprocess and reads stdout. Two kinds
of lines appear:

1. Human-readable loguru log lines — for display in the text panel.
2. JSON event lines prefixed with `__EVENT__ ` — for structured state
   updates (cycle counter, step label, loot totals, etc.).

GUI must split on the prefix. Changing log string wording no longer
breaks GUI display — the GUI reads events, not text.

### Event types

| type               | fields                                            |
|--------------------|---------------------------------------------------|
| `cycle_start`      | `n: int`                                          |
| `step`             | `label: str`                                      |
| `loot_found`       | `kind: str` ("available"|"remaining"), `gold`, `elixir`, `de` |
| `loot_accepted`    | `gold, elixir, de, total: int`                    |
| `surrender_early`  | `remaining: int`                                  |
| `template_fail`    | `name: str`                                       |
| `attack_complete`  | `cycle: int`                                      |

Adding a new event is a one-line `emit()` call. Removing / renaming one
is a breaking change for the GUI.
"""

import random
import sys
import time
from enum import Enum, auto
from pathlib import Path
from typing import Callable

from loguru import logger

from cocbot import __version__
from cocbot.actions import (
    _ui_jitter,
    check_and_fill_donations,
    check_connection_lost,
    deploy_dump,
    deploy_troops,
    dismiss_popups,
    end_battle_and_go_home,
    ensure_coc_running,
    find_and_tap,
    get_fatigue_multiplier,
    human_delay,
    request_cc_troops,
    safe_press_back,
    search_for_good_loot,
    wait_for_battle_end,
    _wait_for_scout_screen,
)
from cocbot.config import cfg
from cocbot.debug import dbg
from cocbot.io import (
    capture_screenshot,
    check_connection,
    force_restart_coc,
    swipe,
    tap,
    zoom_out,
)
from cocbot.plans import PLANS_BY_KEY
from cocbot.runtime import log_python_runtime
from cocbot.session import BotStopRequested, DeadlineExceeded, deadline, emit, session
from cocbot.vision import (
    _load_digit_templates,
    find_template,
)


# ── Logging setup ──

dbg.init(cfg.debug_screenshots)

logger.remove()
_console = sys.stdout or sys.stderr
if _console is not None:
    logger.add(
        _console,
        level="INFO",
        format="{time:HH:mm:ss} | {level:<7} | {message}",
    )
if cfg.log_file:
    logger.add(
        "cocbot.log",
        level="DEBUG",
        format="{time:HH:mm:ss} | {level:<7} | {message}",
        rotation="5 MB",
        retention="7 days",
    )

# Clean up old rotated logs that loguru missed
for _old_log in Path(".").glob("cocbot.*.log"):
    try:
        if _old_log.stat().st_mtime < time.time() - 7 * 86400:
            _old_log.unlink()
    except OSError:
        pass

logger.info(f"[INFO] CoC Bot v{__version__} starting...")
log_python_runtime(logger)
emit("version", version=__version__)


# ── Screen state classification (used by exception recovery) ──


class BotState(Enum):
    HOME = auto()
    SCOUTING = auto()
    BATTLING = auto()
    DISCONNECTED = auto()
    UNKNOWN = auto()


def infer_state_from_screen(screenshot) -> BotState:
    """Classify what screen the game is on. Best-effort — returns UNKNOWN if unsure.

    Used only in the DeadlineExceeded recovery path. Popups and dialogs
    don't partition cleanly, so `go_home` (a search, not an FSM) drives
    normal flow.
    """
    if find_template(screenshot, "0_attack_button"):
        return BotState.HOME
    if find_template(screenshot, "3_next_button"):
        return BotState.SCOUTING
    if find_template(screenshot, "5_return_home") or find_template(
        screenshot, "4_end_battle_button"
    ):
        return BotState.BATTLING
    if find_template(screenshot, "reload_game") or find_template(
        screenshot, "connection_lost"
    ):
        return BotState.DISCONNECTED
    return BotState.UNKNOWN


# ── Random events (human-behavior anti-detection) ──


def _event_browse_chat():
    """Open chat, scroll up slowly like reading, then close."""
    logger.info("Random event: Browsing chat...")
    screen = capture_screenshot()
    chat_pos = find_template(screen, "chat_icon", threshold=0.7)
    if chat_pos:
        jx, jy = _ui_jitter(chat_pos[0], chat_pos[1], chat_pos[2], chat_pos[3])
        tap(jx, jy)
    else:
        tap(110 + random.randint(-10, 10), 410 + random.randint(-10, 10))
    time.sleep(random.uniform(1.5, 3))

    scrolls = random.randint(2, 5)
    for _ in range(scrolls):
        swipe(960, 400, 960, 600, random.randint(300, 600))
        time.sleep(random.uniform(1, 3))

    time.sleep(random.uniform(2, 5))

    for _ in range(3):
        close_pos = find_and_tap("chat_close", threshold=0.7, label="Chat Close")
        if close_pos:
            break
        time.sleep(1)
    time.sleep(random.uniform(0.5, 1.5))
    logger.info("Random event: Done browsing chat")


def _event_browse_shop():
    """Open shop, look around, swipe through items, then close."""
    logger.info("Random event: Browsing shop...")
    screen = capture_screenshot()
    shop_pos = find_template(screen, "open_shop", threshold=0.7)
    if not shop_pos:
        logger.info("Shop icon not found, skipping event")
        return

    jx, jy = _ui_jitter(shop_pos[0], shop_pos[1], shop_pos[2], shop_pos[3])
    tap(jx, jy)
    time.sleep(random.uniform(2, 3.5))

    swipes = random.randint(2, 4)
    for _ in range(swipes):
        start_x = random.randint(1100, 1300)
        end_x = random.randint(400, 600)
        y = random.randint(480, 560)
        swipe(start_x, y, end_x, y, random.randint(400, 800))
        time.sleep(random.uniform(1.5, 3.5))

    for _ in range(3):
        close_pos = find_and_tap("exit_popups", threshold=0.7, label="Shop Close")
        if close_pos:
            break
        time.sleep(1)
    time.sleep(random.uniform(0.5, 1.5))
    logger.info("Random event: Done browsing shop")


def _event_zoom_base():
    """Zoom around own base randomly like checking defenses. No tapping."""
    logger.info("Random event: Zooming around base...")
    actions_ = random.randint(3, 6)
    for _ in range(actions_):
        action = random.choice(["swipe", "swipe", "zoom_out"])
        if action == "swipe":
            sx = random.randint(400, 1500)
            sy = random.randint(200, 800)
            dx = sx + random.randint(-400, 400)
            dy = sy + random.randint(-300, 300)
            swipe(sx, sy, dx, dy, random.randint(300, 700))
        else:
            zoom_out(random.randint(3, 6))
        time.sleep(random.uniform(1, 3))

    zoom_out(random.randint(1, 5))
    time.sleep(random.uniform(0.5, 1.5))
    logger.info("Random event: Done zooming around base")


def _event_idle_scroll():
    """Sit on home screen and scroll around slowly. Like a bored player."""
    logger.info("Random event: Idle scrolling around base...")
    scrolls = random.randint(2, 5)
    for _ in range(scrolls):
        sx = random.randint(500, 1400)
        sy = random.randint(300, 700)
        dx = sx + random.randint(-300, 300)
        dy = sy + random.randint(-200, 200)
        swipe(sx, sy, dx, dy, random.randint(500, 1000))
        time.sleep(random.uniform(1.5, 4))

    time.sleep(random.uniform(2, 5))
    logger.info("Random event: Done idle scrolling")


def _event_check_army():
    """Open army overview, look at it briefly, then close."""
    logger.info("Random event: Checking army...")
    screen = capture_screenshot()
    army_pos = find_template(screen, "open_army", threshold=0.7)
    if not army_pos:
        logger.info("Army button not found, skipping event")
        return

    jx, jy = _ui_jitter(army_pos[0], army_pos[1], army_pos[2], army_pos[3])
    tap(jx, jy)
    time.sleep(random.uniform(2, 4))

    for _ in range(random.randint(1, 3)):
        swipe(960, 500, 960 + random.randint(-200, 200), 500, random.randint(300, 600))
        time.sleep(random.uniform(1, 2.5))

    close_pos = find_and_tap("exit_popups", threshold=0.7, label="Army Close")
    if not close_pos:
        safe_press_back()
    time.sleep(random.uniform(0.5, 1.5))
    logger.info("Random event: Done checking army")


def _event_open_builder():
    """Open builder menu by tapping the builder count (1/7) at top of home screen."""
    logger.info("Random event: Checking builder menu...")
    # Builder "1/7" indicator at top bar, ~(940, 50) on 1920x1080
    bx = 940 + random.randint(-40, 60)
    by = 50 + random.randint(-15, 20)
    tap(bx, by)
    time.sleep(random.uniform(2, 4))

    time.sleep(random.uniform(1.5, 3.5))

    bx = 940 + random.randint(-40, 60)
    by = 50 + random.randint(-15, 20)
    tap(bx, by)
    time.sleep(1)
    screen = capture_screenshot()
    if not find_template(screen, "0_attack_button", threshold=0.7):
        safe_press_back()
        time.sleep(0.5)
    logger.info("Random event: Done checking builder menu")


def _event_just_stare():
    """Do nothing for a while. Simulating a distracted player."""
    duration = random.uniform(3, 12)
    logger.info(f"Random event: Staring at screen for {duration:.1f}s...")
    time.sleep(duration)
    logger.info("Random event: Done staring")


# Event name -> (weight, callable). Higher weight = more likely.
# `just_stare` is double-weighted because "doing nothing briefly" is the
# most common human "event" between actions.
RANDOM_EVENTS: dict[str, tuple[int, Callable[[], None]]] = {
    "browse_chat": (1, _event_browse_chat),
    "browse_shop": (1, _event_browse_shop),
    "zoom_base": (1, _event_zoom_base),
    "idle_scroll": (1, _event_idle_scroll),
    "check_army": (1, _event_check_army),
    "open_builder": (1, _event_open_builder),
    "just_stare": (2, _event_just_stare),
}


def _pick_random_event() -> Callable[[], None]:
    names = list(RANDOM_EVENTS.keys())
    weights = [RANDOM_EVENTS[n][0] for n in names]
    name = random.choices(names, weights=weights, k=1)[0]
    return RANDOM_EVENTS[name][1]


def _schedule_next_event(current_cycle: int):
    """Schedule the next random event N cycles from now."""
    session.next_event_at_cycle = current_cycle + random.randint(
        cfg.event_every_min, cfg.event_every_max
    )


def maybe_trigger_random_event(current_cycle: int):
    """Trigger a random event if enough cycles have passed.

    Sometimes chains 2 events (20% chance).
    """
    if not cfg.random_events:
        return
    if session.next_event_at_cycle == 0:
        _schedule_next_event(current_cycle)
        return
    if current_cycle < session.next_event_at_cycle:
        return
    _pick_random_event()()
    # 20% chance to chain a second event right after (real players browse around)
    if random.random() < 0.2:
        time.sleep(random.uniform(1, 4))
        _pick_random_event()()
    _schedule_next_event(current_cycle)


# ── Breaks and post-attack delay ──


def _schedule_next_break():
    """Schedule when the next break should happen."""
    session.next_break_at = time.time() + random.randint(
        cfg.break_every_min * 60,
        cfg.break_every_max * 60,
    )


def maybe_take_break():
    """Sleep for a human-like break if scheduled and not blocked.

    Blocked during combat (between loot-found and troops-deployed) so
    we don't leave the attack half-finished.
    """
    if session.break_blocked:
        return False
    if session.next_break_at == 0.0 or time.time() < session.next_break_at:
        return False

    break_duration = random.randint(
        cfg.break_dur_min * 60,
        cfg.break_dur_max * 60,
    )
    logger.info(f"Taking a break for {break_duration // 60}m {break_duration % 60}s...")
    time.sleep(break_duration)
    logger.info("Break over, resuming...")
    _schedule_next_break()
    check_connection_lost()
    return True


def post_attack_delay():
    """Random delay after returning home, simulating checking base."""
    center = (cfg.post_attack_min + cfg.post_attack_max) / 2
    spread = (cfg.post_attack_max - cfg.post_attack_min) / 4
    fatigue = get_fatigue_multiplier()
    delay = human_delay(center, spread, cfg.post_attack_min) * fatigue
    logger.info(f"Post-attack delay: {delay:.1f}s (fatigue x{fatigue:.2f})...")
    time.sleep(delay)


# ── Core orchestration ──


def _resolve_attack_side() -> str:
    """Translate cfg.attack_side GUI label → plan key."""
    setting = cfg.attack_side
    if setting in ("Top left only", "Top left"):
        return "left"
    if setting in ("Top right only", "Top right"):
        return "right"
    if setting in ("Bottom right only", "Bottom right"):
        return "bottom_right"
    return random.choice(["left", "right", "bottom_right"])


def _step(label: str) -> None:
    """Set the debug step label AND emit a `step` event for the GUI."""
    dbg.set_step(label)
    emit("step", label=label)


# ── Fail-obviously: force_restart budget + UNKNOWN state counter ──

_MAX_RESTARTS_PER_HOUR = 2
_MAX_CONSECUTIVE_UNKNOWNS = 3


def _budgeted_force_restart() -> None:
    """Wrapper around `force_restart_coc` that trips the bot if called too often.

    Frequent force-restarts mean the bot is stuck in a loop it can't
    recover from — continuing just hammers the servers.
    """
    now = time.time()
    session.recent_restarts = [t for t in session.recent_restarts if now - t < 3600]
    session.recent_restarts.append(now)
    if len(session.recent_restarts) > _MAX_RESTARTS_PER_HOUR:
        emit("restart_budget_exceeded", count=len(session.recent_restarts))
        raise BotStopRequested(
            f"force_restart_coc called {len(session.recent_restarts)}x in the last "
            f"hour (max {_MAX_RESTARTS_PER_HOUR}) — stopping to avoid a spiral"
        )
    force_restart_coc()


def _track_unknown_state(state: "BotState") -> None:
    """Count consecutive UNKNOWN classifications and stop if it keeps happening."""
    if state == BotState.UNKNOWN:
        session.consecutive_unknown_states += 1
        if session.consecutive_unknown_states >= _MAX_CONSECUTIVE_UNKNOWNS:
            emit("unknown_state_budget_exceeded", count=session.consecutive_unknown_states)
            raise BotStopRequested(
                f"infer_state_from_screen returned UNKNOWN "
                f"{session.consecutive_unknown_states}x in a row — UI likely broken"
            )
    else:
        session.consecutive_unknown_states = 0


def _zoom_and_deploy(plan):
    """Steps 5+6 of an attack: zoom out, swipe to center base, deploy troops.

    Extracted so manual single-shot attacks (GUI Manual tab) can reuse the
    same deploy mechanics without going through matchmaking + loot search.
    Caller owns session/break state around the call.
    """
    _step("Step 5: Zoom + camera")
    logger.info("Step 5: Zooming out + centering...")
    zoom_out(random.randint(1, 5))
    time.sleep(0.5)
    if plan.name == "bottom_right":
        swipe(960, 540, 700, 300, 300)
    else:
        swipe(960, 540, 1200, 700, 300)
    time.sleep(1)
    dbg.add_text(400, 540, f"Strategy: {plan.name}", "green")
    if dbg.is_enabled():
        dbg.save(capture_screenshot(), "zoomed")

    _step("Step 6: Deploy troops")
    logger.info("Step 6: Deploying troops...")
    with deadline(120):
        deploy_troops(plan)
    if dbg.is_enabled():
        dbg.save(capture_screenshot(), "deployed")


def _finish_battle():
    """Steps 7+8 of an attack: wait for battle end, dismiss popups."""
    _step("Step 7: Battle wait")
    logger.info("Step 7: Waiting for battle result...")
    with deadline(240):
        wait_for_battle_end()
    if dbg.is_enabled():
        dbg.save(capture_screenshot(), "battle_end")

    _step("Step 8: Dismiss popups")
    with deadline(120):
        dismiss_popups()
    if dbg.is_enabled():
        dbg.save(capture_screenshot(), "popups_done")


def run_manual_attack(side_label: str = "Random"):
    """Deploy troops on whatever scout/raid base is currently visible.

    Used by the GUI Manual tab when the user has manually navigated to a
    base. Skips matchmaking, loot search, donations, breaks, and random
    events — just the deploy + wait + dismiss slice.

    side_label uses GUI dropdown values: "Random", "Top left",
    "Top right", "Bottom right". Translated via _resolve_attack_side().
    """
    logger.info(f"=== Manual attack starting (side={side_label}) ===")
    cfg.attack_side = side_label
    side_key = _resolve_attack_side()
    plan = PLANS_BY_KEY[side_key]

    _load_digit_templates()
    _zoom_and_deploy(plan)
    _finish_battle()

    logger.info("=== Manual attack complete ===")


def run_detect_loot():
    """Capture screen and OCR the loot panel. Used by GUI Detect Loot button.

    Assumes a scout/raid screen is showing the 'Available Loot' panel. On
    other screens the OCR returns 0/garbage — user re-tries on the right
    screen.
    """
    from cocbot.vision import read_loot

    logger.info("=== Manual loot detection ===")
    _load_digit_templates()
    screen = capture_screenshot()
    read_loot(screen, label="Manual loot")


def run_attack(cycle: int = 0):
    """Execute one full attack cycle with loot check."""
    logger.info("=== Starting attack cycle ===")
    _step(f"Cycle {cycle}")

    # Preload digit templates so loot checks are fast
    _load_digit_templates()

    # Break can happen before we even start
    maybe_take_break()

    # Step 0: Verify we're on home screen, get there if not
    _step("Step 0: Home screen check")
    logger.info("Step 0: Verifying home screen...")
    with deadline(120):
        check_connection_lost()
        ensure_coc_running()

    # Final check: attack button MUST be visible
    screen = capture_screenshot()
    pos = find_template(screen, "0_attack_button", threshold=0.7)
    dbg.save(screen, "home_check")
    if not pos:
        logger.error("Attack button not visible, aborting cycle")
        return

    # Step 1: Tap Attack on main screen
    _step("Step 1: Attack button")
    logger.info("Step 1: Tapping Attack button...")
    if not find_and_tap("0_attack_button", screenshot=screen, label="Attack"):
        logger.error("Attack button not found on screen")
        return
    time.sleep(1)

    # Step 2: Tap Find a Match (Battle, not Ranked)
    _step("Step 2: Find a Match")
    logger.info("Step 2: Tapping Find a Match...")
    if not find_and_tap("1_find_match_button", wait=3, label="Find a Match"):
        logger.error("Find a Match button not found")
        safe_press_back()
        return
    time.sleep(1)

    # Step 2.5: Request CC troops if no cooldown
    _step("Step 2.5: CC request")
    logger.info("Step 2.5: Checking CC troop request...")
    with deadline(120):
        request_cc_troops()

    # Step 3: Tap Attack on army confirmation screen
    _step("Step 3: Army confirm")
    logger.info("Step 3: Confirming army...")
    if not find_and_tap("2_army_attack_button", label="Army Attack"):
        logger.error("Army Attack button not found")
        safe_press_back()
        return

    # Wait for matchmaking to find a base
    logger.info("Waiting for matchmaking...")
    if not _wait_for_scout_screen(timeout=20.0):
        logger.warning("Scout screen not detected, proceeding anyway")

    # Block breaks during combat (loot search -> troop deploy)
    session.break_blocked = True

    # Event "dump" mode: skip the loot search entirely, throw the whole army
    # onto whatever base matchmaking gave us, then leave. Used to burn through
    # the army for event points (not to win).
    if cfg.dump_mode:
        _step("Dump mode: deploy army")
        logger.info("Dump mode ON -- deploying entire army for event points")
        zoom_out(random.randint(1, 5))
        time.sleep(0.5)
        swipe(960, 540, 1200, 700, 300)
        time.sleep(1)
        with deadline(120):
            deploy_dump()
        session.break_blocked = False
        event_window = max(15.0, float(cfg.broom_witch_battle_seconds))
        _step("Dump mode: crystal window")
        emit("battle_wait", cycle=cycle, mode="dump", seconds=event_window)
        logger.info(f"Dump mode: collecting crystals for {event_window:.1f}s before reset")
        time.sleep(event_window)

        _step("Dump mode: return home")
        try:
            with deadline(120):
                end_battle_and_go_home()
        except Exception as e:
            emit("battle_return_error", cycle=cycle, error=str(e))
            logger.warning(f"Dump mode return failed: {e}")
            try:
                dismiss_results_and_return_home()
            except Exception:
                pass

        post_attack_delay()
        emit("dump_cycle_complete", cycle=cycle, optimized=True, crystal_window=event_window)
        logger.info("=== Optimized dump attack cycle complete ===")
        return

    # Step 4: Check loot -- search for good opponent
    _step("Step 4: Loot search")
    logger.info("Step 4: Checking loot...")
    with deadline(240):
        found_loot = search_for_good_loot()
    if not found_loot:
        logger.warning("No good loot found, ending battle")
        session.break_blocked = False
        with deadline(120):
            end_battle_and_go_home()
        return

    # Determine attack side + resolve to plan
    attack_side = _resolve_attack_side()
    plan = PLANS_BY_KEY[attack_side]

    # Step 5: Good loot! Zoom out + center camera
    _step("Step 5: Zoom + camera")
    logger.info("Step 5: Zooming out + centering...")
    zoom_out(random.randint(1, 5))
    time.sleep(0.5)
    if attack_side == "bottom_right":
        swipe(960, 540, 700, 300, 300)
    else:
        swipe(960, 540, 1200, 700, 300)
    time.sleep(1)
    dbg.add_text(400, 540, f"Strategy: {attack_side}", "green")
    if dbg.is_enabled():
        dbg.save(capture_screenshot(), "zoomed")

    # Step 6: Deploy troops
    _step("Step 6: Deploy troops")
    logger.info("Step 6: Deploying troops...")
    with deadline(120):
        deploy_troops(plan)
    if dbg.is_enabled():
        dbg.save(capture_screenshot(), "deployed")

    # Unblock breaks -- troops deployed, safe to break
    session.break_blocked = False
    maybe_take_break()

    # Step 7: Wait for battle to end
    _step("Step 7: Battle wait")
    logger.info("Step 7: Waiting for battle result...")
    with deadline(240):
        wait_for_battle_end()
    if dbg.is_enabled():
        dbg.save(capture_screenshot(), "battle_end")

    # Step 8: Dismiss popups
    _step("Step 8: Dismiss popups")
    with deadline(120):
        dismiss_popups()
    if dbg.is_enabled():
        dbg.save(capture_screenshot(), "popups_done")

    # Break can happen before donations
    maybe_take_break()

    _step("Step 9: Donations")
    # Step 9: Check chat for donation requests
    if cfg.donate:
        logger.info("Step 9: Checking for donation requests...")
        with deadline(180):
            check_and_fill_donations()
    else:
        logger.info("Step 9: Donations disabled, skipping")
    if dbg.is_enabled():
        dbg.save(capture_screenshot(), "donations_done")

    # Step 10: Post-attack delay + random events
    _step("Step 10: Cooldown")
    logger.info("Step 10: Post-attack cooldown...")
    post_attack_delay()
    maybe_trigger_random_event(cycle)

    emit("attack_complete", cycle=cycle)
    logger.info("=== Attack cycle complete ===")


def run_loop():
    """Run attack cycles continuously, recovering from connection loss.

    BotStopRequested from any guardrail (template misses, restart budget,
    UNKNOWN state budget) exits cleanly via the outer handler.
    """
    try:
        _run_loop_impl()
    except BotStopRequested as e:
        logger.critical(f"Bot stopped: {e}")
        emit("bot_stopped", reason=str(e))


def _run_loop_impl():
    _schedule_next_break()
    cycle = 0
    max_cycles = cfg.max_cycles

    while True:
        cycle += 1
        emit("cycle_start", n=cycle)
        logger.info(f"========== LOOP CYCLE #{cycle} ==========")
        try:
            run_attack(cycle)
        except DeadlineExceeded as e:
            session.break_blocked = False
            logger.error(f"Timeout: {e}")
            try:
                screen = capture_screenshot()
                state = infer_state_from_screen(screen)
                logger.info(f"Screen state after timeout: {state.name}")
                _track_unknown_state(state)
                if state == BotState.HOME:
                    logger.info("Already home, continuing to next cycle")
                    continue
                elif state == BotState.DISCONNECTED:
                    check_connection_lost()
                    continue
                elif state == BotState.BATTLING:
                    end_battle_and_go_home()
                    continue
            except BotStopRequested:
                raise
            except Exception:
                pass
            logger.info("Force-restarting CoC (budgeted)...")
            _budgeted_force_restart()
            time.sleep(15)
            ensure_coc_running()
            continue
        except BotStopRequested:
            raise
        except Exception as e:
            session.break_blocked = False
            logger.error(f"Attack cycle failed: {e}")
            try:
                if check_connection_lost():
                    logger.info("Recovered from connection loss, continuing loop...")
                    continue
            except Exception:
                pass
            logger.info("Waiting 5s before retrying...")
            time.sleep(5)
            continue

        if max_cycles > 0 and cycle >= max_cycles:
            logger.info(f"Max cycles reached ({max_cycles}), stopping bot.")
            break

        logger.info("Cycle done, starting next...")


def run_screenshot_test():
    """Quick test: capture screenshot and save it."""
    import cv2

    screen = capture_screenshot()
    path = Path("screenshots") / "latest.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), screen):
        raise RuntimeError(f"Failed to save screenshot: {path}")
    logger.info(f"Saved screenshot: {path} ({screen.shape[1]}x{screen.shape[0]})")


def run_bottom_scout():
    """Test: enter attack, zoom out, swipe down.

    Take screenshot for bottom-right planning.
    """
    import cv2

    ensure_coc_running()

    screen = capture_screenshot()
    if not find_and_tap("0_attack_button", screenshot=screen, label="Attack"):
        logger.error("Attack button not found")
        return
    time.sleep(1)

    if not find_and_tap("1_find_match_button", wait=3, label="Find a Match"):
        logger.error("Find a Match not found")
        safe_press_back()
        return
    time.sleep(1)

    request_cc_troops()

    if not find_and_tap("2_army_attack_button", label="Army Attack"):
        logger.error("Army Attack not found")
        safe_press_back()
        return

    logger.info("Waiting for matchmaking...")
    _wait_for_scout_screen(timeout=20.0)

    zoom_out(random.randint(1, 5))
    time.sleep(0.5)
    swipe(960, 540, 700, 300, 300)  # Swipe camera down-right
    time.sleep(1)

    screen = capture_screenshot()
    cv2.imwrite("screenshots/bottom_scout.png", screen)
    logger.info("Saved screenshots/bottom_scout.png — check bottom-right positions")
