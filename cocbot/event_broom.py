"""Broom Witch event deployment helpers.

The normal dump deploy is intentionally generic, but it is expensive for event
farming: it sweeps many troop-bar positions and sprays every perimeter point.
For Magical Crystal farming the faster path is to use configured Broom Witch
slots and deploy controlled waves onto lanes that pressure peripheral Wizard
Towers first.

This module is pure deployment orchestration: no image recognition and no bot
state. It is safe to unit-test by monkeypatching ``tap`` and ``time.sleep``.
"""

from __future__ import annotations

import random
import time

from loguru import logger

from cocbot.config import cfg
from cocbot.io import tap
from cocbot.plans import TROOP_BAR_Y
from cocbot.session import check_deadline, emit

# Valid green-ring lanes around common base edges. These are intentionally near
# the perimeter: Broom Witches retarget Wizard Towers well when they enter from
# multiple outside lanes instead of being stacked in one corner.
WIZARD_TOWER_PRESSURE_POINTS: tuple[tuple[int, int], ...] = (
    # top-left / left edge
    (870, 180),
    (760, 245),
    (635, 320),
    (505, 400),
    (380, 500),
    # top-right / right edge
    (1050, 165),
    (1175, 235),
    (1305, 315),
    (1430, 400),
    (1545, 505),
    # bottom-right pressure lane
    (1170, 760),
    (1310, 680),
    (1430, 600),
    (1540, 520),
)

# Human-safe minimum. io.tap already adds random 0..80ms after this value, so
# 70ms becomes roughly 70-150ms between taps and avoids rapid-fire bursts.
MIN_SAFE_TAP_DELAY = 0.07


def _jitter_point(x: int, y: int, radius: int = 10) -> tuple[int, int]:
    """Apply small deployment jitter while staying close to a chosen lane."""
    return x + random.randint(-radius, radius), y + random.randint(-radius, radius)


def _configured_slot_xs() -> list[int]:
    """Return bounded troop-bar X coordinates for event deployment.

    Broom Witch/event armies can occupy multiple troop-bar slots. The previous
    v1.4.1 commit changed deployment to call this helper but failed to commit
    the helper itself, causing ``NameError: _configured_slot_xs`` at runtime.

    Values come from ``cfg.broom_witch_slot_xs`` as a comma/semicolon separated
    string, with ``cfg.broom_witch_slot_x`` retained as a legacy fallback.
    Coordinates are bounded to the visible troop bar area and deduplicated.
    """
    raw = str(getattr(cfg, "broom_witch_slot_xs", "") or "")
    slots: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            x = int(float(chunk))
        except ValueError:
            logger.warning(f"Ignoring invalid Broom Witch slot x={chunk!r}")
            continue
        if 120 <= x <= 1510 and x not in slots:
            slots.append(x)

    if not slots:
        slots = [int(getattr(cfg, "broom_witch_slot_x", 250))]
    return slots[:8]


def broom_witch_wave_points(wave: int) -> list[tuple[int, int]]:
    """Return an ordered, per-wave pressure-point list.

    Wave 1 prioritizes outside Wizard Tower lanes. Later waves are shuffled to
    avoid deterministic repeats while still covering the same high-value ring.
    """
    points = list(WIZARD_TOWER_PRESSURE_POINTS)
    if wave > 0:
        random.shuffle(points)
    return points


def estimated_broom_witch_taps(waves: int | None = None) -> int:
    """Estimate tap volume for Broom Witch deployment.

    Counts one troop-slot select per configured slot per wave plus one tap per
    pressure point for each selected slot.
    """
    wave_count = max(1, int(waves if waves is not None else cfg.broom_witch_waves))
    return wave_count * len(_configured_slot_xs()) * (
        1 + len(WIZARD_TOWER_PRESSURE_POINTS)
    )


def deploy_broom_witches() -> None:
    """Deploy Broom Witches in controlled waves for event-point farming.

    The function uses configured troop-bar slots instead of scanning images,
    then deploys each slot across perimeter Wizard Tower pressure lanes. This
    keeps deployment bounded while still emptying multiple event troop stacks.
    """
    slot_xs = _configured_slot_xs()
    waves = max(1, int(cfg.broom_witch_waves))
    tap_delay = max(MIN_SAFE_TAP_DELAY, float(cfg.broom_witch_tap_delay))
    wave_pause = max(0.35, float(cfg.broom_witch_wave_pause))

    logger.info(
        "Broom Witch deploy: %s waves, slot_xs=%s, est_taps=%s",
        waves,
        slot_xs,
        estimated_broom_witch_taps(waves),
    )
    emit(
        "broom_witch_deploy_start",
        waves=waves,
        slot_xs=slot_xs,
        estimated_taps=estimated_broom_witch_taps(waves),
    )

    for wave in range(waves):
        check_deadline("Broom Witch deploy")
        points = broom_witch_wave_points(wave)
        for slot_x in slot_xs:
            check_deadline("Broom Witch deploy")
            tap(slot_x, TROOP_BAR_Y, delay=tap_delay)
            for x, y in points:
                jx, jy = _jitter_point(x, y)
                tap(jx, jy, delay=tap_delay)
        if wave != waves - 1:
            time.sleep(wave_pause + random.uniform(0.0, 0.25))

    logger.info("Broom Witch deploy complete")
    emit("broom_witch_deploy_complete", waves=waves, slot_xs=slot_xs)
