"""Reliable in-app auto-update for the compiled Coc Farm app.

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
        if name == "coc-farm.zip" or "windows" in name or "cocbot" in name or "ghostfarm" in name or "coc-farm" in name:
            return {**asset, "kind": "zip"}
    exe_assets = [a for a in assets if a.get("name", "").lower().endswith(".exe")]
    for asset in exe_assets:
        name = asset.get("name", "").lower()
        if name in {"coc-farm.exe", "cocbot.exe", "ghostfarm.exe"} or "coc-farm" in name or "cocbot" in name or "ghostfarm" in name:
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
    new_exe = folder / "Coc-farm_new.exe"
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
    temp_root = Path(tempfile.mkdtemp(prefix="coc_farm_update_"))
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
