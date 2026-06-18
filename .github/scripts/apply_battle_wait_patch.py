from pathlib import Path

ROOT = Path.cwd()


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


# 1) Config: add smart battle wait defaults if missing.
config = (ROOT / "cocbot/config.py").read_text(encoding="utf-8")
if "auto_end_enabled" not in config:
    config = config.replace(
        "    warden_tome_delay: float = 3.0\n",
        "    warden_tome_delay: float = 3.0\n"
        "    auto_end_enabled: bool = True\n"
        "    auto_end_min_battle_age: float = 20.0\n"
        "    auto_end_min_after_last_deploy: float = 12.0\n"
        "    auto_end_no_progress_seconds: float = 15.0\n"
        "    auto_end_low_remaining_loot: int = 50_000\n"
        "    auto_enable_4x_last_seconds: int = 60\n",
    )
write("cocbot/config.py", config)

# 2) Session: store battle state.
session = (ROOT / "cocbot/session.py").read_text(encoding="utf-8")
if "last_deploy_time" not in session:
    session = session.replace(
        "    # Timestamps of force_restart_coc calls in the last hour.\n"
        "    recent_restarts: list[float] = None  # type: ignore[assignment]\n",
        "    # Timestamps of force_restart_coc calls in the last hour.\n"
        "    recent_restarts: list[float] = None  # type: ignore[assignment]\n"
        "    # Battle progress state used by smart auto-end logic.\n"
        "    battle_start_time: float = 0.0\n"
        "    last_deploy_time: float = 0.0\n"
        "    last_progress_time: float = 0.0\n"
        "    deployment_finished: bool = False\n"
        "    speed_4x_checked: bool = False\n",
    )
write("cocbot/session.py", session)

# 3) Vision: detect Broom Witch slot and optional 1x/4x templates.
vision = (ROOT / "cocbot/vision.py").read_text(encoding="utf-8")
if '    "broom_witch",' not in vision:
    vision = vision.replace('TROOP_NAMES = [\n    "edrag",', 'TROOP_NAMES = [\n    "broom_witch",\n    "edrag",')
if "def detect_battle_speed" not in vision:
    vision += r'''

# Battle HUD helpers. These are intentionally conservative: if the optional
# templates are not present or confidence is low, return None instead of making a
# blind decision. The battle loop falls back to elapsed-time estimates where safe.
SPEED_BUTTON_CENTER = (1845, 590)
SPEED_BUTTON_REGION = (540, 640, 1785, 1915)  # y1, y2, x1, x2 at 1920x1080


def _match_optional_templates(
    screenshot: np.ndarray,
    template_names: tuple[str, ...],
    region: tuple[int, int, int, int],
    threshold: float = 0.72,
) -> float:
    """Return best template confidence for optional templates, or 0.0."""
    y1, y2, x1, x2 = region
    search_area = screenshot[y1:y2, x1:x2]
    if search_area.size == 0:
        return 0.0
    gray_area = cv2.cvtColor(search_area, cv2.COLOR_BGR2GRAY)
    best = 0.0
    for name in template_names:
        template = _get_template(name, grayscale=True)
        if template is None:
            continue
        h, w = template.shape[:2]
        if gray_area.shape[0] <= h or gray_area.shape[1] <= w:
            continue
        result = cv2.matchTemplate(gray_area, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        best = max(best, float(max_val))
    return best if best >= threshold else 0.0


def detect_battle_speed(screenshot: np.ndarray) -> str | None:
    """Detect the battle speed button state: "1x", "4x", or None.

    Optional template names:
    - templates/speed_1x.png or templates/battle_speed_1x.png
    - templates/speed_4x.png or templates/battle_speed_4x.png
    """
    one_x = _match_optional_templates(
        screenshot,
        ("speed_1x", "battle_speed_1x", "hud_speed_1x"),
        SPEED_BUTTON_REGION,
    )
    four_x = _match_optional_templates(
        screenshot,
        ("speed_4x", "battle_speed_4x", "hud_speed_4x"),
        SPEED_BUTTON_REGION,
    )
    if one_x <= 0.0 and four_x <= 0.0:
        return None
    return "4x" if four_x > one_x else "1x"


def read_battle_timer_seconds(_screenshot: np.ndarray) -> int | None:
    """Read remaining battle time in seconds when timer OCR/templates exist.

    Dedicated timer templates are not bundled yet. Returning None is intentional;
    the battle loop then uses the battle-age fallback.
    """
    return None


def read_damage_percent(_screenshot: np.ndarray) -> int | None:
    """Read battle damage percentage when damage OCR/templates exist.

    Dedicated damage templates are not bundled yet. Returning None keeps
    auto-end driven by remaining-loot progress instead of guessing.
    """
    return None
'''
write("cocbot/vision.py", vision)

# 4) Actions: replace battle wait loop and track deployment activity.
actions_path = ROOT / "cocbot/actions.py"
actions = actions_path.read_text(encoding="utf-8")
if "read_battle_timer_seconds" not in actions.split("from cocbot.vision import (", 1)[1].split(")", 1)[0]:
    actions = actions.replace(
        "    is_troop_available,\n    read_loot,",
        "    is_troop_available,\n    read_battle_timer_seconds,\n    read_damage_percent,\n    read_loot,\n    detect_battle_speed,",
    )
if "def _should_auto_end_battle" not in actions:
    start = actions.index("def wait_for_battle_end(")
    end = actions.index("\ndef _tap_troop(", start)
    new_wait = '''def _loot_total(loot: dict[str, int] | None) -> int | None:
    """Return total loot from a read_loot dict, or None for invalid OCR reads."""
    if not loot:
        return None
    total = int(loot.get("gold", 0)) + int(loot.get("elixir", 0)) + int(loot.get("dark_elixir", 0))
    return total if total > 0 else None


def _filtered_remaining_loot(loot: dict[str, int] | None) -> int | None:
    """Return the remaining-loot number used for early-end decisions."""
    if not loot:
        return None
    has_resource_filter = cfg.min_gold > 0 or cfg.min_elixir > 0 or cfg.min_de > 0
    if not has_resource_filter:
        return _loot_total(loot)
    remaining = 0
    if cfg.min_gold > 0:
        remaining += int(loot.get("gold", 0))
    if cfg.min_elixir > 0:
        remaining += int(loot.get("elixir", 0))
    if cfg.min_de > 0:
        remaining += int(loot.get("dark_elixir", 0))
    return remaining if remaining > 0 else None


def _should_auto_end_battle(
    *,
    now: float,
    battle_start_time: float,
    last_deploy_time: float,
    last_progress_time: float,
    deployment_finished: bool,
    remaining_loot: int | None,
) -> tuple[bool, str]:
    """Decide whether the current battle has stopped being useful."""
    if not bool(getattr(cfg, "auto_end_enabled", True)):
        return False, "disabled"
    if not deployment_finished:
        return False, "deployment_not_finished"
    battle_age = now - battle_start_time
    if battle_age < float(getattr(cfg, "auto_end_min_battle_age", 20.0)):
        return False, "battle_too_young"
    if now - last_deploy_time < float(getattr(cfg, "auto_end_min_after_last_deploy", 12.0)):
        return False, "recent_deploy"
    low_remaining = (
        remaining_loot is not None
        and remaining_loot <= int(getattr(cfg, "auto_end_low_remaining_loot", 50_000))
    )
    no_progress = now - last_progress_time >= float(getattr(cfg, "auto_end_no_progress_seconds", 15.0))
    if low_remaining:
        return True, "low_remaining_loot"
    if no_progress:
        return True, "no_progress"
    return False, "still_progressing"


def _maybe_enable_4x(screen, remaining_seconds: int | None) -> bool:
    """Enable 4x during the final battle minute when the HUD says 1x."""
    if remaining_seconds is None:
        return False
    threshold = int(getattr(cfg, "auto_enable_4x_last_seconds", 60))
    if threshold <= 0 or remaining_seconds > threshold:
        return False
    speed = detect_battle_speed(screen)
    if speed == "4x":
        logger.debug("Battle speed already 4x")
        return False
    if speed != "1x":
        logger.debug("Battle speed unreadable; not tapping speed button blindly")
        return False
    tap(1845 + random.randint(-8, 8), 590 + random.randint(-8, 8), delay=0.05)
    logger.info("Enabled 4x battle speed for final {}s", threshold)
    emit("battle_speed_4x_enabled", remaining_seconds=int(remaining_seconds))
    return True


def _note_progress(
    *,
    remaining_loot: int | None,
    previous_remaining_loot: int | None,
    damage_percent: int | None,
    previous_damage_percent: int | None,
) -> bool:
    """Return True when loot decreased or damage increased."""
    loot_progress = (
        remaining_loot is not None
        and previous_remaining_loot is not None
        and remaining_loot < previous_remaining_loot
    )
    damage_progress = (
        damage_percent is not None
        and previous_damage_percent is not None
        and damage_percent > previous_damage_percent
    )
    return loot_progress or damage_progress


def wait_for_battle_end(timeout: float = 180.0):
    """Wait for battle end with 4x support and smart auto-end."""
    logger.info("Waiting for battle to end...")
    battle_start_time = time.time()
    session.battle_start_time = battle_start_time
    session.deployment_finished = True
    if not session.last_deploy_time:
        session.last_deploy_time = battle_start_time
    session.last_progress_time = battle_start_time
    session.speed_4x_checked = False
    previous_remaining_loot: int | None = None
    previous_damage_percent: int | None = None
    while time.time() - battle_start_time < timeout:
        check_deadline("Battle end")
        now = time.time()
        elapsed = now - battle_start_time
        screen = capture_screenshot()
        pos = find_template(screen, "5_return_home", threshold=0.7)
        if pos:
            logger.info("Found Return Home button")
            jx, jy = _ui_jitter(pos[0], pos[1], pos[2], pos[3])
            tap(jx, jy)
            time.sleep(2)
            return True
        remaining_loot: int | None = None
        damage_percent: int | None = None
        if elapsed >= 5.0:
            loot = read_loot(screen, label="Remaining Loot")
            remaining_loot = _filtered_remaining_loot(loot)
            damage_percent = read_damage_percent(screen)
            if _note_progress(
                remaining_loot=remaining_loot,
                previous_remaining_loot=previous_remaining_loot,
                damage_percent=damage_percent,
                previous_damage_percent=previous_damage_percent,
            ):
                session.last_progress_time = now
            if remaining_loot is not None:
                previous_remaining_loot = remaining_loot
            if damage_percent is not None:
                previous_damage_percent = damage_percent
        remaining_seconds = read_battle_timer_seconds(screen)
        if remaining_seconds is None:
            remaining_seconds = max(0, int(timeout - elapsed))
        if not session.speed_4x_checked and remaining_seconds <= int(getattr(cfg, "auto_enable_4x_last_seconds", 60)):
            _maybe_enable_4x(screen, remaining_seconds)
            session.speed_4x_checked = True
        should_end, reason = _should_auto_end_battle(
            now=now,
            battle_start_time=battle_start_time,
            last_deploy_time=session.last_deploy_time or battle_start_time,
            last_progress_time=session.last_progress_time or battle_start_time,
            deployment_finished=session.deployment_finished,
            remaining_loot=remaining_loot,
        )
        if should_end:
            logger.info("Auto-ending battle: {}", reason)
            emit("auto_end_battle", reason=reason, remaining=remaining_loot or 0)
            end_battle_and_go_home()
            return True
        time.sleep(1)
    logger.warning("Battle timeout, tapping to continue...")
    tap(960, 540)
    time.sleep(3)
    return False


# Troop deployment helpers


def _mark_deploy_activity() -> None:
    """Record that a troop/hero/spell/ability deployment action just happened."""
    session.last_deploy_time = time.time()


def _begin_deployment() -> None:
    session.deployment_finished = False
    _mark_deploy_activity()


def _finish_deployment() -> None:
    _mark_deploy_activity()
    session.deployment_finished = True

'''
    actions = actions[:start] + new_wait + actions[end + 1 :]
    actions = actions.replace(
        "    tap(slots[name], TROOP_BAR_Y, delay=0.08)\n    return True\n",
        "    tap(slots[name], TROOP_BAR_Y, delay=0.08)\n    _mark_deploy_activity()\n    return True\n",
        1,
    )
    start = actions.index("def deploy_dump():")
    end = actions.index("\n\ndef deploy_troops(", start)
    new_dump = '''def deploy_dump():
    """Deploy the active army preset for event/dump mode."""
    preset = active_preset_name()
    logger.info(f"Dump mode using army preset: {preset}")
    _begin_deployment()
    try:
        if preset == "broom_witch":
            deploy_broom_witches()
        else:
            _deploy_generic_dump()
    finally:
        _finish_deployment()
'''
    actions = actions[:start] + new_dump + actions[end:]
    actions = actions.replace(
        "        tap(sx, TROOP_BAR_Y, delay=0.04)\n        points = list(_DUMP_PERIMETER)",
        "        tap(sx, TROOP_BAR_Y, delay=0.04)\n        _mark_deploy_activity()\n        points = list(_DUMP_PERIMETER)",
    )
    actions = actions.replace(
        "            tap(x + random.randint(-8, 8), y + random.randint(-8, 8), delay=0.07)\n        tap(sx, TROOP_BAR_Y, delay=0.04)",
        "            tap(x + random.randint(-8, 8), y + random.randint(-8, 8), delay=0.07)\n            _mark_deploy_activity()\n        tap(sx, TROOP_BAR_Y, delay=0.04)\n        _mark_deploy_activity()",
    )
    actions = actions.replace(
        "    army_config = get_army_config()\n    if army_config[\"name\"] == \"broom_witch\":\n        logger.info(\"Normal attack using Broom Witch preset\")\n        deploy_broom_witches()\n        return\n",
        "    _begin_deployment()\n    army_config = get_army_config()\n    if army_config[\"name\"] == \"broom_witch\":\n        logger.info(\"Normal attack using Broom Witch preset\")\n        try:\n            deploy_broom_witches()\n        finally:\n            _finish_deployment()\n        return\n",
    )
    actions = actions.replace(
        "    if not slots:\n        logger.error(\"No troops found in bar!\")\n        return\n",
        "    if not slots:\n        logger.error(\"No troops found in bar!\")\n        _finish_deployment()\n        return\n",
    )
    actions = actions.replace(
        "    logger.info(\"All troops deployed\")\n",
        "    _finish_deployment()\n    logger.info(\"All troops deployed\")\n",
    )
write("cocbot/actions.py", actions)

# 5) Tests.
write("test_battle_wait.py", r'''from cocbot import actions


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
''')

import py_compile
for file in [
    "cocbot/actions.py",
    "cocbot/config.py",
    "cocbot/vision.py",
    "cocbot/session.py",
    "test_battle_wait.py",
    "test_event_broom.py",
]:
    py_compile.compile(str(ROOT / file), doraise=True)
