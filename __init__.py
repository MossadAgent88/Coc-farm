"""Tests for cocbot.config — BotConfig defaults and load_config parsing."""

import json
from pathlib import Path

from cocbot.config import BotConfig, load_config


def test_defaults_when_file_missing(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    cfg = load_config(missing)
    assert cfg == BotConfig()


def test_defaults_when_file_corrupt(tmp_path):
    corrupt = tmp_path / "bad.json"
    corrupt.write_text("{this is not json")
    cfg = load_config(corrupt)
    assert cfg == BotConfig()


def test_parses_int_fields_from_strings(tmp_path):
    """The GUI writes numbers as strings — load_config must coerce them."""
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"min_loot": "2000000", "max_search": "30"}))
    cfg = load_config(p)
    assert cfg.min_loot == 2_000_000
    assert cfg.max_search == 30


def test_parses_float_fields_from_strings(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"fatigue_ramp": "90.5", "skip_long_chance": "0.25"}))
    cfg = load_config(p)
    assert cfg.fatigue_ramp == 90.5
    assert cfg.skip_long_chance == 0.25


def test_parses_bool_from_multiple_representations(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"donate": "1", "fatigue": "true", "random_events": False}))
    cfg = load_config(p)
    assert cfg.donate is True
    assert cfg.fatigue is True
    assert cfg.random_events is False


def test_unknown_fields_ignored(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"min_loot": "1234567", "unknown_key": "ignored"}))
    cfg = load_config(p)
    assert cfg.min_loot == 1_234_567
