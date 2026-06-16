"""ADB primitives — pure I/O to the LDPlayer emulator.

No game knowledge. No imports from vision/actions/loop.
Timing and jitter values are empirically tuned — do not "optimize".
"""

import glob
import os
import random
import struct
import subprocess
import time

import cv2
import numpy as np
from loguru import logger

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


def _find_ldplayer_tool(filename: str, env_var: str) -> str:
    """Locate an LDPlayer tool (adb.exe / ldconsole.exe).

    Order of preference:
      1. Explicit override via environment variable.
      2. Auto-detect: scan common LDPlayer install folders for any
         version (LDPlayer9, LDPlayer14, etc.).
      3. Fall back to the classic LDPlayer9 default so behaviour is
         unchanged when nothing is found.
    """
    override = os.environ.get(env_var)
    if override and os.path.exists(override):
        return override

    search_roots = [
        r"C:\LDPlayer",
        r"D:\LDPlayer",
        r"E:\LDPlayer",
        r"C:\Program Files\LDPlayer",
        r"C:\Program Files (x86)\LDPlayer",
        r"C:\Program Files\XuanZhi",
        r"C:\Program Files (x86)\XuanZhi",
    ]
    for root in search_roots:
        for pattern in (
            os.path.join(root, "LDPlayer*", filename),
            os.path.join(root, filename),
        ):
            matches = glob.glob(pattern)
            if matches:
                return matches[0]

    return os.path.join(r"C:\LDPlayer\LDPlayer9", filename)


ADB_PATH = _find_ldplayer_tool("adb.exe", "ADB_PATH")
LDCONSOLE_PATH = _find_ldplayer_tool("ldconsole.exe", "LDCONSOLE_PATH")
logger.info(f"Using ADB: {ADB_PATH}")
logger.info(f"Using ldconsole: {LDCONSOLE_PATH}")
LDPLAYER_INDEX = "0"
DEVICE_SERIAL = None  # Auto-detected

COC_PACKAGE = "com.supercell.clashofclans"
COC_ACTIVITY = "com.supercell.titan.GameApp"


def _run_adb(*args, timeout=10) -> subprocess.CompletedProcess:
    """Run an ADB command, auto-reconnect on failure."""
    serial = _detect_device()
    cmd = [ADB_PATH, "-s", serial, *args]
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=timeout, creationflags=_SUBPROCESS_FLAGS
        )
        if b"device not found" in (result.stderr or b"") or b"offline" in (
            result.stderr or b""
        ):
            logger.warning("Device lost, reconnecting...")
            _reconnect()
            serial = _detect_device()
            cmd = [ADB_PATH, "-s", serial, *args]
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                creationflags=_SUBPROCESS_FLAGS,
            )
        return result
    except subprocess.TimeoutExpired:
        logger.warning(f"ADB command timed out: {args}, reconnecting...")
        _reconnect()
        raise


def _reconnect():
    """Kill ADB server and reconnect."""
    global DEVICE_SERIAL
    DEVICE_SERIAL = None
    logger.info("Restarting ADB server...")
    subprocess.run(
        [ADB_PATH, "kill-server"],
        timeout=5,
        capture_output=True,
        creationflags=_SUBPROCESS_FLAGS,
    )
    time.sleep(1)
    subprocess.run(
        [ADB_PATH, "start-server"],
        timeout=10,
        capture_output=True,
        creationflags=_SUBPROCESS_FLAGS,
    )
    time.sleep(2)
    for port in [5554, 5555, 5556]:
        subprocess.run(
            [ADB_PATH, "connect", f"localhost:{port}"],
            timeout=5,
            capture_output=True,
            creationflags=_SUBPROCESS_FLAGS,
        )
    time.sleep(1)


def _detect_device() -> str:
    """Find the first connected ADB device, reconnect if needed."""
    global DEVICE_SERIAL
    if DEVICE_SERIAL:
        return DEVICE_SERIAL

    result = subprocess.run(
        [ADB_PATH, "devices"],
        capture_output=True,
        text=True,
        timeout=5,
        creationflags=_SUBPROCESS_FLAGS,
    )
    for line in result.stdout.strip().splitlines()[1:]:
        if "\tdevice" in line:
            DEVICE_SERIAL = line.split("\t")[0]
            logger.info(f"Auto-detected device: {DEVICE_SERIAL}")
            return DEVICE_SERIAL

    logger.warning("No device found, attempting reconnect...")
    _reconnect()

    result = subprocess.run(
        [ADB_PATH, "devices"],
        capture_output=True,
        text=True,
        timeout=5,
        creationflags=_SUBPROCESS_FLAGS,
    )
    for line in result.stdout.strip().splitlines()[1:]:
        if "\tdevice" in line:
            DEVICE_SERIAL = line.split("\t")[0]
            logger.info(f"Reconnected to device: {DEVICE_SERIAL}")
            return DEVICE_SERIAL

    raise RuntimeError("No ADB device found after reconnect. Is LDPlayer running?")


def capture_screenshot() -> np.ndarray:
    """Capture screenshot from LDPlayer via ADB, return as BGR numpy array."""
    result = _run_adb("exec-out", "screencap")
    if result.returncode != 0:
        raise RuntimeError(f"ADB screencap failed: {result.stderr.decode()}")

    data = result.stdout
    if len(data) < 12:
        raise RuntimeError(
            f"ADB screencap returned too little data ({len(data)} bytes)"
        )

    w, h, fmt = struct.unpack("<III", data[:12])
    expected = w * h * 4 + 12
    if len(data) < expected:
        img_array = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("Failed to decode screenshot (both raw and PNG)")
        logger.debug(
            f"Screenshot captured (PNG fallback): {img.shape[1]}x{img.shape[0]}"
        )
    else:
        pixels = np.frombuffer(data, dtype=np.uint8, offset=12, count=w * h * 4)
        img = pixels.reshape(h, w, 4)
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        logger.debug(f"Screenshot captured: {w}x{h}")

    # All vision code is tuned for 1920x1080. Fail loud if emulator resolution drifted.
    if img.shape != (1080, 1920, 3):
        raise RuntimeError(
            f"Expected 1920x1080 BGR screenshot, got shape {img.shape}. "
            "Check LDPlayer resolution."
        )
    return img


def _humanize(value: int, jitter: int = 5) -> int:
    """Add small random offset to a coordinate to mimic human finger imprecision."""
    return value + random.randint(-jitter, jitter)


def tap(x: int, y: int, delay: float = 0.1):
    """Tap at screen coordinates with slight random offset for human-like input.

    ADB rapid taps merge into swipes if spaced closer than ~0.05s apart
    (0.15s after troop selection). The default delay keeps us safe.
    """
    hx, hy = _humanize(x), _humanize(y)
    _run_adb("shell", "input", "tap", str(hx), str(hy), timeout=5)
    logger.debug(f"Tapped at ({hx}, {hy})")
    time.sleep(delay + random.uniform(0, 0.08))


def swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300):
    """Swipe from (x1,y1) to (x2,y2) with slight randomization."""
    hx1, hy1 = _humanize(x1), _humanize(y1)
    hx2, hy2 = _humanize(x2), _humanize(y2)
    hduration = duration_ms + random.randint(-30, 30)
    _run_adb(
        "shell",
        "input",
        "swipe",
        str(hx1),
        str(hy1),
        str(hx2),
        str(hy2),
        str(hduration),
    )
    logger.debug(f"Swiped ({hx1},{hy1}) -> ({hx2},{hy2})")


def press_back():
    """Press Android back button."""
    _run_adb("shell", "input", "keyevent", "4", timeout=5)
    logger.debug("Pressed BACK")


def launch_coc() -> bool:
    """Launch Clash of Clans. Returns True if already running."""
    result = _run_adb("shell", "dumpsys", "window", "windows")
    if COC_PACKAGE in result.stdout.decode(errors="ignore"):
        logger.info("CoC is already running")
        return True

    logger.info("Launching Clash of Clans...")
    _run_adb("shell", "am", "start", "-n", f"{COC_PACKAGE}/{COC_ACTIVITY}")
    return False


def force_restart_coc():
    """Kill and relaunch Clash of Clans."""
    logger.warning("Force-restarting CoC...")
    _run_adb("shell", "am", "force-stop", COC_PACKAGE, timeout=5)
    time.sleep(2)
    _run_adb("shell", "am", "start", "-n", f"{COC_PACKAGE}/{COC_ACTIVITY}")


def zoom_out(steps: int = 15):
    """Zoom out using LDPlayer's ldconsole command."""
    logger.info(f"Zooming out ({steps} steps)...")
    for _ in range(steps):
        subprocess.run(
            [LDCONSOLE_PATH, "zoomOut", "--index", LDPLAYER_INDEX],
            timeout=5,
            capture_output=True,
            creationflags=_SUBPROCESS_FLAGS,
        )
        time.sleep(0.2)
    logger.info("Zoom out complete")


def check_connection() -> bool:
    """Verify ADB device is connected."""
    try:
        _detect_device()
        return True
    except RuntimeError:
        logger.error("ADB not connected")
        return False
