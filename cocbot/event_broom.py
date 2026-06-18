"""Fast Broom Witch event deployment helpers.

The generic dump deploy is intentionally broad, but it is too slow for event
farming. This module keeps Broom Witch attacks bounded and fast: deploy heroes
first, dump Broom Witches along high-value perimeter lanes until depleted, drop
Rage into the core path, then trigger Eternal Tome after a short configurable
wait.
"""

from __future__ import annotations

import random
import time

from loguru import logger

from cocbot.config import cfg
from cocbot.army import (
    activate_warden_abilities,
    configured_broom_witch_slots,
    deploy_heroes,
    deploy_rage_spells,
    get_army_config,
)
from cocbot.io import capture_screenshot, tap
from cocbot.plans import TROOP_BAR_Y
from cocbot.session import check_deadline, emit
from cocbot.vision import find_troop_slots, is_troop_available

# Valid green-ring lanes around common base edges. Ordered for fast event spam:
# bottom-right first, then right/top-left pressure points. Broom Witches work best
# when they enter quickly from one edge and flow toward Wizard Tower clusters.
WIZARD_TOWER_PRESSURE_POINTS: tuple[tuple[int, int], ...] = (
    # bottom-right pressure lane
    (1170, 760),
    (1310, 680),
    (1430, 600),
    (1540, 520),
    # top-right / right edge
    (1050, 165),
    (1175, 235),
    (1305, 315),
    (1430, 400),
    # top-left / left edge backups
    (870, 180),
    (760, 245),
    (635, 320),
    (505, 400),
    (380, 500),
)

# io.tap already adds a random 0..80ms after this value, so 70ms becomes about
# 70-150ms between taps. That is fast without becoming an instant tap burst.
MIN_SAFE_TAP_DELAY = 0.07


def _jitter_point(x: int, y: int, radius: int = 10) -> tuple[int, int]:
    """Apply small deployment jitter while staying close to a chosen lane."""
    return x + random.randint(-radius, radius), y + random.randint(-radius, radius)


def _sleep_interruptible(seconds: float, label: str) -> None:
    """Sleep in short chunks so Stop requests do not feel laggy."""
    remaining = max(0.0, float(seconds))
    while remaining > 0:
        check_deadline(label)
        chunk = min(0.1, remaining)
        time.sleep(chunk)
        remaining -= chunk


def _configured_slot_xs() -> list[int]:
    """Backward-compatible wrapper for tests and older callers."""
    return configured_broom_witch_slots()


def _broom_witch_slot_xs() -> list[int]:
    """Prefer live troop-bar detection, then fall back to configured slots.

    The old default listed several X positions, which can accidentally select
    heroes/spells after the first troop. Broom Witch normally appears as one
    troop-bar slot with a quantity counter, so dynamic detection or a single
    configured slot is safer and faster.
    """
    try:
        slots = find_troop_slots(capture_screenshot())
    except Exception as exc:  # Vision/capture failure should not kill deploy.
        logger.debug("Broom Witch slot detection failed; using configured slots: {}", exc)
        return _configured_slot_xs()

    if "broom_witch" in slots:
        return [int(slots["broom_witch"])]
    return _configured_slot_xs()


def _slot_still_available(slot_x: int) -> bool:
    """Return whether the configured Broom Witch slot still has troops."""
    try:
        screen = capture_screenshot()
        return is_troop_available(screen, "broom_witch", slot_x)
    except Exception as exc:
        # If availability cannot be measured, continue using the bounded max
        # rounds. This favors finishing deployment over silently skipping troops.
        logger.debug("Could not verify Broom Witch availability at x={}: {}", slot_x, exc)
        return True


def broom_witch_wave_points(round_index: int) -> list[tuple[int, int]]:
    """Return an ordered, per-round pressure-point list."""
    points = list(WIZARD_TOWER_PRESSURE_POINTS)
    if round_index > 0:
        # Keep the same lanes but prevent identical replay patterns.
        random.shuffle(points)
    return points


def _max_rounds() -> int:
    return max(
        1,
        int(getattr(cfg, "broom_witch_max_rounds", getattr(cfg, "broom_witch_waves", 3))),
    )


def _taps_per_round() -> int:
    return max(1, int(getattr(cfg, "broom_witch_taps_per_round", 8)))


def estimated_broom_witch_taps(waves: int | None = None) -> int:
    """Estimate tap volume for Broom Witch deployment.

    Counts one troop-slot select per configured slot per round plus the bounded
    number of edge deployment taps. The estimate intentionally uses configured
    slots only, because live slot detection requires a screenshot.
    """
    round_count = max(1, int(waves if waves is not None else _max_rounds()))
    taps_per_round = min(_taps_per_round(), len(WIZARD_TOWER_PRESSURE_POINTS))
    return round_count * len(_configured_slot_xs()) * (1 + taps_per_round)


def deploy_broom_witches() -> None:
    """Fast-deploy Broom Witches for Magical Crystal farming.

    Flow:
      1. Deploy Grand Warden early.
      2. Dump Broom Witches along the pressure edge until depleted or capped.
      3. Drop Rage spells into the core path.
      4. Activate Eternal Tome after the short configured delay.
    """
    army_config = get_army_config("broom_witch")
    slot_xs = _broom_witch_slot_xs()
    max_rounds = _max_rounds()
    taps_per_round = _taps_per_round()
    tap_delay = max(MIN_SAFE_TAP_DELAY, float(getattr(cfg, "broom_witch_tap_delay", 0.07)))
    round_delay = max(0.0, float(getattr(cfg, "broom_witch_round_delay", getattr(cfg, "broom_witch_wave_pause", 0.25))))
    hero_delay = max(0.0, float(getattr(cfg, "broom_witch_hero_delay", 0.15)))

    logger.info(
        "Broom Witch deploy: max_rounds={}, slot_xs={}, taps_per_round={}, est_taps={}",
        max_rounds,
        slot_xs,
        taps_per_round,
        estimated_broom_witch_taps(max_rounds),
    )
    emit(
        "broom_witch_deploy_start",
        max_rounds=max_rounds,
        slot_xs=slot_xs,
        taps_per_round=taps_per_round,
        estimated_taps=estimated_broom_witch_taps(max_rounds),
    )

    deploy_heroes(army_config)
    if hero_delay:
        _sleep_interruptible(hero_delay, "Broom Witch hero deploy")

    logger.info("Deploying Broom Witches along event pressure edge until depleted...")
    rounds = 0
    while rounds < max_rounds:
        check_deadline("Broom Witch deploy")
        points = broom_witch_wave_points(rounds)[:taps_per_round]
        deployed_this_round = False
        for slot_x in slot_xs:
            check_deadline("Broom Witch deploy")
            if not _slot_still_available(slot_x):
                continue
            tap(slot_x, TROOP_BAR_Y, delay=tap_delay)
            deployed_this_round = True
            for x, y in points:
                jx, jy = _jitter_point(x, y)
                tap(jx, jy, delay=tap_delay)

        if not deployed_this_round:
            break

        rounds += 1
        if rounds < max_rounds:
            _sleep_interruptible(round_delay, "Broom Witch round delay")

    logger.info("Broom Witches depleted after {} rounds", rounds)

    deploy_rage_spells(army_config)
    activate_warden_abilities(army_config, timing="core")

    logger.info("Fast Broom Witch deploy complete")
    emit(
        "broom_witch_deploy_complete",
        rounds=rounds,
        slot_xs=slot_xs,
        preset=army_config["name"],
    )
