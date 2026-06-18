from cocbot import army, event_broom
from cocbot.config import cfg


def test_estimated_taps_stays_bounded(monkeypatch):
    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "250")
    monkeypatch.setattr(event_broom.cfg, "broom_witch_taps_per_round", 8)
    taps = event_broom.estimated_broom_witch_taps(waves=3)
    assert taps == 27
    assert taps < 40


def test_estimated_taps_counts_multiple_slots(monkeypatch):
    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "250,330,410")
    monkeypatch.setattr(event_broom.cfg, "broom_witch_taps_per_round", 8)
    taps = event_broom.estimated_broom_witch_taps(waves=2)
    assert taps == 2 * 3 * (1 + 8)


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
    monkeypatch.setattr(event_broom, "deploy_heroes", lambda *_args, **_kwargs: support_calls.append("warden"))
    monkeypatch.setattr(event_broom, "deploy_rage_spells", lambda *_args, **_kwargs: support_calls.append("rage"))
    monkeypatch.setattr(event_broom, "activate_warden_abilities", lambda *_args, **_kwargs: support_calls.append("tome"))

    event_broom.deploy_broom_witches()

    slot_taps = [t for t in taps if t[0] == 250]
    assert len(slot_taps) == 3  # 1 slot * 3 max rounds
    assert all(delay >= event_broom.MIN_SAFE_TAP_DELAY for *_xy, delay in taps)
    assert max(sleeps) <= 0.1  # interruptible stop-friendly sleep chunks
    assert round(sum(sleeps), 2) == 0.65  # hero delay + two 0.25s round delays
    assert support_calls == ["warden", "rage", "tome"]
    assert events[0][0][0] == "broom_witch_deploy_start"
    assert events[-1][0][0] == "broom_witch_deploy_complete"
    assert events[-1][1]["rounds"] == 3


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


def test_config_defaults_are_fast_and_compatible():
    assert hasattr(cfg, "broom_witch_slot_xs")
    assert cfg.broom_witch_slot_x == 250
    assert cfg.broom_witch_max_rounds == 3
    assert cfg.broom_witch_taps_per_round == 8
    assert cfg.broom_witch_tap_delay == 0.07
    assert cfg.broom_witch_round_delay == 0.25
    assert cfg.broom_witch_hero_delay == 0.15
    assert cfg.broom_witch_spell_delay == 0.12
    assert cfg.warden_tome_delay == 3.0
    assert cfg.broom_witch_battle_seconds >= 15
