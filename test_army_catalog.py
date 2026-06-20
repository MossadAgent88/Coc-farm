"""Sanity tests for the GUI army catalog and preset normalisation."""

from __future__ import annotations

import subprocess

# cocbot.io references Windows-only subprocess flags at import time; provide
# harmless fallbacks so these tests can also run on non-Windows CI/dev boxes.
for _attr in ("CREATE_NO_WINDOW", "CREATE_NEW_PROCESS_GROUP"):
    if not hasattr(subprocess, _attr):
        setattr(subprocess, _attr, 0)

from cocbot import army_catalog
from cocbot.army import ARMY_PRESETS


def test_catalog_keys_match_backend_presets():
    # The GUI must never offer a preset the backend cannot deploy.
    assert set(army_catalog.CATALOG_META) == set(ARMY_PRESETS)


def test_supported_presets_are_exactly_broom_and_edrag():
    assert army_catalog.supported_preset_keys() == ["broom_witch", "electro_dragon"]


def test_normalize_valid_presets_unchanged():
    for key in ARMY_PRESETS:
        assert army_catalog.normalize_preset(key) == (key, False)


def test_normalize_aliases_and_invalid_fall_back():
    assert army_catalog.normalize_preset("broom_witches") == ("broom_witch", True)
    assert army_catalog.normalize_preset("E-Drag Spam") == ("electro_dragon", True)
    assert army_catalog.normalize_preset("edrag") == ("electro_dragon", True)
    # Removed/unsupported presets all fall back to the default.
    for bad in ("super_archer", "barch", "dragon_loon", "hog_rider", "", None):
        key, changed = army_catalog.normalize_preset(bad)
        assert key == army_catalog.DEFAULT_PRESET
        assert changed is True


def test_build_gui_catalog_uses_real_deployment_lists():
    catalog = army_catalog.build_gui_catalog()
    keys = [c["key"] for c in catalog]
    assert keys == army_catalog.supported_preset_keys()
    for entry in catalog:
        assert entry["display_name"]
        assert entry["supported_town_halls"]
        # troops/heroes come straight from ARMY_PRESETS, so they must be present
        assert entry["troops"]
        assert entry["heroes"]


def test_config_migrates_invalid_preset(tmp_path):
    import json

    from cocbot.config import load_config

    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"army_preset": "hog_rider"}))
    assert load_config(settings).army_preset == "broom_witch"

    settings.write_text(json.dumps({"army_preset": "electro_dragon"}))
    assert load_config(settings).army_preset == "electro_dragon"
