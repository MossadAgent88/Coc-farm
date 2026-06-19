from cocbot import army, event_broom
from cocbot.config import cfg


def test_estimated_taps_stays_bounded(monkeypatch):
    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "250")
    monkeypatch.setattr(event_broom.cfg, "broom_witch_taps_per_round", 8)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_taps_per_point", 1)
    taps = event_broom.estimated_broom_witch_taps(waves=3)
    assert taps == 27  # 3 rounds * 1 slot * (1 + 8*1)
    assert taps < 60


def test_estimated_taps_counts_multiple_slots(monkeypatch):
    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "250,330,410")
    monkeypatch.setattr(event_broom.cfg, "broom_witch_taps_per_round", 8)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_taps_per_point", 1)
    taps = event_broom.estimated_broom_witch_taps(waves=2)
    assert taps == 2 * 3 * (1 + 8)


def test_estimated_taps_scales_with_taps_per_point(monkeypatch):
    """More taps per point => proportionally more total taps (faster spam)."""
    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "250")
    monkeypatch.setattr(event_broom.cfg, "broom_witch_taps_per_round", 4)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_taps_per_point", 3)
    taps = event_broom.estimated_broom_witch_taps(waves=2)
    assert taps == 2 * 1 * (1 + 4 * 3)  # 26


def test_configured_slot_xs_parses_and_deduplicates(monkeypatch):
    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "250,330,330,bad,99,1600;410")
    assert event_broom._configured_slot_xs() == [250, 330, 410]


def test_configured_slot_xs_uses_legacy_fallback(monkeypatch):
    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "")
    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_x", 250)
    assert event_broom._configured_slot_xs() == [250]


def test_pressure_points_cover_multiple_edges():
    pts = event_broom.WIZARD_TOWER_PRESSURE_POINTS
    assert len(pts) >= 10
    assert min(x for x, _ in pts) < 600
    assert max(x for x, _ in pts) > 1400
    assert min(y for _, y in pts) < 250
    assert max(y for _, y in pts) > 700


def test_broom_witch_slot_detection_prefers_live_slot(monkeypatch):
    monkeypatch.setattr(event_broom, "capture_screenshot", lambda: object())
    monkeypatch.setattr(event_broom, "find_troop_slots", lambda _screen: {"broom_witch": 444})
    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "250")
    assert event_broom._broom_witch_slot_xs() == [444]


def test_deploy_uses_fast_until_depleted_pattern(monkeypatch):
    taps = []
    sleeps = []
    events = []
    support_calls = []

    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "250")
    monkeypatch.setattr(event_broom.cfg, "broom_witch_max_rounds", 3)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_taps_per_round", 2)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_taps_per_point", 1)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_tap_delay", 0.001)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_round_delay", 0.25)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_hero_delay", 0.15)
    monkeypatch.setattr(event_broom, "_jitter_point", lambda x, y: (x, y))
    monkeypatch.setattr(event_broom, "_broom_witch_slot_xs", lambda: [250])
    monkeypatch.setattr(event_broom, "_slot_still_available", lambda _slot_x: True)
    monkeypatch.setattr(event_broom, "tap", lambda x, y, delay=0: taps.append((x, y, delay)))
    monkeypatch.setattr(event_broom.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(event_broom, "check_deadline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(event_broom, "emit", lambda *args, **kwargs: events.append((args, kwargs)))
    # Every phase of the new flow is exercised through these stubs.
    monkeypatch.setattr(event_broom, "deploy_heroes", lambda *_a, **_k: support_calls.append("heroes"))
    monkeypatch.setattr(event_broom, "deploy_all_spells", lambda *_a, **_k: support_calls.append("spells"))
    monkeypatch.setattr(event_broom, "activate_all_hero_abilities", lambda *_a, **_k: support_calls.append("abilities"))

    event_broom.deploy_broom_witches()

    slot_taps = [t for t in taps if t[0] == 250]
    assert len(slot_taps) == 3  # 1 slot * 3 max rounds
    assert all(delay >= event_broom.MIN_SAFE_TAP_DELAY for *_xy, delay in taps)
    assert max(sleeps) <= 0.1  # interruptible stop-friendly sleep chunks
    assert round(sum(sleeps), 2) == 0.65  # hero delay + two 0.25s round delays
    # New flow deploys heroes, then all spells, then all hero abilities.
    assert support_calls == ["heroes", "spells", "abilities"]
    assert events[0][0][0] == "broom_witch_deploy_start"
    assert events[-1][0][0] == "broom_witch_deploy_complete"
    assert events[-1][1]["rounds"] == 3


def test_deploy_spams_multiple_taps_per_point(monkeypatch):
    """taps_per_point > 1 should produce multiple deployment taps per point."""
    taps = []

    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "250")
    monkeypatch.setattr(event_broom.cfg, "broom_witch_max_rounds", 1)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_taps_per_round", 2)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_taps_per_point", 3)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_tap_delay", 0.001)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_round_delay", 0.0)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_hero_delay", 0.0)
    monkeypatch.setattr(event_broom, "_jitter_point", lambda x, y: (x, y))
    monkeypatch.setattr(event_broom, "_broom_witch_slot_xs", lambda: [250])
    monkeypatch.setattr(event_broom, "_slot_still_available", lambda _slot_x: True)
    monkeypatch.setattr(event_broom, "tap", lambda x, y, delay=0: taps.append((x, y, delay)))
    monkeypatch.setattr(event_broom.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(event_broom, "check_deadline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(event_broom, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(event_broom, "deploy_heroes", lambda *_a, **_k: None)
    monkeypatch.setattr(event_broom, "deploy_all_spells", lambda *_a, **_k: None)
    monkeypatch.setattr(event_broom, "activate_all_hero_abilities", lambda *_a, **_k: None)

    event_broom.deploy_broom_witches()

    # 1 slot-select + (2 points * 3 taps each) = 7 taps total.
    assert len(taps) == 1 + 2 * 3


def test_warden_tome_delay_defaults_to_three_seconds(monkeypatch):
    taps = []
    sleeps = []

    monkeypatch.setattr(army.cfg, "warden_tome_delay", 3.0)
    monkeypatch.setattr(army.cfg, "warden_slot_x", 1370)
    monkeypatch.setattr(army, "tap", lambda x, y, delay=0: taps.append((x, y, delay)))
    monkeypatch.setattr(army.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(army, "check_deadline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(army, "emit", lambda *_args, **_kwargs: None)

    army.activate_warden_abilities({"heroes": [{"name": "warden"}]}, timing="core")

    assert abs(sum(sleeps) - 3.0) < 0.001
    assert max(sleeps) <= 0.1
    assert taps[-1][0] == 1370


def test_activate_all_hero_abilities_triggers_every_hero(monkeypatch):
    """Every hero with an ability configured should be activated."""
    activated = []

    monkeypatch.setattr(army.cfg, "warden_tome_delay", 0.0)
    monkeypatch.setattr(army.cfg, "broom_witch_hero_delay", 0.0)
    monkeypatch.setattr(army, "tap", lambda x, y, delay=0: activated.append(x))
    monkeypatch.setattr(army.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(army, "check_deadline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(army, "emit", lambda *_args, **_kwargs: None)

    army_config = {
        "heroes": [
            {"name": "queen", "ability": "immediate"},
            {"name": "warden", "ability": "eternal_tome"},
            {"name": "minion_prince", "ability": "post_deploy"},
            {"name": "duke", "ability": "post_deploy"},
        ],
        "timing": {"hero_ability_delay": 0.0},
    }
    army.activate_all_hero_abilities(army_config)

    # Every hero produced at least one activation tap.
    assert len(activated) >= 4


def test_deploy_all_spells_drops_every_spell_type(monkeypatch):
    """deploy_all_spells should drop Rage, Heal, AND Totem."""
    from cocbot import army as army_mod

    dropped = []
    monkeypatch.setattr(army_mod.cfg, "rage_spell_count", 2)
    monkeypatch.setattr(army_mod.cfg, "heal_spell_count", 2)
    monkeypatch.setattr(army_mod.cfg, "totem_spell_count", 2)
    monkeypatch.setattr(army_mod, "tap", lambda x, y, delay=0: dropped.append((x, y)))
    monkeypatch.setattr(army_mod, "check_deadline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(army_mod, "emit", lambda *_args, **_kwargs: None)

    army_config = {
        "spells": [
            {"name": "spell_rage"},
            {"name": "spell_heal"},
            {"name": "spell_totem"},
        ],
    }
    army.deploy_all_spells(army_config)

    # Each spell: 1 slot-select tap + count drop taps. With count=2 that's
    # 3 taps per spell, 9 total. At minimum every spell type was selected.
    slot_xs = {army_mod._spell_slot_x("spell_rage"), army_mod._spell_slot_x("spell_heal"), army_mod._spell_slot_x("spell_totem")}
    dropped_xs = {x for x, _ in dropped}
    assert slot_xs.issubset(dropped_xs)


def test_config_defaults_are_fast_and_compatible():
    assert hasattr(cfg, "broom_witch_slot_xs")
    assert cfg.broom_witch_slot_x == 250
    # Faster spam defaults: more rounds and more taps per round than before.
    assert cfg.broom_witch_max_rounds >= 3
    assert cfg.broom_witch_taps_per_round >= 8
    assert cfg.broom_witch_taps_per_point >= 1
    assert cfg.broom_witch_tap_delay == 0.07
    assert cfg.broom_witch_round_delay == 0.25
    assert cfg.broom_witch_hero_delay == 0.15
    assert cfg.broom_witch_spell_delay == 0.12
    assert cfg.warden_tome_delay == 3.0
    assert cfg.broom_witch_battle_seconds >= 15
    # New hero/spell slot + count fields exist.
    for field in (
        "queen_slot_x",
        "warden_slot_x",
        "minion_prince_slot_x",
        "duke_slot_x",
        "heal_slot_x",
        "totem_slot_x",
        "heal_spell_count",
        "totem_spell_count",
    ):
        assert hasattr(cfg, field), f"Missing config field: {field}"