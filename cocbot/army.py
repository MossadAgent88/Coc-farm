"""Config-driven army presets and event deployment helpers.

The deployment functions in this module are designed to be fast and
complete. For event modes (such as Broom Witch) every hero and spell
configured in the preset is deployed:

* Heroes (Queen, Warden, Minion Prince, Duke) are dropped on their own
  entry points, and their abilities are activated after a short delay.
* Spells (Rage, Heal, Totem) are dropped on the core attack path and
  follow-up funnels so the army benefits from every spell slot.
"""

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

# ── Deployment coordinates (1920x1080 LDPlayer) ──
CORE_RAGE_POINTS: tuple[tuple[int, int], ...] = (
    (930, 430),
    (1030, 470),
    (960, 545),
    (1080, 590),
)
WARDEN_ENTRY_POINTS: tuple[tuple[int, int], ...] = (
    (900, 230),
    (1020, 230),
    (1160, 300),
)
QUEEN_ENTRY_POINTS: tuple[tuple[int, int], ...] = (
    (760, 245),
    (870, 180),
    (505, 400),
)
MINION_PRINCE_ENTRY_POINTS: tuple[tuple[int, int], ...] = (
    (1305, 315),
    (1430, 400),
    (1050, 165),
)
DUKE_ENTRY_POINTS: tuple[tuple[int, int], ...] = (
    (1170, 760),
    (1310, 680),
    (1540, 520),
)

# Spell drop points — spread across the core + funnels so every spell slot
# contributes to the push. Each spell type uses a distinct lane to avoid
# stacking identical spell effects on a single tile.
RAGE_DROP_POINTS: tuple[tuple[int, int], ...] = (
    (960, 480),
    (1010, 540),
    (900, 560),
    (1060, 610),
)
HEAL_DROP_POINTS: tuple[tuple[int, int], ...] = (
    (980, 500),
    (1040, 580),
    (920, 540),
    (1100, 470),
)
TOTEM_DROP_POINTS: tuple[tuple[int, int], ...] = (
    (990, 460),
    (940, 520),
    (1050, 560),
    (1010, 470),
)

# Per-hero defaults for slot X in the troop bar (1920x1080). These are
# reasonable fallbacks when vision detection is unavailable. They can be
# overridden from settings via `cfg.<hero>_slot_x`.
_HERO_DEFAULT_SLOT_X = {
    "queen": 1300,
    "warden": 1370,
    "king": 1430,
    "minion_prince": 1490,
    "duke": 1550,
}

# Per-spell defaults for slot X in the troop bar.
_SPELL_DEFAULT_SLOT_X = {
    "spell_rage": 1290,
    "spell_heal": 1230,
    "spell_totem": 1350,
}


ARMY_PRESETS: dict[str, dict[str, Any]] = {
    "broom_witch": {
        "name": "broom_witch",
        "troops": [
            {"name": "broom_witch", "quantity": "fill_camps", "slot_source": "broom_witch_slot_xs"}
        ],
        "spells": [
            {"name": "spell_rage", "quantity": "fill_spells", "slot_source": "rage_slot_x"},
            {"name": "spell_heal", "quantity": "fill_spells", "slot_source": "heal_slot_x"},
            {"name": "spell_totem", "quantity": "fill_spells", "slot_source": "totem_slot_x"},
        ],
        "heroes": [
            {"name": "queen", "slot_source": "queen_slot_x", "ability": "immediate"},
            {"name": "warden", "slot_source": "warden_slot_x", "ability": "eternal_tome"},
            {"name": "minion_prince", "slot_source": "minion_prince_slot_x", "ability": "post_deploy"},
            {"name": "duke", "slot_source": "duke_slot_x", "ability": "post_deploy"},
        ],
        "deployment_order": [
            "queen",
            "warden",
            "broom_witch",
            "spell_rage",
            "spell_heal",
            "spell_totem",
            "minion_prince",
            "duke",
            "eternal_tome",
        ],
        "timing": {
            "rage_after_wave": 1,
            "warden_after_wave": 0,
            "tome_after_seconds": 3.0,
            "hero_ability_delay": 2.5,
        },
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
        "spells": [
            {"name": "spell_rage", "quantity": 4},
            {"name": "spell_heal", "quantity": 2},
            {"name": "spell_totem", "quantity": 2},
        ],
        "heroes": [
            {"name": "queen", "ability": "immediate"},
            {"name": "warden", "ability": "core"},
            {"name": "minion_prince", "ability": "post_deploy"},
        ],
        "deployment_order": [
            "queen",
            "barracks",
            "baby_dragon",
            "edrag",
            "dragon_rider",
            "warden",
            "minion_prince",
            "duke",
            "spell_rage",
            "spell_heal",
            "spell_totem",
        ],
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
    return _parse_slot_list(
        getattr(cfg, "broom_witch_slot_xs", ""),
        int(getattr(cfg, "broom_witch_slot_x", 250)),
    )[:8]


# ── Slot resolution helpers ──


def _hero_slot_x(hero_name: str) -> int:
    """Resolve the troop-bar X for a hero using cfg + fallback map."""
    cfg_key = f"{hero_name}_slot_x"
    default = _HERO_DEFAULT_SLOT_X.get(hero_name, 1370)
    return int(getattr(cfg, cfg_key, default))


def _spell_slot_x(spell_name: str) -> int:
    """Resolve the troop-bar X for a spell using cfg + fallback map."""
    cfg_key = f"{spell_name}_slot_x"
    # Legacy aliases.
    if spell_name == "spell_rage":
        cfg_key = "rage_slot_x"
    default = _SPELL_DEFAULT_SLOT_X.get(spell_name, 1290)
    return int(getattr(cfg, cfg_key, default))


def _ability_delay(army_config: dict[str, Any]) -> float:
    return max(0.0, float(army_config.get("timing", {}).get("hero_ability_delay", 2.5)))


def _tap_delay(key: str, default: float) -> float:
    return max(0.0, float(getattr(cfg, key, default)))


def _jitter(x: int, y: int, radius: int = 15) -> tuple[int, int]:
    return x + random.randint(-radius, radius), y + random.randint(-radius, radius)


# ── Hero deployment ──


def _hero_entry_points(hero_name: str) -> tuple[tuple[int, int], ...]:
    return {
        "queen": QUEEN_ENTRY_POINTS,
        "warden": WARDEN_ENTRY_POINTS,
        "minion_prince": MINION_PRINCE_ENTRY_POINTS,
        "duke": DUKE_ENTRY_POINTS,
    }.get(hero_name, WARDEN_ENTRY_POINTS)


def _deploy_single_hero(hero: dict[str, Any], delay: float) -> None:
    hero_name = hero.get("name")
    if not hero_name:
        return
    slot_x = _hero_slot_x(hero_name)
    entry_points = _hero_entry_points(hero_name)
    logger.info("Deploying hero {} at slot x={}", hero_name, slot_x)
    emit("hero_deploy", hero=hero_name, slot_x=slot_x)
    tap(slot_x, TROOP_BAR_Y, delay=delay)
    for x, y in list(entry_points)[:3]:
        check_deadline(f"Deploy {hero_name}")
        jx, jy = _jitter(x, y)
        tap(jx, jy, delay=delay)


def deploy_heroes(
    army_config: dict[str, Any],
    deploy_points: list[tuple[int, int]] | tuple[tuple[int, int], ...] = WARDEN_ENTRY_POINTS,
) -> None:
    """Deploy every hero in the preset.

    The optional `deploy_points` argument is kept for backward compatibility
    for callers that only knew about the Grand Warden; when present it is
    used as the entry-point list for the Warden specifically.
    """
    heroes = army_config.get("heroes", [])
    if not heroes:
        return
    delay = _tap_delay("broom_witch_hero_delay", 0.15)

    for hero in heroes:
        if not hero.get("name"):
            continue
        _deploy_single_hero(hero, delay)

    logger.info("Hero deployment complete for {} hero(es)", len(heroes))


def activate_hero_ability(hero_name: str, timing: str = "core") -> None:
    """Activate a hero's ability after a short delay.

    The ability is triggered by tapping the hero slot again in the troop bar.
    """
    slot_x = _hero_slot_x(hero_name)
    delay = _tap_delay("broom_witch_hero_delay", 0.15)
    logger.info("Activating {} ability (timing={})", hero_name, timing)
    emit("hero_ability", hero=hero_name, ability=timing, slot_x=slot_x)
    tap(slot_x, TROOP_BAR_Y, delay=delay)


def activate_warden_abilities(army_config: dict[str, Any], timing: str = "core") -> None:
    """Backward-compatible Warden ability activator.

    Newer callers should use `activate_all_hero_abilities()` to trigger
    every hero's ability.
    """
    hero_names = {hero.get("name") for hero in army_config.get("heroes", [])}
    if "warden" not in hero_names:
        return
    delay = max(
        0.0,
        float(
            getattr(
                cfg,
                "warden_tome_delay",
                army_config.get("timing", {}).get("tome_after_seconds", 3.0),
            )
        ),
    )
    if delay:
        logger.info("Waiting {:.1f}s before Eternal Tome", delay)
        _interruptible_sleep(delay, "Eternal Tome wait")
    activate_hero_ability("warden", timing="eternal_tome")


def activate_all_hero_abilities(army_config: dict[str, Any]) -> None:
    """Activate abilities for every hero that has one configured."""
    heroes = army_config.get("heroes", [])
    if not heroes:
        return
    ability_delay = _ability_delay(army_config)
    logger.info("Activating abilities for {} hero(es) after {:.1f}s", len(heroes), ability_delay)
    if ability_delay:
        _interruptible_sleep(ability_delay, "Hero ability wait")

    for hero in heroes:
        hero_name = hero.get("name")
        ability = hero.get("ability")
        if not hero_name or not ability:
            continue
        check_deadline(f"Activate {hero_name} ability")
        # The Warden uses the configurable tome delay via the legacy function.
        if hero_name == "warden":
            activate_warden_abilities(army_config, timing="eternal_tome")
            continue
        activate_hero_ability(hero_name, timing=ability)


# ── Spell deployment ──


def _drop_spell(spell_name: str, count: int, drop_points: tuple[tuple[int, int], ...]) -> None:
    slot_x = _spell_slot_x(spell_name)
    delay = _tap_delay("broom_witch_spell_delay", 0.12)
    logger.info("Dropping {} x{} ({})", spell_name, count, spell_name.replace("spell_", ""))
    emit("spell_deploy", spell=spell_name, slot_x=slot_x, count=count)
    tap(slot_x, TROOP_BAR_Y, delay=delay)
    for i in range(count):
        check_deadline(f"Deploy {spell_name}")
        x, y = drop_points[i % len(drop_points)]
        jx, jy = _jitter(x, y, radius=45)
        tap(jx, jy, delay=delay)


def deploy_rage_spells(
    army_config: dict[str, Any],
    rage_points: list[tuple[int, int]] | tuple[tuple[int, int], ...] = RAGE_DROP_POINTS,
) -> None:
    """Drop all Rage spells configured in the preset."""
    spells = {spell.get("name"): spell for spell in army_config.get("spells", [])}
    if "spell_rage" not in spells:
        return
    count = max(1, int(getattr(cfg, "rage_spell_count", 4)))
    points = tuple(rage_points) if rage_points else RAGE_DROP_POINTS
    _drop_spell("spell_rage", count, points)


def deploy_all_spells(army_config: dict[str, Any]) -> None:
    """Deploy every spell configured in the preset.

    Each spell type uses a distinct drop-point lane so effects do not stack
    on the same tile, and so the whole spell inventory is consumed.
    """
    spells = army_config.get("spells", [])
    if not spells:
        return
    for spell in spells:
        spell_name = spell.get("name")
        if not spell_name:
            continue
        count = _resolve_spell_count(spell_name)
        if count <= 0:
            continue
        drop_points = _spell_drop_points(spell_name)
        _drop_spell(spell_name, count, drop_points)


def _resolve_spell_count(spell_name: str) -> int:
    """Resolve spell quantity from cfg or a sensible default per spell type."""
    cfg_key_map = {
        "spell_rage": "rage_spell_count",
        "spell_heal": "heal_spell_count",
        "spell_totem": "totem_spell_count",
    }
    default_map = {
        "spell_rage": 4,
        "spell_heal": 2,
        "spell_totem": 2,
    }
    return max(0, int(getattr(cfg, cfg_key_map.get(spell_name, ""), default_map.get(spell_name, 1))))


def _spell_drop_points(spell_name: str) -> tuple[tuple[int, int], ...]:
    return {
        "spell_rage": RAGE_DROP_POINTS,
        "spell_heal": HEAL_DROP_POINTS,
        "spell_totem": TOTEM_DROP_POINTS,
    }.get(spell_name, RAGE_DROP_POINTS)


# ── Utility ──


def _interruptible_sleep(seconds: float, label: str) -> None:
    remaining = max(0.0, float(seconds))
    while remaining > 0:
        check_deadline(label)
        chunk = min(0.1, remaining)
        time.sleep(chunk)
        remaining -= chunk