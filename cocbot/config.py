"""Bot configuration — static-at-process-start.

The `cfg` singleton is frozen at import time. Settings changes in
`settings.json` apply on next bot Start (GUI restarts the subprocess).
There is no hot-reload.
"""

import json
from dataclasses import dataclass, fields
from pathlib import Path

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
    army_preset: str = "broom_witch"
    # Broom Witch event mode tuning. These defaults are intentionally bounded:
    # bounded troop-bar slots, controlled waves, and no rapid-fire tapping.
    # Use a comma-separated list because settings.json stores GUI values as text.
    broom_witch_slot_xs: str = "250,330,410,490"
    broom_witch_slot_x: int = 250  # legacy fallback if slot_xs is empty
    broom_witch_waves: int = 3
    broom_witch_tap_delay: float = 0.07
    broom_witch_wave_pause: float = 0.75
    broom_witch_battle_seconds: float = 45.0
    warden_slot_x: int = 1370
    rage_slot_x: int = 1290
    rage_spell_count: int = 3
    warden_tome_delay: float = 8.0


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
    return BotConfig(**kwargs)


cfg = load_config()
