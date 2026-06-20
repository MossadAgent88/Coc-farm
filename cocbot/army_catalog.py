"""GUI-facing army preset catalog and preset-name normalisation.

This module is intentionally dependency-free at import time (it only uses the
standard library) so that ``cocbot.config`` can import it without creating an
import cycle with ``cocbot.army`` (which imports ``cocbot.config``).

The *deployment* logic and the canonical set of supported presets live in
``cocbot.army.ARMY_PRESETS``. This module adds only the human-facing metadata
needed to render the GUI "Army Equipment" panel and to migrate old/invalid
preset names. ``build_gui_catalog()`` reads troops/spells/heroes straight from
``ARMY_PRESETS`` (imported lazily) so the GUI can never show a preset that the
backend cannot actually deploy.
"""

from __future__ import annotations

from typing import Any

# The default preset used whenever a stored preset is missing or invalid.
DEFAULT_PRESET = "broom_witch"

# Old / display / typo names mapped onto a real backend preset key. Keys are
# compared case-insensitively and after stripping surrounding whitespace.
PRESET_ALIASES: dict[str, str] = {
    "broom_witches": "broom_witch",
    "broomwitch": "broom_witch",
    "broom witch": "broom_witch",
    "e-drag spam": "electro_dragon",
    "edrag spam": "electro_dragon",
    "edrag": "electro_dragon",
    "e-drag": "electro_dragon",
    "e_drag": "electro_dragon",
    "electro dragon": "electro_dragon",
    "electro_dragons": "electro_dragon",
}

# Display-only metadata, keyed by the *backend* preset key. The set of keys
# here must exactly match cocbot.army.ARMY_PRESETS (enforced by a test). Troops,
# spells and heroes are NOT duplicated here — they are read from ARMY_PRESETS so
# there is a single source of truth for what is actually deployed.
CATALOG_META: dict[str, dict[str, Any]] = {
    "broom_witch": {
        "display_name": "Broom Witch (Event)",
        "purpose": "Event farming / loot",
        "supported_town_halls": [13, 14, 15, 16, 17],
        "siege": "None (event army)",
        "notes": (
            "Event mode. The bot fills all camps with the event Broom Witch, "
            "drops every configured spell, and deploys all heroes with their "
            "abilities. Composition is the same across supported Town Halls."
        ),
    },
    "electro_dragon": {
        "display_name": "Electro Dragon Spam",
        "purpose": "Farming / trophies",
        "supported_town_halls": [13, 14, 15, 16, 17],
        "siege": "Siege Barracks (generic slot)",
        "notes": (
            "Air spam. Baby Dragon funnel, then Electro Dragons and Dragon "
            "Riders down the core, heroes and spells behind. Composition is "
            "the same across supported Town Halls."
        ),
    },
}


def supported_preset_keys() -> list[str]:
    """Return the backend preset keys the GUI is allowed to show, sorted."""
    return sorted(CATALOG_META.keys())


def normalize_preset(name: str | None) -> tuple[str, bool]:
    """Resolve *name* to a valid backend preset key.

    Returns ``(key, changed)`` where ``changed`` is True when the input was an
    alias, blank, or otherwise invalid and had to be migrated to a valid key.
    """
    raw = str(name or "").strip()
    key = raw.lower()
    if key in CATALOG_META:
        return key, key != raw  # changed only if casing/whitespace differed
    if key in PRESET_ALIASES:
        return PRESET_ALIASES[key], True
    return DEFAULT_PRESET, True


def _humanize(name: str) -> str:
    cleaned = str(name or "").strip()
    if cleaned.startswith("spell_"):
        cleaned = cleaned[len("spell_") :] + " spell"
    cleaned = cleaned.replace("_", " ").strip()
    return cleaned.title() if cleaned else cleaned


def _format_quantity(qty: Any) -> str:
    mapping = {
        "fill_camps": "fill camps",
        "fill_spells": "fill",
        "until_empty": "all",
    }
    if isinstance(qty, str):
        return mapping.get(qty, qty.replace("_", " "))
    try:
        return f"×{int(qty)}"
    except (TypeError, ValueError):
        return str(qty)


def _format_unit(entry: dict[str, Any]) -> str:
    name = _humanize(entry.get("name", ""))
    qty = entry.get("quantity")
    if qty is None:
        return name
    return f"{name} ({_format_quantity(qty)})"


def _format_hero(entry: dict[str, Any]) -> str:
    name = _humanize(entry.get("name", ""))
    ability = entry.get("ability")
    if ability:
        return f"{name} — {_humanize(str(ability))}"
    return name


def build_gui_catalog() -> list[dict[str, Any]]:
    """Build the GUI catalog: display metadata + the real deployment lists.

    Troops, spells and heroes come straight from ``cocbot.army.ARMY_PRESETS``
    so the panel is always truthful about what the bot deploys. Only presets
    present in BOTH ``ARMY_PRESETS`` and ``CATALOG_META`` are returned.
    """
    from cocbot.army import ARMY_PRESETS  # lazy import to avoid a cycle

    catalog: list[dict[str, Any]] = []
    for key in supported_preset_keys():
        preset = ARMY_PRESETS.get(key)
        if not preset:
            continue
        meta = CATALOG_META[key]
        catalog.append(
            {
                "key": key,
                "display_name": meta["display_name"],
                "purpose": meta["purpose"],
                "supported_town_halls": list(meta["supported_town_halls"]),
                "troops": [_format_unit(t) for t in preset.get("troops", [])],
                "spells": [_format_unit(s) for s in preset.get("spells", [])],
                "heroes": [_format_hero(h) for h in preset.get("heroes", [])],
                "siege": meta["siege"],
                "notes": meta["notes"],
            }
        )
    return catalog
