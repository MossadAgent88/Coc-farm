from pathlib import Path
import re

root = Path('.')

(root / 'cocbot' / 'army.py').write_text(r'''"""Config-driven army presets and event deployment helpers."""

from __future__ import annotations

import random
import time
from copy import deepcopy
from typing import Any

from loguru import logger

from cocbot.config import cfg
from cocbot.io import tap
from cocbot.plans import TROOP_BAR_Y
from cocbot.session import check_deadline, emit

CORE_RAGE_POINTS: tuple[tuple[int, int], ...] = ((930, 430), (1030, 470), (960, 545), (1080, 590))
WARDEN_ENTRY_POINTS: tuple[tuple[int, int], ...] = ((900, 230), (1020, 230), (1160, 300))

ARMY_PRESETS: dict[str, dict[str, Any]] = {
    "broom_witch": {
        "name": "broom_witch",
        "troops": [{"name": "broom_witch", "quantity": "fill_camps", "slot_source": "broom_witch_slot_xs"}],
        "spells": [{"name": "spell_rage", "quantity": "fill_spells", "slot_source": "rage_slot_x"}],
        "heroes": [{"name": "warden", "slot_source": "warden_slot_x", "ability": "eternal_tome"}],
        "deployment_order": ["broom_witch", "warden", "rage", "eternal_tome"],
        "timing": {"rage_after_wave": 1, "warden_after_wave": 0, "tome_after_seconds": 8.0},
    },
    "electro_dragon": {
        "name": "electro_dragon",
        "troops": [
            {"name": "queen", "quantity": 1},
            {"name": "barracks", "quantity": 1},
            {"name": "baby_dragon", "quantity": 3},
            {"name": "edrag", "quantity": "until_empty"},
            {"name": "dragon_rider", "quantity": "until_empty"},
            {"name": "warden", "quantity": 1},
            {"name": "minion_prince", "quantity": 1},
            {"name": "duke", "quantity": 1},
        ],
        "spells": [{"name": "spell_rage", "quantity": 4}, {"name": "spell_totem", "quantity": 4}],
        "heroes": [
            {"name": "queen", "ability": "immediate"},
            {"name": "warden", "ability": "core"},
            {"name": "minion_prince", "ability": "post_deploy"},
        ],
        "deployment_order": ["queen", "barracks", "baby_dragon", "edrag", "dragon_rider", "warden", "minion_prince", "duke", "spell_rage", "spell_totem"],
    },
}


def active_preset_name() -> str:
    name = str(getattr(cfg, "army_preset", "broom_witch") or "broom_witch").strip().lower()
    if name not in ARMY_PRESETS:
        logger.warning(f"Unknown ARMY_PRESET={name!r}; falling back to broom_witch")
        return "broom_witch"
    return name


def get_army_config(name: str | None = None) -> dict[str, Any]:
    preset = (name or active_preset_name()).strip().lower()
    return deepcopy(ARMY_PRESETS.get(preset, ARMY_PRESETS["broom_witch"]))


def _parse_slot_list(raw: str, fallback: int) -> list[int]:
    slots: list[int] = []
    for chunk in str(raw or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            x = int(float(chunk))
        except ValueError:
            logger.warning(f"Ignoring invalid troop slot x={chunk!r}")
            continue
        if 120 <= x <= 1510 and x not in slots:
            slots.append(x)
    return slots or [fallback]


def configured_broom_witch_slots() -> list[int]:
    return _parse_slot_list(getattr(cfg, "broom_witch_slot_xs", ""), int(getattr(cfg, "broom_witch_slot_x", 250)))[:8]


def deploy_heroes(army_config: dict[str, Any], deploy_points: list[tuple[int, int]] | tuple[tuple[int, int], ...] = WARDEN_ENTRY_POINTS) -> None:
    hero_names = {hero.get("name") for hero in army_config.get("heroes", [])}
    if "warden" not in hero_names:
        return
    warden_slot = int(getattr(cfg, "warden_slot_x", 1370))
    logger.info("Deploying Grand Warden for event push")
    emit("hero_deploy", hero="warden", slot_x=warden_slot)
    tap(warden_slot, TROOP_BAR_Y, delay=0.08)
    for x, y in list(deploy_points)[:3]:
        check_deadline("Deploy Warden")
        tap(x + random.randint(-15, 15), y + random.randint(-15, 15), delay=0.07)


def deploy_rage_spells(army_config: dict[str, Any], rage_points: list[tuple[int, int]] | tuple[tuple[int, int], ...] = CORE_RAGE_POINTS) -> None:
    spells = {spell.get("name") for spell in army_config.get("spells", [])}
    if "spell_rage" not in spells:
        return
    rage_slot = int(getattr(cfg, "rage_slot_x", 1290))
    count = max(1, int(getattr(cfg, "rage_spell_count", 3)))
    logger.info(f"Dropping {count} Rage spells for Broom Witch core push")
    emit("spell_deploy", spell="rage", slot_x=rage_slot, count=count)
    tap(rage_slot, TROOP_BAR_Y, delay=0.08)
    points = list(rage_points)
    for i in range(count):
        check_deadline("Deploy Rage")
        x, y = points[i % len(points)]
        tap(x + random.randint(-45, 45), y + random.randint(-45, 45), delay=0.08)


def activate_warden_abilities(army_config: dict[str, Any], timing: str = "core") -> None:
    hero_names = {hero.get("name") for hero in army_config.get("heroes", [])}
    if "warden" not in hero_names:
        return
    delay = max(0.0, float(getattr(cfg, "warden_tome_delay", 8.0)))
    if delay:
        logger.info(f"Waiting {delay:.1f}s before Eternal Tome ({timing})")
        time.sleep(delay)
    warden_slot = int(getattr(cfg, "warden_slot_x", 1370))
    logger.info("Activating Grand Warden Eternal Tome")
    emit("hero_ability", hero="warden", ability="eternal_tome", timing=timing)
    tap(warden_slot, TROOP_BAR_Y, delay=0.08)
''', encoding='utf-8')

# config.py
p = root / 'cocbot' / 'config.py'
s = p.read_text(encoding='utf-8')
if 'army_preset:' not in s:
    s = s.replace('    dump_mode: bool = False\n', '    dump_mode: bool = False\n    army_preset: str = "broom_witch"\n')
if 'warden_slot_x:' not in s:
    s = s.replace('    broom_witch_battle_seconds: float = 45.0\n', '    broom_witch_battle_seconds: float = 45.0\n    warden_slot_x: int = 1370\n    rage_slot_x: int = 1290\n    rage_spell_count: int = 3\n    warden_tome_delay: float = 8.0\n')
p.write_text(s, encoding='utf-8')

# event_broom.py
p = root / 'cocbot' / 'event_broom.py'
s = p.read_text(encoding='utf-8')
if 'configured_broom_witch_slots' not in s:
    s = s.replace('from cocbot.config import cfg\n', 'from cocbot.config import cfg\nfrom cocbot.army import (\n    activate_warden_abilities,\n    configured_broom_witch_slots,\n    deploy_heroes,\n    deploy_rage_spells,\n    get_army_config,\n)\n')
    s = re.sub(r'def _configured_slot_xs\(\) -> list\[int\]:.*?\n\ndef broom_witch_wave_points', 'def _configured_slot_xs() -> list[int]:\n    """Backward-compatible wrapper for tests and older callers."""\n    return configured_broom_witch_slots()\n\n\ndef broom_witch_wave_points', s, flags=re.S)
    s = s.replace('    slot_xs = _configured_slot_xs()\n', '    army_config = get_army_config("broom_witch")\n    slot_xs = _configured_slot_xs()\n')
    s = s.replace('        if wave != waves - 1:\n            time.sleep(wave_pause + random.uniform(0.0, 0.25))\n\n    logger.info("Broom Witch deploy complete")\n    emit("broom_witch_deploy_complete", waves=waves, slot_xs=slot_xs)\n', '        if wave == 0:\n            deploy_heroes(army_config)\n        if wave == 1 or (waves == 1 and wave == 0):\n            deploy_rage_spells(army_config)\n        if wave != waves - 1:\n            time.sleep(wave_pause + random.uniform(0.0, 0.25))\n\n    activate_warden_abilities(army_config, timing="core")\n    logger.info("Broom Witch deploy complete")\n    emit("broom_witch_deploy_complete", waves=waves, slot_xs=slot_xs, preset=army_config["name"])\n')
p.write_text(s, encoding='utf-8')

# actions.py
p = root / 'cocbot' / 'actions.py'
s = p.read_text(encoding='utf-8')
if 'active_preset_name' not in s:
    s = s.replace('from cocbot.debug import dbg\n', 'from cocbot.debug import dbg\nfrom cocbot.army import active_preset_name, get_army_config\n')
old = '''def deploy_dump():
    """Deploy the active event army using the optimized Broom Witch plan.

    The old dump mode swept every troop-bar slot across the whole perimeter,
    producing hundreds of ADB taps before the battle could produce useful
    event points. Broom Witch farming is now bounded to the configured troop
    slot and deploys timed waves into Wizard Tower pressure lanes. This keeps
    tap volume low, preserves human-safe delays, and improves crystals/minute.
    """
    deploy_broom_witches()
'''
new = '''def _deploy_generic_dump():
    """Fallback dump: empty visible slots across the perimeter using safe taps."""
    logger.info("Generic dump deploy: emptying configured/visible army onto base")
    for sx in _DUMP_SLOT_XS:
        check_deadline("Dump deploy")
        tap(sx, TROOP_BAR_Y, delay=0.04)
        points = list(_DUMP_PERIMETER)
        random.shuffle(points)
        for x, y in points:
            tap(x + random.randint(-8, 8), y + random.randint(-8, 8), delay=0.07)
        tap(sx, TROOP_BAR_Y, delay=0.04)


def deploy_dump():
    """Deploy the active army preset for event/dump mode."""
    preset = active_preset_name()
    logger.info(f"Dump mode using army preset: {preset}")
    if preset == "broom_witch":
        deploy_broom_witches()
    else:
        _deploy_generic_dump()
'''
if old in s:
    s = s.replace(old, new)
if 'army_config = get_army_config()' not in s:
    s = s.replace('    screen = capture_screenshot()\n    slots = find_troop_slots(screen)\n', '    army_config = get_army_config()\n    if army_config["name"] == "broom_witch":\n        logger.info("Normal attack using Broom Witch preset")\n        deploy_broom_witches()\n        return\n\n    screen = capture_screenshot()\n    slots = find_troop_slots(screen)\n')
    s = s.replace('    logger.info(f"Troop positions: {slots} | Attacking from {plan.name}")\n', '    logger.info(f"Troop positions: {slots} | Attacking from {plan.name} | preset={army_config[\'name\']}")\n')
p.write_text(s, encoding='utf-8')

# startup line
p = root / 'cocbot' / 'loop.py'
s = p.read_text(encoding='utf-8').replace('logger.info(f"CoC bot v{__version__}")', 'logger.info(f"[INFO] CoC Bot v{__version__} starting...")')
p.write_text(s, encoding='utf-8')
p = root / 'cocbot' / '__main__.py'
s = p.read_text(encoding='utf-8').replace('print(f"cocbot v{__version__}")', 'print(f"[INFO] CoC Bot v{__version__} starting...")')
p.write_text(s, encoding='utf-8')

# gui.py
p = root / 'gui.py'
s = p.read_text(encoding='utf-8')
s = s.replace('    "splash_enabled": True,', '    "splash_enabled": False,')
if '"army_preset"' not in s:
    s = s.replace('    "dump_mode": False,\n', '    "dump_mode": False,\n    "army_preset": "broom_witch",\n')
s = s.replace('splash_var = ctk.BooleanVar(value=True)', 'splash_var = ctk.BooleanVar(value=False)')
s = s.replace('text="Splash screen",', 'text="Splash disabled",')
s = s.replace('_help_icon(r, "Show the splash screen on startup.").pack(', '_help_icon(r, "Startup banner/GIF is disabled for fast launch.").pack(')
if 'army_preset_var = ctk.StringVar' not in s:
    insert = '''\nr = _row(atk_card)\nctk.CTkLabel(r, text="Army preset", font=("Segoe UI", 13)).pack(side="left", padx=(0, 6))\n_help_icon(r, "Switches deployment composition without changing code.").pack(side="left", padx=(0, 8))\narmy_preset_var = ctk.StringVar(value="broom_witch")\nctk.CTkOptionMenu(r, values=["broom_witch", "electro_dragon"], variable=army_preset_var, width=170).pack(side="left")\n'''
    s = s.replace('r = _row(atk_card)\n_single_entry(\n    r,\n    "Min total loot",', insert + '\nr = _row(atk_card)\n_single_entry(\n    r,\n    "Min total loot",')
    s = s.replace('    "attack_side": attack_side_var,\n', '    "attack_side": attack_side_var,\n    "army_preset": army_preset_var,\n')
s = re.sub(r'def _play_splash\(\):.*?\n\ndef _run_bot_cli\(\):', 'def _play_splash():\n    """Splash screen intentionally disabled for fast, clean startup."""\n    root.deiconify()\n\n\ndef _run_bot_cli():', s, flags=re.S)
p.write_text(s, encoding='utf-8')

# updater.py
p = root / 'cocbot' / 'updater.py'
s = p.read_text(encoding='utf-8')
s = s.replace('if "windows" in name or "cocbot" in name or "ghostfarm" in name:', 'if name == "coc-farm.zip" or "windows" in name or "cocbot" in name or "ghostfarm" in name or "coc-farm" in name:')
s = s.replace('if name in {"cocbot.exe", "ghostfarm.exe"} or "cocbot" in name or "ghostfarm" in name:', 'if name in {"coc-farm.exe", "cocbot.exe", "ghostfarm.exe"} or "coc-farm" in name or "cocbot" in name or "ghostfarm" in name:')
s = s.replace('new_exe = folder / "cocbot_new.exe"', 'new_exe = folder / "Coc-farm_new.exe"')
s = s.replace('temp_root = Path(tempfile.mkdtemp(prefix="cocbot_update_"))', 'temp_root = Path(tempfile.mkdtemp(prefix="coc_farm_update_"))')
p.write_text(s, encoding='utf-8')

# build.bat
(root / 'build.bat').write_text(r'''@echo off
REM Build Coc-farm.exe with fixed output naming.
setlocal
cd /d "%~dp0"

echo Building Coc-farm.exe ...
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
call ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
call ".venv\Scripts\python.exe" -m pip install pyinstaller
call ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean CoCBot.spec
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
echo DONE: %~dp0dist\Coc-farm\Coc-farm.exe
pause
''', encoding='utf-8')

# run.bat
(root / 'run.bat').write_text(r'''@echo off
setlocal
cd /d "%~dp0"
if exist "dist\Coc-farm\Coc-farm.exe" (
    start "" "dist\Coc-farm\Coc-farm.exe"
    exit /b 0
)
if exist "Coc-farm\Coc-farm.exe" (
    start "" "Coc-farm\Coc-farm.exe"
    exit /b 0
)
echo [ERROR] Coc-farm.exe not found. Build first or extract Coc-farm.zip.
pause
exit /b 1
''', encoding='utf-8')

# spec
p = root / 'CoCBot.spec'
s = p.read_text(encoding='utf-8')
s = s.replace('Produces a single standalone exe at: dist\\CoCBot.exe', 'Produces a stable folder package at: dist\\Coc-farm\\Coc-farm.exe')
s = s.replace('name="CoCBot",', 'name="Coc-farm",')
if 'coll = COLLECT(' not in s:
    s = s.replace('exe = EXE(\n    pyz,\n    a.scripts,\n    a.binaries,\n    a.zipfiles,\n    a.datas,\n    [],', 'exe = EXE(\n    pyz,\n    a.scripts,\n    [],')
    s = s.replace('    icon="templates/logo.ico",\n)', '    icon="templates/logo.ico",\n)\n\ncoll = COLLECT(\n    exe,\n    a.binaries,\n    a.zipfiles,\n    a.datas,\n    strip=False,\n    upx=True,\n    upx_exclude=[],\n    name="Coc-farm",\n)')
p.write_text(s, encoding='utf-8')

# build.yml
p = root / '.github/workflows/build.yml'
s = p.read_text(encoding='utf-8')
s = s.replace('cocbot/army.py ', '')
s = s.replace('python -m py_compile ', 'python -m py_compile cocbot/army.py ')
s = s.replace('--name cocbot `', '--name Coc-farm `').replace('--name cocbot', '--name Coc-farm')
s = s.replace('dist/cocbot/cocbot.exe', 'dist/Coc-farm/Coc-farm.exe')
s = s.replace('dist/cocbot/*', 'dist/Coc-farm/*')
s = re.sub(r'"zip=.*?" \| Out-File -FilePath \$env:GITHUB_OUTPUT -Append', '"zip=Coc-farm.zip" | Out-File -FilePath $env:GITHUB_OUTPUT -Append', s)
s = s.replace('run `cocbot.exe`', 'run `Coc-farm.exe`')
p.write_text(s, encoding='utf-8')

# tests
p = root / 'test_event_broom.py'
s = p.read_text(encoding='utf-8')
if 'support_calls' not in s:
    s = s.replace('    events = []\n\n    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "250,330")', '    events = []\n    support_calls = []\n\n    monkeypatch.setattr(event_broom.cfg, "broom_witch_slot_xs", "250,330")')
    s = s.replace('    monkeypatch.setattr(event_broom, "emit", lambda *args, **kwargs: events.append((args, kwargs)))\n\n    event_broom.deploy_broom_witches()\n', '    monkeypatch.setattr(event_broom, "emit", lambda *args, **kwargs: events.append((args, kwargs)))\n    monkeypatch.setattr(event_broom, "deploy_heroes", lambda *_args, **_kwargs: support_calls.append("warden"))\n    monkeypatch.setattr(event_broom, "deploy_rage_spells", lambda *_args, **_kwargs: support_calls.append("rage"))\n    monkeypatch.setattr(event_broom, "activate_warden_abilities", lambda *_args, **_kwargs: support_calls.append("tome"))\n\n    event_broom.deploy_broom_witches()\n')
    s = s.replace('    assert len(sleeps) == 1\n    assert events[0][0][0] == "broom_witch_deploy_start"', '    assert len(sleeps) == 1\n    assert support_calls == ["warden", "rage", "tome"]\n    assert events[0][0][0] == "broom_witch_deploy_start"')
p.write_text(s, encoding='utf-8')

# version
p = root / 'cocbot' / '__init__.py'
s = re.sub(r'__version__\s*=\s*"[^"]+"', '__version__ = "1.5.0"', p.read_text(encoding='utf-8'))
p.write_text(s, encoding='utf-8')

# cleanup temp files
(root / '.github' / 'workflows' / 'apply-refactor-source.yml').unlink(missing_ok=True)
(root / '.github' / 'scripts' / 'apply_refactor_source.py').unlink(missing_ok=True)
