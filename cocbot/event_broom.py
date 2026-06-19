"""Fast Broom Witch event deployment helpers.

The generic dump deploy is intentionally broad, but it is too slow for event
farming. This module keeps Broom Witch attacks bounded and fast while also
ensuring that **every** hero and **every** spell in the preset is used:

  1. Deploy ALL heroes (Queen, Warden, Minion Prince, Duke) on their lanes.
  2. Spam Broom Witches along the pressure edge with multiple taps per drop
     point so the slot is depleted quickly and efficiently.
  3. Drop ALL spells (Rage, Heal, Totem) on distinct lanes covering the core
     push and funnels.
  4. Activate ALL hero abilities (Queen's Royal Cloak, Warden's Eternal Tome,
     Minion Prince's Dark Quill, Duke's ability) after a short delay.
"""

from __future__ import annotations

import random
import time

from loguru import logger

from cocbot.config import cfg
from cocbot.army import (
    activate_all_hero_abilities,
    configured_broom_witch_slots,
    deploy_all_spells,
    deploy_heroes,
    get_army_config,
)
from cocbot.io import batch_tap, capture_screenshot, tap
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


def _taps_per_point() -> int:
    """Number of rapid taps to perform at each deployment point.

    Higher values deplete the troop slot faster (more Broom Witches dropped
    per point per round). Capped so a single point is not hammered forever
    if availability detection fails.
    """
    return max(1, min(6, int(getattr(cfg, "broom_witch_taps_per_point", 2))))


def estimated_broom_witch_taps(waves: int | None = None) -> int:
    """Estimate tap volume for Broom Witch deployment.

    Counts one troop-slot select per configured slot per round plus the bounded
    number of edge deployment taps. The estimate intentionally uses configured
    slots only, because live slot detection requires a screenshot.
    """
    round_count = max(1, int(waves if waves is not None else _max_rounds()))
    taps_per_round = min(_taps_per_round(), len(WIZARD_TOWER_PRESSURE_POINTS))
    taps_per_point = _taps_per_point()
    return round_count * len(_configured_slot_xs()) * (1 + taps_per_round * taps_per_point)


def _spam_broom_witches(
    slot_xs: list[int],
    max_rounds: int,
    taps_per_round: int,
    taps_per_point: int,
    tap_delay: float,
    round_delay: float,
) -> int:
    """Spam Broom Witches along the pressure edge until depleted or capped.

    Uses :func:`batch_tap` so an entire round (slot re-select + all drop
    points) runs in a **single** ADB shell call instead of one subprocess
    spawn per tap. This is what makes the spam fast enough to empty the slot
    inside the event crystal window.

    Returns the number of completed rounds.
    """
    logger.info("Deploying Broom Witches along event pressure edge until depleted...")
    rounds = 0
    while rounds < max_rounds:
        check_deadline("Broom Witch deploy")
        points = broom_witch_wave_points(rounds)[:taps_per_round]

        # Verify at least one slot still has troops before issuing the round.
        active_slots = [sx for sx in slot_xs if _slot_still_available(sx)]
        if not active_slots:
            logger.info("All Broom Witch slots depleted; stopping spam")
            break

        # Build the entire round as a list of (x, y, delay) tuples, then
        # execute it via a single batched ADB call. This converts ~50-150
        # subprocess spawns per round into 1-3.
        round_taps: list[tuple[int, int, float]] = []
        for slot_x in active_slots:
            # Re-select the slot once per round to keep the troop active,
            # then tap every pressure point taps_per_point times.
            round_taps.append((slot_x, TROOP_BAR_Y, tap_delay))
            for x, y in points:
                jx, jy = _jitter_point(x, y)
                for _ in range(taps_per_point):
                    round_taps.append((jx, jy, tap_delay))

        check_deadline("Broom Witch deploy")
        batch_tap(round_taps)
        rounds += 1

        if rounds < max_rounds:
            _sleep_interruptible(round_delay, "Broom Witch round delay")

    logger.info("Broom Witches depleted after {} rounds", rounds)
    return rounds


def deploy_broom_witches() -> None:
    """Fast-deploy Broom Witches for Magical Crystal farming.

    Flow:
      1. Deploy ALL heroes (Queen, Warden, Minion Prince, Duke).
      2. Spam Broom Witches along the pressure edge until depleted or capped.
      3. Drop ALL spells (Rage, Heal, Totem) across distinct lanes.
      4. Activate ALL hero abilities after a short configurable delay.
    """
    army_config = get_army_config("broom_witch")
    slot_xs = _broom_witch_slot_xs()
    max_rounds = _max_rounds()
    taps_per_round = _taps_per_round()
    taps_per_point = _taps_per_point()
    tap_delay = max(MIN_SAFE_TAP_DELAY, float(getattr(cfg, "broom_witch_tap_delay", 0.07)))
    round_delay = max(0.0, float(getattr(cfg, "broom_witch_round_delay", getattr(cfg, "broom_witch_wave_pause", 0.25))))
    hero_delay = max(0.0, float(getattr(cfg, "broom_witch_hero_delay", 0.15)))

    logger.info(
        "Broom Witch deploy: max_rounds={}, slot_xs={}, taps_per_round={}, taps_per_point={}, est_taps={}",
        max_rounds,
        slot_xs,
        taps_per_round,
        taps_per_point,
        estimated_broom_witch_taps(max_rounds),
    )
    emit(
        "broom_witch_deploy_start",
        max_rounds=max_rounds,
        slot_xs=slot_xs,
        taps_per_round=taps_per_round,
        taps_per_point=taps_per_point,
        estimated_taps=estimated_broom_witch_taps(max_rounds),
    )

    # 1. Deploy every hero configured in the preset.
    deploy_heroes(army_config)
    if hero_delay:
        _sleep_interruptible(hero_delay, "Broom Witch hero deploy")

    # 2. Spam Broom Witches fast along the pressure edge.
    rounds = _spam_broom_witches(
        slot_xs=slot_xs,
        max_rounds=max_rounds,
        taps_per_round=taps_per_round,
        taps_per_point=taps_per_point,
        tap_delay=tap_delay,
        round_delay=round_delay,
    )

    # 3. Drop every spell (Rage, Heal, Totem) on distinct lanes so the entire
    #    spell inventory is consumed and contributes to the push.
    deploy_all_spells(army_config)

    # 4. Activate every hero ability (Queen, Warden Eternal Tome, Minion Prince,
    #    Duke) so no hero is left without using its ability.
    activate_all_hero_abilities(army_config)

    logger.info("Fast Broom Witch deploy complete")
    emit(
        "broom_witch_deploy_complete",
        rounds=rounds,
        slot_xs=slot_xs,
        preset=army_config["name"],
    )