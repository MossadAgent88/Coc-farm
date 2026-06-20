"""Bot configuration — static-at-process-start.

The `cfg` singleton is frozen at import time. Settings changes in
`settings.json` apply on next bot Start (GUI restarts the subprocess).
There is no hot-reload.
"""

import json
from dataclasses import dataclass, fields
from pathlib import Path

from cocbot.army_catalog import DEFAULT_PRESET, normalize_preset

_SETTINGS_FILE = Path.cwd() / "settings.json"


@dataclass
class BotConfig:
    min_loot: int = 1_500_000
    min_remaining: int = 100_000
    min_gold: int = 0
    min_elixir: int = 0
    min_de: int = 0
    max_search: int = 20
    reconnect_wait: int = 300
    attack_side: str = "Random"
    donate: bool = True
    random_events: bool = True
    fatigue: bool = True
    fatigue_ramp: float = 120.0
    fatigue_max: float = 2.0
    break_every_min: int = 60
    break_every_max: int = 120
    break_dur_min: int = 4
    break_dur_max: int = 16
    skip_min: float = 0.0
    skip_max: float = 6.0
    skip_long_min: float = 5.0
    skip_long_max: float = 15.0
    skip_long_chance: float = 0.15
    event_every_min: int = 3
    event_every_max: int = 10
    post_attack_min: float = 3.0
    post_attack_max: float = 20.0
    log_file: bool = False
    max_cycles: int = 0
    debug_screenshots: bool = False
    dump_mode: bool = False
    army_preset: str = DEFAULT_PRESET
    # Broom Witch event mode tuning. These defaults are intentionally bounded:
    # one troop-bar slot, fast rounds, and no rapid-fire tapping.
    # Use a comma-separated list because settings.json stores GUI values as text.
    broom_witch_slot_xs: str = "250"
    broom_witch_slot_x: int = 250  # legacy fallback if slot_xs is empty
    broom_witch_waves: int = 3  # legacy alias; use broom_witch_max_rounds for new code
    broom_witch_max_rounds: int = 6
    broom_witch_taps_per_round: int = 13
    broom_witch_taps_per_point: int = 2
    broom_witch_tap_delay: float = 0.07
    broom_witch_round_delay: float = 0.25
    broom_witch_wave_pause: float = 0.25  # legacy alias
    broom_witch_hero_delay: float = 0.15
    broom_witch_spell_delay: float = 0.12
    broom_witch_battle_seconds: float = 45.0
    # Hero troop-bar slot X positions (1920x1080). Used so every hero is
    # selected from the correct slot and deployed on its own lane.
    queen_slot_x: int = 1300
    warden_slot_x: int = 1370
    king_slot_x: int = 1430
    minion_prince_slot_x: int = 1490
    duke_slot_x: int = 1550
    # Spell troop-bar slot X positions and counts. Each spell type uses its
    # own drop-point lane in army.deploy_all_spells().
    rage_slot_x: int = 1290
    heal_slot_x: int = 1230
    totem_slot_x: int = 1350
    rage_spell_count: int = 4
    heal_spell_count: int = 2
    totem_spell_count: int = 2
    warden_tome_delay: float = 3.0
    auto_end_enabled: bool = True
    auto_end_min_battle_age: float = 20.0
    auto_end_min_after_last_deploy: float = 12.0
    auto_end_no_progress_seconds: float = 15.0
    auto_end_low_remaining_loot: int = 50_000
    auto_enable_4x_last_seconds: int = 60


def load_config(path: Path = _SETTINGS_FILE) -> BotConfig:
    if not path.exists():
        return BotConfig()
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return BotConfig()
    kwargs = {}
    for f in fields(BotConfig):
        if f.name in raw:
            val = raw[f.name]
            if f.type is bool:
                kwargs[f.name] = (
                    val
                    if isinstance(val, bool)
                    else str(val) == "1" or str(val).lower() == "true"
                )
            elif f.type is int:
                kwargs[f.name] = int(float(val))
            elif f.type is float:
                kwargs[f.name] = float(val)
            else:
                kwargs[f.name] = str(val)
    # Migrate/validate the army preset so an old or invalid value in
    # settings.json (e.g. a removed preset) falls back cleanly instead of
    # silently breaking deployment.
    requested = kwargs.get("army_preset", DEFAULT_PRESET)
    preset, changed = normalize_preset(requested)
    if changed:
        from loguru import logger

        logger.warning(
            f"Unsupported army_preset {requested!r}; using {preset!r} instead"
        )
    kwargs["army_preset"] = preset
    return BotConfig(**kwargs)


cfg = load_config()
