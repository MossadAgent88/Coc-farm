"""GUI controller for the CoC Farm Bot.

The GUI talks to this class only. The controller owns process startup,
shutdown, stdout streaming, update checks, and small JSON stores used by the
new Bases and Armies tabs. The farming backend remains behind ``python -m
cocbot`` or the frozen app's ``--bot`` entrypoint.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from cocbot import __version__


EVENT_PREFIX = "__EVENT__ "
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Folders the backend may write debug/screenshot PNGs into, relative to a
# data root (current working dir and the app dir). Order = display priority.
SCREENSHOT_SUBDIRS = ("debug/runtime", "debug", "debug_screenshots", "screenshots")


class JsonLinkStore:
    def __init__(self, path: Path, default_kind: str) -> None:
        self.path = path
        self.default_kind = default_kind

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [self._clean_row(item) for item in data if isinstance(item, dict)]

    def save(self, rows: list[dict[str, Any]]) -> None:
        clean = []
        for row in rows:
            item = self._clean_row(row)
            if not item.get("name") and not item.get("link"):
                continue
            clean.append(item)
        self.path.write_text(json.dumps(clean, indent=2), encoding="utf-8")

    def _clean_row(self, row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        for key in ("name", "link", "notes", "category", "purpose", "troops", "spells", "siege", "lastCopied"):
            if key in item:
                item[key] = str(item.get(key, "")).strip()
        item["kind"] = str(item.get("kind", self.default_kind)).strip() or self.default_kind
        try:
            item["id"] = int(item.get("id", 0))
        except (TypeError, ValueError):
            item["id"] = 0
        try:
            item["th"] = int(str(item.get("th", 13)).replace("TH", ""))
        except (TypeError, ValueError):
            item["th"] = 13
        try:
            item["added"] = int(item.get("added", 0))
        except (TypeError, ValueError):
            item["added"] = 0
        item["fav"] = bool(item.get("fav", False))
        item["donations"] = bool(item.get("donations", False))
        tags = item.get("tags", [])
        if isinstance(tags, str):
            tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
        elif isinstance(tags, list):
            tags = [str(tag).strip() for tag in tags if str(tag).strip()]
        else:
            tags = []
        item["tags"] = tags
        return item


class BotController:
    def __init__(self, base_dir: Path | None = None, frozen: bool | None = None) -> None:
        self.base_dir = Path(base_dir or Path(__file__).parent)
        self.frozen = getattr(sys, "frozen", False) if frozen is None else frozen
        self.events: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self.process: subprocess.Popen | None = None
        self.started_at: float | None = None
        self._stop_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._starting = False
        self._cancel_start = False
        self.settings_path = Path.cwd() / "settings.json"
        self.bases = JsonLinkStore(Path.cwd() / "bases.json", "base")
        self.armies = JsonLinkStore(Path.cwd() / "armies.json", "army")
        self._shot_index: dict[str, Path] = {}
        self._shot_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._starting or (self.process is not None and self.process.poll() is None)

    def emit(self, kind: str, **payload: Any) -> None:
        self.events.put({"kind": kind, **payload})

    def load_settings(self) -> dict[str, Any]:
        if not self.settings_path.exists():
            return {}
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.emit("log", text="Settings file could not be read; using defaults.", level="warning")
            return {}
        return data if isinstance(data, dict) else {}

    def save_settings(self, data: dict[str, Any]) -> None:
        self.settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.emit("log", text="Settings saved to settings.json.", level="success")

    def reload_settings(self) -> dict[str, Any]:
        data = self.load_settings()
        self.emit("log", text="Settings reloaded from settings.json.", level="info")
        return data

    def _python_command(self, subcmd: str, *extra_args: str) -> list[str]:
        if self.frozen:
            return [sys.executable, "--bot", subcmd, *extra_args]
        venv_py = self.base_dir / ".venv" / "Scripts" / "python.exe"
        python = str(venv_py if venv_py.exists() else Path(sys.executable))
        return [python, "-u", "-m", "cocbot", subcmd, *extra_args]

    def start(self, settings: dict[str, Any]) -> None:
        self._start_subprocess("loop", "Farming", settings)

    def run_tool(self, subcmd: str, label: str, *extra_args: str, settings: dict[str, Any] | None = None) -> None:
        self._start_subprocess(subcmd, label, settings, *extra_args)

    def collect_resources(self) -> None:
        self.emit("log", text="Collect resources: not implemented yet.", level="warning")

    def _start_subprocess(
        self,
        subcmd: str,
        label: str,
        settings: dict[str, Any] | None,
        *extra_args: str,
    ) -> None:
        with self._start_lock:
            if self.is_running:
                self.emit("status", running=True, text="Bot already running")
                self.emit("log", text="Cannot start another action while the bot is running.", level="warning")
                return
            self._starting = True
            self._cancel_start = False
        if settings is not None:
            try:
                self.save_settings(settings)
            except Exception as exc:
                self._starting = False
                self._cancel_start = False
                self.emit("log", text=f"Could not save settings: {exc}", level="error")
                return
        threading.Thread(
            target=self._spawn_worker,
            args=(subcmd, label, extra_args),
            daemon=True,
        ).start()

    def _spawn_worker(self, subcmd: str, label: str, extra_args: tuple[str, ...]) -> None:
        try:
            cmd = self._python_command(subcmd, *extra_args)
            flags = 0
            if os.name == "nt":
                flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
            if self._cancel_start:
                self._starting = False
                self.emit("log", text=f"{label} start cancelled; stopping process.", level="warning")
                threading.Thread(target=self._stop_worker, args=(self.process,), daemon=True).start()
                return
            self.started_at = time.time()
            self._starting = False
            self.emit(
                "status",
                running=True,
                text=f"{label} (PID {self.process.pid})",
                started_at=self.started_at,
            )
            threading.Thread(target=self._read_stdout_worker, daemon=True).start()
        except Exception as exc:
            self.process = None
            self.started_at = None
            self._starting = False
            self._cancel_start = False
            self.emit("status", running=False, text="Bot idle")
            self.emit("log", text=f"Failed to start bot: {exc}", level="error")

    def _read_stdout_worker(self) -> None:
        proc = self.process
        if proc is None or proc.stdout is None:
            return
        try:
            for raw in proc.stdout:
                text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                text = ANSI_RE.sub("", text)
                if text.startswith(EVENT_PREFIX):
                    payload = text[len(EVENT_PREFIX) :]
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        self.emit("log", text=text, level="info")
                    else:
                        self.emit("bot_event", event=event)
                    continue
                self.emit("log", text=text, level=self._level_for_log(text))
        except Exception as exc:
            self.emit("log", text=f"Log reader failed: {exc}", level="error")
        finally:
            code = None
            try:
                code = proc.wait(timeout=1)
            except Exception:
                pass
            if self.process is proc:
                self.process = None
                self.started_at = None
                self.emit("status", running=False, text="Bot idle")
                self.emit("process_exit", code=code)

    def _level_for_log(self, text: str) -> str:
        upper = text.upper()
        if "ERROR" in upper or "CRITICAL" in upper:
            return "error"
        if "WARNING" in upper or "WARN" in upper:
            return "warning"
        if "GOOD LOOT" in upper or "SUCCESS" in upper or "COMPLETE" in upper:
            return "success"
        if "DEBUG" in upper:
            return "debug"
        return "info"

    def stop(self) -> None:
        proc = self.process
        if proc is None and self._starting:
            self._cancel_start = True
            self.emit("status", running=True, text="Stopping bot...")
            self.emit("log", text="Stop requested while bot was starting.", level="warning")
            return
        if proc is None or proc.poll() is not None:
            self.process = None
            self.started_at = None
            self._starting = False
            self._cancel_start = False
            self.emit("status", running=False, text="Bot idle")
            return
        threading.Thread(target=self._stop_worker, args=(proc,), daemon=True).start()

    def _stop_worker(self, proc: subprocess.Popen) -> None:
        with self._stop_lock:
            self.emit("status", running=True, text="Stopping bot...")
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True,
                        timeout=5,
                    )
                else:
                    proc.terminate()
            except Exception as exc:
                self.emit("log", text=f"Graceful stop failed: {exc}", level="warning")
                try:
                    proc.kill()
                except Exception as kill_exc:
                    self.emit("log", text=f"Force stop failed: {kill_exc}", level="error")
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
            if self.process is proc:
                self.process = None
                self.started_at = None
                self._starting = False
                self._cancel_start = False
                self.emit("status", running=False, text="Bot stopped")

    def check_update(self) -> None:
        threading.Thread(target=self._check_update_worker, daemon=True).start()

    def _check_update_worker(self) -> None:
        try:
            from cocbot.updater import check_for_update

            info = check_for_update()
            self.emit("update_result", info=info, error=None)
        except Exception as exc:
            self.emit("update_result", info=None, error=str(exc))

    def apply_update(self, info: dict[str, Any]) -> None:
        threading.Thread(target=self._apply_update_worker, args=(info,), daemon=True).start()

    def _apply_update_worker(self, info: dict[str, Any]) -> None:
        try:
            from cocbot.updater import download_and_apply

            download_and_apply(info["url"])
            self.emit("update_applied")
        except Exception as exc:
            self.emit("log", text=f"Update failed: {exc}", level="error")
            self.emit("update_failed", error=str(exc))

    def open_link(self, link: str) -> None:
        link = link.strip()
        if not link:
            self.emit("log", text="No link to open.", level="warning")
            return
        threading.Thread(target=self._open_link_worker, args=(link,), daemon=True).start()

    def _open_link_worker(self, link: str) -> None:
        try:
            webbrowser.open(link)
            self.emit("log", text=f"Opened link: {link}", level="info")
        except Exception as exc:
            self.emit("log", text=f"Could not open link: {exc}", level="error")

    def copy_link(self, link: str) -> None:
        self.emit("copy_link", link=link.strip())

    # ── Clipboard ───────────────────────────────────────────────────────────
    def copy_text(self, text: str) -> dict[str, Any]:
        """Copy *text* to the OS clipboard. Returns {"ok": bool, "error": str}.

        Tries pyperclip first (if installed), then a platform-native command.
        Never fakes success — the GUI relies on the real result.
        """
        text = "" if text is None else str(text)
        try:
            import pyperclip  # optional dependency

            pyperclip.copy(text)
            return {"ok": True}
        except Exception:
            pass

        try:
            if os.name == "nt":
                flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                subprocess.run(
                    ["clip"], input=text.encode("utf-16-le"), check=True, creationflags=flags
                )
            elif sys.platform == "darwin":
                subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
            else:
                try:
                    subprocess.run(
                        ["xclip", "-selection", "clipboard"],
                        input=text.encode("utf-8"),
                        check=True,
                    )
                except FileNotFoundError:
                    subprocess.run(["xsel", "--clipboard", "--input"], input=text.encode("utf-8"), check=True)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ── Debug screenshots ───────────────────────────────────────────────────
    def _screenshot_roots(self) -> list[Path]:
        roots: list[Path] = []
        seen: set[str] = set()
        for base in (Path.cwd(), self.base_dir):
            for sub in SCREENSHOT_SUBDIRS:
                d = (base / sub).resolve()
                key = str(d)
                if key not in seen:
                    seen.add(key)
                    roots.append(d)
        return roots

    def list_debug_screenshots(self, limit: int = 48) -> list[dict[str, Any]]:
        """Return real debug/screenshot PNGs, newest first.

        Each item: {name, mtime, time, url}. ``url`` is served by the GUI HTTP
        server via ``/__shots__/<token>`` so large images are not base64-inlined.
        Works in both source and frozen (PyInstaller) modes because all paths
        are derived from the running process, never hard-coded.
        """
        found: list[tuple[float, Path]] = []
        seen: set[str] = set()
        for d in self._screenshot_roots():
            if not d.is_dir():
                continue
            for pattern in ("*.png", "*.jpg", "*.jpeg"):
                for path in d.glob(pattern):
                    rp = path.resolve()
                    key = str(rp)
                    if key in seen:
                        continue
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        continue
                    seen.add(key)
                    found.append((mtime, rp))
        found.sort(key=lambda t: t[0], reverse=True)
        found = found[: max(0, int(limit))]

        index: dict[str, Path] = {}
        out: list[dict[str, Any]] = []
        for mtime, rp in found:
            token = hashlib.sha1(str(rp).encode("utf-8")).hexdigest()[:16]
            index[token] = rp
            out.append(
                {
                    "name": rp.name,
                    "mtime": mtime,
                    "time": time.strftime("%H:%M:%S", time.localtime(mtime)),
                    "url": f"/__shots__/{token}",
                }
            )
        with self._shot_lock:
            self._shot_index = index
        return out

    def shot_path(self, token: str) -> Path | None:
        """Resolve a screenshot token to a safe absolute path, or None."""
        with self._shot_lock:
            path = self._shot_index.get(str(token))
        if path is None:
            return None
        try:
            rp = path.resolve()
        except OSError:
            return None
        roots = self._screenshot_roots()
        if not any(rp == r or r in rp.parents for r in roots):
            return None
        if not rp.is_file():
            return None
        return rp


def app_version() -> str:
    return __version__
