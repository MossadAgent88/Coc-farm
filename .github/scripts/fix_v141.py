from pathlib import Path
import re

root = Path('.')

# config.py: multi-slot event deployment defaults.
p = root / 'cocbot' / 'config.py'
s = p.read_text(encoding='utf-8')
if 'broom_witch_slot_xs' not in s:
    s = s.replace(
        '# one known troop-bar slot, controlled waves, and no rapid-fire tapping.\n    broom_witch_slot_x: int = 250\n',
        '# bounded troop-bar slots, controlled waves, and no rapid-fire tapping.\n    # Use a comma-separated list because settings.json stores GUI values as text.\n    broom_witch_slot_xs: str = "250,330,410,490"\n    broom_witch_slot_x: int = 250  # legacy fallback if slot_xs is empty\n',
    )
p.write_text(s, encoding='utf-8')

# event_broom.py: deploy every configured event slot, not only one slot.
p = root / 'cocbot' / 'event_broom.py'
s = p.read_text(encoding='utf-8')
if 'def _configured_slot_xs()' not in s:
    s = s.replace(
        'def estimated_broom_witch_taps(waves: int | None = None) -> int:\n    """Return expected tap count; useful for keeping automation bounded."""\n    wave_count = max(1, int(waves if waves is not None else cfg.broom_witch_waves))\n    return wave_count * (1 + len(WIZARD_TOWER_PRESSURE_POINTS))\n\n\ndef deploy_broom_witches() -> None:\n',
        'def _configured_slot_xs() -> list[int]:\n    """Return bounded troop-bar slots used by event deployment.\n\n    Event armies can occupy more than one visible troop slot. Older builds only\n    selected one slot, which left the rest of the army unused. The list remains\n    configurable so users can match their own LDPlayer troop-bar layout without\n    returning to the old full-bar spam pattern.\n    """\n    raw = str(getattr(cfg, "broom_witch_slot_xs", "") or "")\n    slots: list[int] = []\n    for chunk in raw.replace(";", ",").split(","):\n        chunk = chunk.strip()\n        if not chunk:\n            continue\n        try:\n            x = int(float(chunk))\n        except ValueError:\n            logger.warning(f"Ignoring invalid Broom Witch slot x={chunk!r}")\n            continue\n        if 120 <= x <= 1510 and x not in slots:\n            slots.append(x)\n    if not slots:\n        slots = [int(cfg.broom_witch_slot_x)]\n    return slots[:8]\n\n\ndef estimated_broom_witch_taps(waves: int | None = None) -> int:\n    """Return expected tap count; useful for keeping automation bounded."""\n    wave_count = max(1, int(waves if waves is not None else cfg.broom_witch_waves))\n    return wave_count * len(_configured_slot_xs()) * (1 + len(WIZARD_TOWER_PRESSURE_POINTS))\n\n\ndef deploy_broom_witches() -> None:\n',
    )
    s = s.replace('    slot_x = int(cfg.broom_witch_slot_x)\n    waves = max(1, int(cfg.broom_witch_waves))\n', '    slot_xs = _configured_slot_xs()\n    waves = max(1, int(cfg.broom_witch_waves))\n')
    s = s.replace('        slot_x=slot_x,\n', '        slot_xs=slot_xs,\n')
    s = s.replace(
        '        tap(slot_x, TROOP_BAR_Y, delay=tap_delay)\n        for x, y in broom_witch_wave_points(wave):\n            jx, jy = _jitter_point(x, y)\n            tap(jx, jy, delay=tap_delay)\n',
        '        points = broom_witch_wave_points(wave)\n        for slot_x in slot_xs:\n            check_deadline("Broom Witch deploy")\n            tap(slot_x, TROOP_BAR_Y, delay=tap_delay)\n            for x, y in points:\n                jx, jy = _jitter_point(x, y)\n                tap(jx, jy, delay=tap_delay)\n',
    )
p.write_text(s, encoding='utf-8')

# gui.py: smooth stop and safe update close.
p = root / 'gui.py'
s = p.read_text(encoding='utf-8')
if '"broom_witch_slot_xs"' not in s:
    s = s.replace('    "dump_mode": False,\n}', '    "dump_mode": False,\n    "broom_witch_slot_xs": "250,330,410,490",\n}')
if '_stop_in_progress = False' not in s:
    s = s.replace('bot_process = None\n_start_time = None\n', 'bot_process = None\n_start_time = None\n_stop_in_progress = False\n')
old_stop = '''def stop_bot():
    global bot_process, _start_time
    if not bot_process or bot_process.poll() is not None:
        status_label.configure(text="Bot idle", text_color=RED)
        return

    # Kill entire process tree (bot + any ADB subprocesses)
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(bot_process.pid)],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        bot_process.kill()
    bot_process.wait()
    try:
        bot_process.stdout.close()
    except Exception:
        pass
    bot_process = None
    _start_time = None
    status_label.configure(text="Bot stopped", text_color=RED)
    start_btn.configure(state="normal")
    stop_btn.configure(state="disabled")
'''
new_stop = '''def _finish_stop_ui(proc=None, label="Bot stopped"):
    """Return the control panel to idle state after a background stop."""
    global bot_process, _start_time, _stop_in_progress
    if proc is None or bot_process is proc or (bot_process and bot_process.poll() is not None):
        bot_process = None
        _start_time = None
    _stop_in_progress = False
    status_label.configure(text=label, text_color=RED)
    start_btn.configure(state="normal")
    stop_btn.configure(text="STOP", state="disabled")


def _stop_worker(proc):
    """Terminate the bot process tree without freezing the GUI thread."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass
    try:
        if proc.stdout:
            proc.stdout.close()
    except Exception:
        pass
    root.after(0, _finish_stop_ui, proc, "Bot stopped")


def stop_bot():
    global _stop_in_progress
    if not bot_process or bot_process.poll() is not None:
        _finish_stop_ui(label="Bot idle")
        return
    if _stop_in_progress:
        return
    _stop_in_progress = True
    status_label.configure(text="Stopping bot...", text_color=YELLOW)
    stop_btn.configure(text="STOPPING...", state="disabled")
    start_btn.configure(state="disabled")
    threading.Thread(target=_stop_worker, args=(bot_process,), daemon=True).start()
'''
if old_stop in s:
    s = s.replace(old_stop, new_stop)
s = s.replace('            download_and_apply(info["url"])\n            root.after(0, lambda: (stop_bot(), root.destroy()))\n', '            download_and_apply(info["url"])\n            root.after(0, _request_close_after_update)\n')
if 'def _request_close_after_update():' not in s:
    s = s.replace('root.protocol("WM_DELETE_WINDOW", lambda: (stop_bot(), root.destroy()))\natexit.register(stop_bot)\n', 'def _request_close_after_update():\n    stop_bot()\n    root.after(250, root.destroy)\n\n\ndef _on_window_close():\n    stop_bot()\n    root.after(250, root.destroy)\n\n\nroot.protocol("WM_DELETE_WINDOW", _on_window_close)\natexit.register(lambda: None)\n')
p.write_text(s, encoding='utf-8')

# updater.py: stable ZIP updater plus legacy EXE fallback.
updater = r'''"""Reliable in-app auto-update for the compiled Coc Farm app.

The updater prefers a Windows ZIP package. That avoids PyInstaller one-file
TEMP extraction failures such as missing python311.dll/python312.dll. A legacy
single-EXE asset is still accepted for older releases.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from loguru import logger

from cocbot import __version__

GITHUB_OWNER = "MossadAgent88"
GITHUB_REPO = "Coc-farm"

_API_LATEST = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
_UA = {"User-Agent": "cocbot-updater", "Accept": "application/vnd.github+json"}


def _parse_version(text: str) -> tuple:
    parts = []
    for chunk in text.strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if digits:
            parts.append(int(digits))
    return tuple(parts)


def _choose_asset(assets: list[dict]) -> dict | None:
    """Prefer stable Windows ZIP packages, then legacy EXE assets."""
    zip_assets = [a for a in assets if a.get("name", "").lower().endswith(".zip")]
    for asset in zip_assets:
        name = asset.get("name", "").lower()
        if "windows" in name or "cocbot" in name or "ghostfarm" in name:
            return {**asset, "kind": "zip"}
    exe_assets = [a for a in assets if a.get("name", "").lower().endswith(".exe")]
    for asset in exe_assets:
        name = asset.get("name", "").lower()
        if name in {"cocbot.exe", "ghostfarm.exe"} or "cocbot" in name or "ghostfarm" in name:
            return {**asset, "kind": "exe"}
    return None


def check_for_update(timeout: int = 15):
    req = urllib.request.Request(_API_LATEST, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)

    tag = data.get("tag_name", "")
    latest = _parse_version(tag)
    current = _parse_version(__version__)
    if not latest or latest <= current:
        logger.info(f"Up to date (local v{__version__}, latest {tag or 'n/a'})")
        return None

    asset = _choose_asset(data.get("assets", []))
    if not asset:
        logger.warning(f"Release {tag} has no supported Windows asset attached.")
        return None

    return {
        "version": tag.lstrip("vV"),
        "url": asset["browser_download_url"],
        "asset_name": asset.get("name", ""),
        "kind": asset.get("kind", "exe"),
        "notes": data.get("body", "") or "",
    }


def _download(url: str, dest: Path, timeout: int) -> None:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp, dest.open("wb") as f:
        shutil.copyfileobj(resp, f)
    if dest.stat().st_size < 100_000:
        raise RuntimeError("Downloaded update looks too small; aborting.")


def _write_and_launch_helper(script: str, folder: Path) -> None:
    helper = folder / "_update_swap.bat"
    helper.write_text(script, encoding="ascii", errors="ignore")
    subprocess.Popen(
        ["cmd", "/c", str(helper)],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )


def _apply_exe(download_url: str, folder: Path, current_exe: Path, timeout: int) -> None:
    new_exe = folder / "cocbot_new.exe"
    _download(download_url, new_exe, timeout)
    script = (
        "@echo off\r\n"
        "setlocal\r\n"
        ":retry\r\n"
        f'move /Y "{new_exe}" "{current_exe}" >nul 2>&1\r\n'
        "if errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto retry\r\n"
        ")\r\n"
        f'start "" "{current_exe}"\r\n'
        'del "%~f0"\r\n'
    )
    _write_and_launch_helper(script, folder)


def _apply_zip(download_url: str, folder: Path, current_exe: Path, timeout: int) -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="cocbot_update_"))
    zip_path = temp_root / "update.zip"
    extract_dir = temp_root / "payload"
    _download(download_url, zip_path, timeout)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)

    exe_candidates = list(extract_dir.rglob("*.exe"))
    if not exe_candidates:
        raise RuntimeError("Update ZIP does not contain an executable.")
    payload_dir = exe_candidates[0].parent
    launch_exe = folder / current_exe.name

    script = (
        "@echo off\r\n"
        "setlocal\r\n"
        ":waitlock\r\n"
        f'tasklist /FI "IMAGENAME eq {current_exe.name}" | find /I "{current_exe.name}" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto waitlock\r\n"
        ")\r\n"
        f'robocopy "{payload_dir}" "{folder}" /MIR /NFL /NDL /NJH /NJS /NP >nul\r\n'
        f'start "" "{launch_exe}"\r\n'
        f'rmdir /S /Q "{temp_root}"\r\n'
        'del "%~f0"\r\n'
    )
    _write_and_launch_helper(script, folder)


def download_and_apply(download_url: str, timeout: int = 180) -> None:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Auto-update only works in the built app. When running from source, update from GitHub.")

    current_exe = Path(sys.executable).resolve()
    folder = current_exe.parent
    lower_url = download_url.lower().split("?")[0]
    logger.info(f"Downloading update from {download_url}")
    if lower_url.endswith(".zip"):
        _apply_zip(download_url, folder, current_exe, timeout)
    else:
        _apply_exe(download_url, folder, current_exe, timeout)
    logger.info("Launching update helper; app will close to finish update.")
'''
(root / 'cocbot' / 'updater.py').write_text(updater, encoding='utf-8')

# Version bump and cleanup.
p = root / 'cocbot' / '__init__.py'
s = p.read_text(encoding='utf-8')
s = re.sub(r'__version__\s*=\s*"[^"]+"', '__version__ = "1.4.1"', s, count=1)
p.write_text(s, encoding='utf-8')
(root / '.github' / 'workflows' / 'fix-v1-4-1-build.yml').unlink(missing_ok=True)
(root / '.github' / 'scripts' / 'fix_v141.py').unlink(missing_ok=True)
