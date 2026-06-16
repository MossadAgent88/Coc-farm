"""In-app auto-update for the compiled CoCBot.exe.

How it works:
  1. check_for_update() asks GitHub for the latest published Release and
     compares its version tag (e.g. "v1.3.1") to the running __version__.
  2. If a newer build exists, download_and_apply() downloads the new
     CoCBot.exe next to the current one, writes a tiny swap helper .bat,
     launches it, and the app exits. The helper waits for the old exe to
     release its file lock, swaps in the new exe, and relaunches it.

A running .exe can't overwrite itself, which is why the swap happens in a
separate helper process after the app quits.

The GITHUB_OWNER / GITHUB_REPO below must point at the repo whose GitHub
Actions workflow publishes CoCBot.exe as a Release asset.
"""

import json
import os
import subprocess
import sys
import urllib.request

from loguru import logger

from cocbot import __version__

# ── CONFIG ────────────────────────────────────────────────────────────
# Set these to YOUR GitHub repo (the one with the build workflow).
GITHUB_OWNER = "MossadAgent88"
GITHUB_REPO = "Coc-farm"
# ──────────────────────────────────────────────────────────────────────

_API_LATEST = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
_ASSET_NAME = "cocbot.exe"  # matched case-insensitively
_UA = {"User-Agent": "cocbot-updater", "Accept": "application/vnd.github+json"}


def _parse_version(text: str) -> tuple:
    """'v1.3.10' -> (1, 3, 10). Non-numeric parts are ignored."""
    parts = []
    for chunk in text.strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if digits:
            parts.append(int(digits))
    return tuple(parts)


def check_for_update(timeout: int = 15):
    """Return dict(version, url, notes) if a newer release exists, else None.

    Raises on network/parse errors so the caller can show a message.
    """
    req = urllib.request.Request(_API_LATEST, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)

    tag = data.get("tag_name", "")
    latest = _parse_version(tag)
    current = _parse_version(__version__)
    if not latest or latest <= current:
        logger.info(f"Up to date (local v{__version__}, latest {tag or 'n/a'})")
        return None

    for asset in data.get("assets", []):
        if asset.get("name", "").lower() == _ASSET_NAME:
            return {
                "version": tag.lstrip("vV"),
                "url": asset["browser_download_url"],
                "notes": data.get("body", "") or "",
            }

    logger.warning(f"Release {tag} has no {_ASSET_NAME} asset attached.")
    return None


def download_and_apply(download_url: str, timeout: int = 180) -> None:
    """Download the new exe and launch the swap helper. Caller must exit after.

    Only works when running as the frozen exe (sys.frozen).
    """
    if not getattr(sys, "frozen", False):
        raise RuntimeError(
            "Auto-update only works in the built CoCBot.exe. "
            "When running from source, use the Update via GitHub instead."
        )

    current_exe = sys.executable
    folder = os.path.dirname(current_exe)
    new_exe = os.path.join(folder, "CoCBot_new.exe")
    helper = os.path.join(folder, "_update_swap.bat")

    logger.info(f"Downloading update to {new_exe} ...")
    req = urllib.request.Request(download_url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(new_exe, "wb") as f:
        f.write(resp.read())

    if os.path.getsize(new_exe) < 100_000:
        raise RuntimeError("Downloaded file looks too small — aborting update.")

    # Swap helper: loop until the old exe's lock is released (app has exited),
    # then replace it and relaunch. Deletes itself at the end.
    script = (
        "@echo off\r\n"
        "setlocal\r\n"
        ":retry\r\n"
        f'move /Y "{new_exe}" "{current_exe}" >nul 2>&1\r\n'
        "if errorlevel 1 (\r\n"
        "  ping 127.0.0.1 -n 2 >nul\r\n"
        "  goto retry\r\n"
        ")\r\n"
        f'start "" "{current_exe}"\r\n'
        'del "%~f0"\r\n'
    )
    with open(helper, "w", encoding="ascii") as f:
        f.write(script)

    logger.info("Launching update helper; app will now close to finish update.")
    subprocess.Popen(
        ["cmd", "/c", helper],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )
