from cocbot import actions


def test_should_auto_end_requires_finished_deployment(monkeypatch):
    monkeypatch.setattr(actions.cfg, "auto_end_enabled", True)
    should_end, reason = actions._should_auto_end_battle(
        now=100.0,
        battle_start_time=0.0,
        last_deploy_time=70.0,
        last_progress_time=70.0,
        deployment_finished=False,
        remaining_loot=10_000,
    )
    assert should_end is False
    assert reason == "deployment_not_finished"


def test_should_auto_end_low_remaining_after_minimums(monkeypatch):
    monkeypatch.setattr(actions.cfg, "auto_end_enabled", True)
    monkeypatch.setattr(actions.cfg, "auto_end_min_battle_age", 20.0)
    monkeypatch.setattr(actions.cfg, "auto_end_min_after_last_deploy", 12.0)
    monkeypatch.setattr(actions.cfg, "auto_end_low_remaining_loot", 50_000)
    should_end, reason = actions._should_auto_end_battle(
        now=40.0,
        battle_start_time=0.0,
        last_deploy_time=20.0,
        last_progress_time=35.0,
        deployment_finished=True,
        remaining_loot=49_999,
    )
    assert should_end is True
    assert reason == "low_remaining_loot"


def test_should_auto_end_no_progress_after_minimums(monkeypatch):
    monkeypatch.setattr(actions.cfg, "auto_end_enabled", True)
    monkeypatch.setattr(actions.cfg, "auto_end_min_battle_age", 20.0)
    monkeypatch.setattr(actions.cfg, "auto_end_min_after_last_deploy", 12.0)
    monkeypatch.setattr(actions.cfg, "auto_end_no_progress_seconds", 15.0)
    should_end, reason = actions._should_auto_end_battle(
        now=45.0,
        battle_start_time=0.0,
        last_deploy_time=20.0,
        last_progress_time=29.5,
        deployment_finished=True,
        remaining_loot=500_000,
    )
    assert should_end is True
    assert reason == "no_progress"


def test_should_not_auto_end_with_recent_deploy(monkeypatch):
    monkeypatch.setattr(actions.cfg, "auto_end_enabled", True)
    monkeypatch.setattr(actions.cfg, "auto_end_min_battle_age", 20.0)
    monkeypatch.setattr(actions.cfg, "auto_end_min_after_last_deploy", 12.0)
    should_end, reason = actions._should_auto_end_battle(
        now=30.0,
        battle_start_time=0.0,
        last_deploy_time=25.0,
        last_progress_time=0.0,
        deployment_finished=True,
        remaining_loot=10_000,
    )
    assert should_end is False
    assert reason == "recent_deploy"


def test_note_progress_detects_loot_drop_and_damage_gain():
    assert actions._note_progress(
        remaining_loot=900,
        previous_remaining_loot=1000,
        damage_percent=None,
        previous_damage_percent=None,
    )
    assert actions._note_progress(
        remaining_loot=1000,
        previous_remaining_loot=1000,
        damage_percent=55,
        previous_damage_percent=54,
    )
    assert not actions._note_progress(
        remaining_loot=1000,
        previous_remaining_loot=1000,
        damage_percent=54,
        previous_damage_percent=54,
    )


def test_maybe_enable_4x_taps_only_when_speed_is_1x(monkeypatch):
    taps = []
    events = []
    monkeypatch.setattr(actions.cfg, "auto_enable_4x_last_seconds", 60)
    monkeypatch.setattr(actions, "detect_battle_speed", lambda _screen: "1x")
    monkeypatch.setattr(actions, "tap", lambda x, y, delay=0: taps.append((x, y, delay)))
    monkeypatch.setattr(actions, "emit", lambda *args, **kwargs: events.append((args, kwargs)))
    assert actions._maybe_enable_4x(object(), 60) is True
    assert len(taps) == 1
    assert events[0][0][0] == "battle_speed_4x_enabled"


def test_maybe_enable_4x_does_not_tap_when_4x_or_unknown(monkeypatch):
    taps = []
    monkeypatch.setattr(actions.cfg, "auto_enable_4x_last_seconds", 60)
    monkeypatch.setattr(actions, "tap", lambda x, y, delay=0: taps.append((x, y, delay)))
    monkeypatch.setattr(actions, "detect_battle_speed", lambda _screen: "4x")
    assert actions._maybe_enable_4x(object(), 60) is False
    monkeypatch.setattr(actions, "detect_battle_speed", lambda _screen: None)
    assert actions._maybe_enable_4x(object(), 60) is False
    assert taps == []
