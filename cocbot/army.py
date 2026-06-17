"""Config-driven army presets and event deployment helpers."""

from __future__ import annotations

import random
import time
from copy import deepcopy
from typing import Any

from loguru import logger

from cocbot.config import cfg
from cocbot.io import tap
from cocbot.plans import TROOP_BAR_Y
from cocbot.session import check_deadline, emit

CORE_RAGE_POINTS: tuple[tuple[int, int], ...] = ((930, 430), (1030, 470), (960, 545), (1080, 590))
WARDEN_ENTRY_POINTS: tuple[tuple[int, int], ...] = ((900, 230), (1020, 230), (1160, 300))

ARMY_PRESETS: dict[str, dict[str, Any]] = {
    "broom_witch": {
        "name": "broom_witch",
        "troops": [{"name": "broom_witch", "quantity": "fill_camps", "slot_source": "broom_witch_slot_xs"}],
        "spells": [{"name": "spell_rage", "quantity": "fill_spells", "slot_source": "rage_slot_x"}],
        "heroes": [{"name": "warden", "slot_source": "warden_slot_x", "ability": "eternal_tome"}],
        "deployment_order": ["broom_witch", "warden", "rage", "eternal_tome"],
        "timing": {"rage_after_wave": 1, "warden_after_wave": 0, "tome_after_seconds": 8.0},
    },
    "electro_dragon": {
        "name": "electro_dragon",
        "troops": [
            {"name": "queen", "quantity": 1},
            {"name": "barracks", "quantity": 1},
            {"name": "baby_dragon", "quantity": 3},
            {"name": "edrag", "quantity": "until_empty"},
            {"name": "dragon_rider", "quantity": "until_empty"},
            {"name": "warden", "quantity": 1},
            {"name": "minion_prince", "quantity": 1},
            {"name": "duke", "quantity": 1},
        ],
        "spells": [{"name": "spell_rage", "quantity": 4}, {"name": "spell_totem", "quantity": 4}],
        "heroes": [
            {"name": "queen", "ability": "immediate"},
            {"name": "warden", "ability": "core"},
            {"name": "minion_prince", "ability": "post_deploy"},
        ],
        "deployment_order": ["queen", "barracks", "baby_dragon", "edrag", "dragon_rider", "warden", "minion_prince", "duke", "spell_rage", "spell_totem"],
    },
}


def active_preset_name() -> str:
    name = str(getattr(cfg, "army_preset", "broom_witch") or "broom_witch").strip().lower()
    if name not in ARMY_PRESETS:
        logger.warning(f"Unknown ARMY_PRESET={name!r}; falling back to broom_witch")
        return "broom_witch"
    return name


def get_army_config(name: str | None = None) -> dict[str, Any]:
    preset = (name or active_preset_name()).strip().lower()
    return deepcopy(ARMY_PRESETS.get(preset, ARMY_PRESETS["broom_witch"]))


def _parse_slot_list(raw: str, fallback: int) -> list[int]:
    slots: list[int] = []
    for chunk in str(raw or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            x = int(float(chunk))
        except ValueError:
            logger.warning(f"Ignoring invalid troop slot x={chunk!r}")
            continue
        if 120 <= x <= 1510 and x not in slots:
            slots.append(x)
    return slots or [fallback]


def configured_broom_witch_slots() -> list[int]:
    return _parse_slot_list(getattr(cfg, "broom_witch_slot_xs", ""), int(getattr(cfg, "broom_witch_slot_x", 250)))[:8]


def deploy_heroes(army_config: dict[str, Any], deploy_points: list[tuple[int, int]] | tuple[tuple[int, int], ...] = WARDEN_ENTRY_POINTS) -> None:
    hero_names = {hero.get("name") for hero in army_config.get("heroes", [])}
    if "warden" not in hero_names:
        return
    warden_slot = int(getattr(cfg, "warden_slot_x", 1370))
    logger.info("Deploying Grand Warden for event push")
    emit("hero_deploy", hero="warden", slot_x=warden_slot)
    tap(warden_slot, TROOP_BAR_Y, delay=0.08)
    for x, y in list(deploy_points)[:3]:
        check_deadline("Deploy Warden")
        tap(x + random.randint(-15, 15), y + random.randint(-15, 15), delay=0.07)


def deploy_rage_spells(army_config: dict[str, Any], rage_points: list[tuple[int, int]] | tuple[tuple[int, int], ...] = CORE_RAGE_POINTS) -> None:
    spells = {spell.get("name") for spell in army_config.get("spells", [])}
    if "spell_rage" not in spells:
        return
    rage_slot = int(getattr(cfg, "rage_slot_x", 1290))
    count = max(1, int(getattr(cfg, "rage_spell_count", 3)))
    logger.info(f"Dropping {count} Rage spells for Broom Witch core push")
    emit("spell_deploy", spell="rage", slot_x=rage_slot, count=count)
    tap(rage_slot, TROOP_BAR_Y, delay=0.08)
    points = list(rage_points)
    for i in range(count):
        check_deadline("Deploy Rage")
        x, y = points[i % len(points)]
        tap(x + random.randint(-45, 45), y + random.randint(-45, 45), delay=0.08)


def activate_warden_abilities(army_config: dict[str, Any], timing: str = "core") -> None:
    hero_names = {hero.get("name") for hero in army_config.get("heroes", [])}
    if "warden" not in hero_names:
        return
    delay = max(0.0, float(getattr(cfg, "warden_tome_delay", 8.0)))
    if delay:
        logger.info(f"Waiting {delay:.1f}s before Eternal Tome ({timing})")
        time.sleep(delay)
    warden_slot = int(getattr(cfg, "warden_slot_x", 1370))
    logger.info("Activating Grand Warden Eternal Tome")
    emit("hero_ability", hero="warden", ability="eternal_tome", timing=timing)
    tap(warden_slot, TROOP_BAR_Y, delay=0.08)
