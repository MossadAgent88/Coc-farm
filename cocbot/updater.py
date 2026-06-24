"""Reliable in-app auto-update for the compiled Coc Farm app.

The updater prefers a Windows ZIP package. That avoids PyInstaller one-file
TEMP extraction failures such as missing python311.dll/python312.dll. A legacy
single-EXE asset is still accepted for older releases.
"""

from __future__ import annotations

import hashlib
import json
import re
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

# The canonical Windows release asset. Must match the CI build output.
PREFERRED_ZIP_NAME = "CoC-Farm-Bot-Windows.zip"


class NoAssetError(RuntimeError):
    """Raised when the latest release has no usable Windows asset."""


def _parse_version(text: str) -> tuple:
    parts = []
    for chunk in text.strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if digits:
            parts.append(int(digits))
    return tuple(parts)


def _choose_asset(assets: list[dict]) -> dict | None:
    """Prefer the canonical Windows ZIP, then other Windows zips, then legacy EXE."""
    # 1) Exact preferred ZIP name.
    for asset in assets:
        if asset.get("name", "") == PREFERRED_ZIP_NAME:
            return {**asset, "kind": "zip"}
    # 2) Any other Windows-flavored ZIP.
    zip_assets = [a for a in assets if a.get("name", "").lower().endswith(".zip")]
    for asset in zip_assets:
        name = asset.get("name", "").lower()
        if "windows" in name or "coc-farm" in name or "cocbot" in name:
            return {**asset, "kind": "zip"}
    # 3) Legacy single-EXE assets.
    exe_assets = [a for a in assets if a.get("name", "").lower().endswith(".exe")]
    for asset in exe_assets:
        name = asset.get("name", "").lower()
        if name in {"coc-farm.exe", "cocbot.exe"} or "coc-farm" in name or "cocbot" in name:
            return {**asset, "kind": "exe"}
    return None


def _find_sha256_sidecar(assets: list[dict]) -> str | None:
    """Return the browser_download_url of a ``.sha256`` sidecar asset, if present."""
    for asset in assets:
        name = asset.get("name", "").lower()
        if name.endswith(".sha256") or name.endswith(".sha256sum"):
            return asset.get("browser_download_url")
    return None


def _parse_sha256_from_notes(body: str) -> str | None:
    """Extract a SHA256 hash from release notes / body text.

    Accepts common formats:
      - ``SHA256: abc123...``
      - ``sha256= abc123...``
      - ``<64-hex>  CoC-Farm-Bot-Windows.zip`` (sha256sum format)
      - a bare 64-char hex string on its own line
    """
    if not body:
        return None
    # Labelled forms.
    m = re.search(r"(?:sha-?256)[:\s=]+([0-9a-fA-F]{64})", body, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    # sha256sum-style: "<hex>  filename"
    for line in body.splitlines():
        m = re.match(r"([0-9a-fA-F]{64})\s+\S+", line.strip())
        if m:
            return m.group(1).lower()
    # Bare 64-char hex on its own line.
    for line in body.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"[0-9a-fA-F]{64}", stripped):
            return stripped.lower()
    return None


def fetch_sha256_from_sidecar(sidecar_url: str, timeout: int = 15) -> str | None:
    """Download and parse a ``.sha256`` sidecar asset for the hash.

    The sidecar format is typically ``<64-hex>  <filename>``.
    Returns the lowercase hex hash, or None if it can't be parsed.
    """
    try:
        req = urllib.request.Request(sidecar_url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning(f"Could not fetch SHA256 sidecar {sidecar_url}: {exc}")
        return None
    return _parse_sha256_from_notes(text)


def check_for_update(timeout: int = 15):
    """Check GitHub for a newer release.

    Returns a dict with version/url/asset_name/kind/notes/sha256_url when an
    update is available, ``None`` when up-to-date, and raises ``NoAssetError``
    when a newer release exists but has no usable Windows asset.
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

    assets = data.get("assets", [])
    asset = _choose_asset(assets)
    if not asset:
        asset_names = [a.get("name", "?") for a in assets]
        raise NoAssetError(
            f"No Windows ZIP asset found in latest release ({tag}). "
            f"Available assets: {asset_names or 'none'}"
        )

    sha256_url = _find_sha256_sidecar(assets)
    body = data.get("body", "") or ""
    sha256_from_notes = _parse_sha256_from_notes(body)

    return {
        "version": tag.lstrip("vV"),
        "url": asset["browser_download_url"],
        "asset_name": asset.get("name", ""),
        "kind": asset.get("kind", "exe"),
        "notes": body,
        "sha256_url": sha256_url,
        "sha256": sha256_from_notes,
    }


def _download(url: str, dest: Path, timeout: int, expected_sha256: str | None = None) -> None:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp, dest.open("wb") as f:
        shutil.copyfileobj(resp, f)
    if dest.stat().st_size < 100_000:
        raise RuntimeError("Downloaded update looks too small; aborting.")
    if expected_sha256:
        actual = _sha256_file(dest)
        if actual.lower() != expected_sha256.lower():
            raise RuntimeError(
                f"SHA256 mismatch: expected {expected_sha256}, got {actual}. Aborting."
            )
        logger.info(f"SHA256 verified: {actual}")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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


def _apply_zip(folder: Path, current_exe: Path, zip_path: Path) -> None:
    """Stage an ALREADY-downloaded (and, when a hash was supplied, already
    verified) ZIP and launch the swap helper.

    The ZIP lives in its own temp dir (``zip_path.parent``); the swap helper
    removes that temp dir after the swap completes.
    """
    temp_root = zip_path.parent
    extract_dir = temp_root / "payload"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)

    exe_candidates = list(extract_dir.rglob("*.exe"))
    if not exe_candidates:
        raise RuntimeError("Update ZIP does not contain an executable.")
    payload_dir = exe_candidates[0].parent
    launch_exe = folder / current_exe.name
    script = _zip_swap_script(payload_dir, folder, launch_exe, temp_root, current_exe.name)
    _write_and_launch_helper(script, folder)


# User data that must survive an update: robocopy /MIR would otherwise DELETE
# these (they are absent from the fresh payload). Kept as a module constant so
# tests can assert the swap script never drops them.
PRESERVE_FILES = "settings.json bases.json armies.json *.log"
PRESERVE_DIRS = "logs debug screenshots"


def _zip_swap_script(
    payload_dir: Path,
    folder: Path,
    launch_exe: Path,
    temp_root: Path,
    exe_name: str,
) -> str:
    """Build the .bat that waits for the EXE to close, mirrors the new payload
    in while preserving user data, relaunches, and cleans up. Pure/ testable."""
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        ":waitlock\r\n"
        f'tasklist /FI "IMAGENAME eq {exe_name}" | find /I "{exe_name}" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto waitlock\r\n"
        ")\r\n"
        f'robocopy "{payload_dir}" "{folder}" /MIR /XF {PRESERVE_FILES} '
        f'/XD {PRESERVE_DIRS} /NFL /NDL /NJH /NJS /NP >nul\r\n'
        f'start "" "{launch_exe}"\r\n'
        f'rmdir /S /Q "{temp_root}"\r\n'
        'del "%~f0"\r\n'
    )


def download_and_apply(
    download_url: str,
    timeout: int = 180,
    sha256: str | None = None,
    sha256_url: str | None = None,
) -> None:
    """Download the update and launch the swap helper.

    If ``sha256`` is provided, the downloaded file is verified against it before
    the swap helper runs. If ``sha256_url`` is provided (a ``.sha256`` sidecar
    asset), it's fetched and parsed to obtain the hash when ``sha256`` is None.
    """
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Auto-update only works in the built app. When running from source, update from GitHub.")

    # Resolve the expected hash: explicit > sidecar > None.
    expected_hash = sha256
    if not expected_hash and sha256_url:
        expected_hash = fetch_sha256_from_sidecar(sha256_url, timeout=15)
        if expected_hash:
            logger.info(f"Using SHA256 from sidecar: {expected_hash}")

    current_exe = Path(sys.executable).resolve()
    folder = current_exe.parent
    lower_url = download_url.lower().split("?")[0]
    logger.info(f"Downloading update from {download_url}")
    if lower_url.endswith(".zip"):
        # Download ONCE into its own temp dir; verify inline (when a hash is
        # known) before staging, then hand the verified path to the swap helper.
        temp_root = Path(tempfile.mkdtemp(prefix="coc_farm_update_"))
        zip_path = temp_root / "update.zip"
        _download(download_url, zip_path, timeout, expected_sha256=expected_hash)
        if expected_hash:
            logger.info("SHA256 verified; staging ZIP update.")
        _apply_zip(folder, current_exe, zip_path)
    else:
        _apply_exe(download_url, folder, current_exe, timeout)
    logger.info("Launching update helper; app will close to finish update.")