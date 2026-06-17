"""Tests for Broom Witch event farming deployment."""

from cocbot import event_broom
from cocbot.config import BotConfig


def test_estimated_broom_witch_taps_is_bounded():
    """Broom Witch mode must stay far below generic dump-mode tap volume."""
    assert event_broom.estimated_broom_witch_taps(waves=3) == 45
    # Old dump mode swept ~18 slots across 33+ points (>600 taps). This plan is
    # intentionally bounded for both speed and anti-detection safety.
    assert event_broom.estimated_broom_witch_taps(waves=3) < 80


def test_broom_witch_pressure_points_cover_multiple_edges():
    points = event_broom.WIZARD_TOWER_PRESSURE_POINTS
    assert len(points) >= 12
    # Left side, right side, and bottom-right lanes must all be represented.
    assert any(x < 700 for x, _ in points)
    assert any(x > 1300 for x, _ in points)
    assert any(y > 650 for _, y in points)


def test_deploy_broom_witches_uses_safe_delay(monkeypatch):
    taps = []
    sleeps = []

    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_x", 250)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_waves", 2)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_tap_delay", 0.01)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_wave_pause", 0.35)
    monkeypatch.setattr(event_broom.random, "uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr(event_broom, "tap", lambda x, y, delay=0.1: taps.append((x, y, delay)))
    monkeypatch.setattr(event_broom.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(event_broom, "emit", lambda *_args, **_kwargs: None)

    event_broom.deploy_broom_witches()

    assert len(taps) == event_broom.estimated_broom_witch_taps(waves=2)
    assert all(delay >= event_broom.MIN_SAFE_TAP_DELAY for *_xy, delay in taps)
    assert sleeps == [0.35]


def test_broom_witch_config_defaults_are_compatible():
    cfg = BotConfig()
    assert cfg.broom_witch_slot_x == 250
    assert cfg.broom_witch_waves == 3
    assert cfg.broom_witch_tap_delay >= event_broom.MIN_SAFE_TAP_DELAY
    assert cfg.broom_witch_battle_seconds > 0
