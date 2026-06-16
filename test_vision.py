"""Tests for cocbot.actions — loot filter, fatigue, template miss counter."""

import time

import pytest

from cocbot.actions import (
    _default_loot_accepts,
    _MAX_CONSECUTIVE_MISSES,
    _register_template_hit,
    _register_template_miss,
    _template_miss_counts,
    _ui_jitter,
    get_fatigue_multiplier,
    human_delay,
)
from cocbot.config import BotConfig, cfg
from cocbot.session import BotStopRequested, session


# ── _default_loot_accepts ──


def test_accepts_accepts_high_total():
    loot = {"gold": 1_000_000, "elixir": 500_000, "dark_elixir": 0}
    assert _default_loot_accepts(loot) is True


def test_accepts_rejects_low_total():
    loot = {"gold": 100_000, "elixir": 100_000, "dark_elixir": 0}
    assert _default_loot_accepts(loot) is False


def test_accepts_uses_resource_filter_when_set(monkeypatch):
    """With min_gold set, only the gold threshold matters (others ignored)."""
    monkeypatch.setattr(cfg, "min_gold", 500_000)
    monkeypatch.setattr(cfg, "min_elixir", 0)
    monkeypatch.setattr(cfg, "min_de", 0)

    assert _default_loot_accepts(
        {"gold": 600_000, "elixir": 0, "dark_elixir": 0}
    ) is True
    assert _default_loot_accepts(
        {"gold": 400_000, "elixir": 1_000_000, "dark_elixir": 0}
    ) is False


def test_accepts_resource_filter_requires_all(monkeypatch):
    """Multiple filters are AND."""
    monkeypatch.setattr(cfg, "min_gold", 500_000)
    monkeypatch.setattr(cfg, "min_elixir", 500_000)
    monkeypatch.setattr(cfg, "min_de", 0)

    # Gold ok, elixir below threshold → reject
    assert _default_loot_accepts(
        {"gold": 600_000, "elixir": 400_000, "dark_elixir": 0}
    ) is False
    # Both ok → accept
    assert _default_loot_accepts(
        {"gold": 600_000, "elixir": 600_000, "dark_elixir": 0}
    ) is True


# ── Fatigue ──


def test_fatigue_disabled_returns_one(monkeypatch):
    monkeypatch.setattr(cfg, "fatigue", False)
    assert get_fatigue_multiplier() == 1.0


def test_fatigue_starts_at_one(monkeypatch):
    monkeypatch.setattr(cfg, "fatigue", True)
    monkeypatch.setattr(cfg, "fatigue_ramp", 120.0)
    monkeypatch.setattr(cfg, "fatigue_max", 2.0)
    monkeypatch.setattr(session, "started_at", time.time())
    m = get_fatigue_multiplier()
    assert 1.0 <= m < 1.1  # just started, elapsed ≈ 0


def test_fatigue_caps_at_max(monkeypatch):
    monkeypatch.setattr(cfg, "fatigue", True)
    monkeypatch.setattr(cfg, "fatigue_ramp", 120.0)
    monkeypatch.setattr(cfg, "fatigue_max", 2.0)
    # Set start time to long ago — should cap at fatigue_max.
    monkeypatch.setattr(session, "started_at", time.time() - 10_000)
    assert get_fatigue_multiplier() == 2.0


# ── human_delay ──


@pytest.mark.parametrize("_", range(20))
def test_human_delay_respects_minimum(_):
    """human_delay must never go below minimum, even when gauss tail is negative."""
    d = human_delay(center=0.0, spread=5.0, minimum=1.0)
    assert d >= 1.0


# ── _ui_jitter ──


def test_ui_jitter_stays_within_button_box():
    """Jitter must keep click inside the button area (scaled to ~30% of size)."""
    for _ in range(100):
        jx, jy = _ui_jitter(100, 100, w=60, h=30)
        assert 100 - 18 <= jx <= 100 + 18  # 30% of 60 = 18
        assert 100 - 9 <= jy <= 100 + 9  # 30% of 30 = 9


# ── Template miss counter ──


@pytest.fixture(autouse=True)
def reset_miss_counter():
    _template_miss_counts.clear()
    yield
    _template_miss_counts.clear()


def test_miss_counter_increments():
    _register_template_miss("tpl_a")
    _register_template_miss("tpl_a")
    assert _template_miss_counts["tpl_a"] == 2


def test_miss_counter_per_template():
    """Different templates have independent counters."""
    _register_template_miss("tpl_a")
    _register_template_miss("tpl_b")
    _register_template_miss("tpl_b")
    assert _template_miss_counts["tpl_a"] == 1
    assert _template_miss_counts["tpl_b"] == 2


def test_any_hit_resets_all_counters():
    """ANY successful template hit clears the full miss map.

    Rationale: fallback chains like `surrender_button or end_battle`
    mean one template always misses by design. The other hitting proves
    the vision system is working, so reset everything.
    """
    _register_template_miss("tpl_a")
    _register_template_miss("tpl_a")
    _register_template_miss("tpl_b")
    # Hitting a DIFFERENT template clears BOTH counters
    _register_template_hit("tpl_c")
    assert _template_miss_counts == {}


def test_threshold_raises_bot_stop_requested(capsys):
    for _ in range(_MAX_CONSECUTIVE_MISSES - 1):
        _register_template_miss("tpl_a")
    with pytest.raises(BotStopRequested) as exc:
        _register_template_miss("tpl_a")
    assert "tpl_a" in str(exc.value)
    # Event emitted on stdout:
    out = capsys.readouterr().out
    assert "template_failing" in out
    assert "tpl_a" in out
