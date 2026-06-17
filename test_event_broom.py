from cocbot import event_broom
from cocbot.config import cfg


def test_estimated_taps_stays_bounded(monkeypatch):
    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "250")
    taps = event_broom.estimated_broom_witch_taps(waves=3)
    assert taps == 45
    assert taps < 80


def test_estimated_taps_counts_multiple_slots(monkeypatch):
    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "250,330,410")
    taps = event_broom.estimated_broom_witch_taps(waves=2)
    assert taps == 2 * 3 * (1 + len(event_broom.WIZARD_TOWER_PRESSURE_POINTS))


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


def test_deploy_uses_safe_delay_and_all_slots(monkeypatch):
    taps = []
    sleeps = []
    events = []

    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "250,330")
    monkeypatch.setattr(event_broom.cfg, "broom_witch_waves", 2)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_tap_delay", 0.001)
    monkeypatch.setattr(event_broom.cfg, "broom_witch_wave_pause", 0.35)
    monkeypatch.setattr(event_broom, "_jitter_point", lambda x, y: (x, y))
    monkeypatch.setattr(event_broom, "tap", lambda x, y, delay=0: taps.append((x, y, delay)))
    monkeypatch.setattr(event_broom.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(event_broom, "check_deadline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(event_broom, "emit", lambda *args, **kwargs: events.append((args, kwargs)))

    event_broom.deploy_broom_witches()

    slot_taps = [t for t in taps if t[0] in (250, 330)]
    assert len(slot_taps) == 4  # 2 slots * 2 waves
    assert all(delay >= event_broom.MIN_SAFE_TAP_DELAY for *_xy, delay in taps)
    assert len(sleeps) == 1
    assert events[0][0][0] == "broom_witch_deploy_start"
    assert events[-1][0][0] == "broom_witch_deploy_complete"


def test_config_defaults_are_compatible():
    assert hasattr(cfg, "broom_witch_slot_xs")
    assert cfg.broom_witch_slot_x == 250
    assert cfg.broom_witch_waves >= 1
    assert cfg.broom_witch_tap_delay >= 0
    assert cfg.broom_witch_battle_seconds >= 15
