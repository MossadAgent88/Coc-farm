from __future__ import annotations

import atexit
import functools
import json
import os
import socket
import sys
import threading
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from bot_controller import BotController, app_version


BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web_gui"


def _run_bot_cli() -> None:
    """Run backend commands when the frozen GUI exe starts itself with --bot."""
    args_after_flag = sys.argv[sys.argv.index("--bot") + 1 :]
    subcmd = args_after_flag[0] if args_after_flag else "loop"

    if subcmd == "loop":
        from cocbot.loop import run_loop

        run_loop()
    elif subcmd == "manual_attack":
        from cocbot.loop import run_manual_attack

        side = args_after_flag[1] if len(args_after_flag) > 1 else "Random"
        run_manual_attack(side)
    elif subcmd == "detect_loot":
        from cocbot.loop import run_detect_loot

        run_detect_loot()
    elif subcmd == "screenshot":
        from cocbot.loop import run_screenshot_test

        run_screenshot_test()
    elif subcmd in ("home", "open_game"):
        from loguru import logger

        from cocbot.actions import ensure_coc_running, go_home, open_game

        if subcmd == "open_game":
            open_game()
        else:
            ensure_coc_running()
            if go_home():
                logger.info("Returned to home village")
            else:
                logger.error("Could not return to home village")
                sys.exit(1)
    elif subcmd == "collect_resources":
        from loguru import logger

        logger.warning("Collect resources: not implemented yet.")
    else:
        from loguru import logger

        logger.error(f"Unknown --bot subcommand: {subcmd}")
        sys.exit(2)


if "--bot" in sys.argv:
    _run_bot_cli()
    raise SystemExit


class WebApi:
    def __init__(self) -> None:
        self.controller = BotController(APP_DIR)

    def initial_state(self) -> dict[str, Any]:
        return {
            "version": app_version(),
            "settings": self.controller.load_settings(),
            "bases": self.controller.bases.load(),
            "armies": self.controller.armies.load(),
        }

    def drain_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        while True:
            try:
                events.append(self.controller.events.get_nowait())
            except Exception:
                break
        return events

    def start_bot(self, settings: dict[str, Any]) -> dict[str, Any]:
        self.controller.start(settings)
        return {"ok": True}

    def stop_bot(self) -> dict[str, Any]:
        self.controller.stop()
        return {"ok": True}

    def save_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        self.controller.save_settings(settings)
        return {"ok": True}

    def load_settings(self) -> dict[str, Any]:
        return {"ok": True, "settings": self.controller.reload_settings()}

    def default_settings(self) -> dict[str, Any]:
        from cocbot.config import BotConfig

        return {"ok": True, "settings": asdict(BotConfig())}

    def reload_config(self) -> dict[str, Any]:
        return self.load_settings()

    def check_update(self) -> dict[str, Any]:
        self.controller.check_update()
        return {"ok": True}

    def run_tool(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else None
        if name == "manual_attack":
            side = str(payload.get("side") or "Random")
            self.controller.run_tool("manual_attack", f"Manual attack ({side})", side, settings=settings)
        elif name == "detect_loot":
            self.controller.run_tool("detect_loot", "Detecting loot", settings=settings)
        elif name == "screenshot":
            self.controller.run_tool("screenshot", "Taking screenshot", settings=settings)
        elif name == "return_home":
            self.controller.run_tool("home", "Returning home", settings=settings)
        elif name == "open_game":
            self.controller.run_tool("open_game", "Opening game", settings=settings)
        else:
            self.controller.emit("log", text=f"{name}: Not implemented yet", level="warning")
        return {"ok": True}

    def save_library(self, kind: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        store = self.controller.bases if kind == "bases" else self.controller.armies
        store.save(items)
        return {"ok": True}

    def open_link(self, link: str) -> dict[str, Any]:
        self.controller.open_link(link)
        return {"ok": True}

    def copy_link(self, link: str) -> dict[str, Any]:
        self.controller.copy_link(link)
        return {"ok": True}

    # ---- Base Copier (safe dry-run only — never live) ----

    def copier_dry_run(self) -> dict[str, Any]:
        """Run the base-copier planner on the sample layout (no ADB, no --live)."""
        from cocbot.base_copier_bridge import dry_run_sample

        result = dry_run_sample()
        if not result.get("ok"):
            msg = result.get("error", "dry-run failed")
            self.controller.emit("log", text=f"Base Copier: {msg}", level="error")
            return result
        if result.get("stale"):
            self.controller.emit(
                "log",
                text=(
                    "Base Copier: using a synthetic sample layout (no real "
                    "detector output found). Run the detector first for a real plan."
                ),
                level="warning",
            )
        plan = result.get("plan", "")
        for line in plan.splitlines():
            self.controller.emit("log", text=f"[copier] {line}", level="info")
        self.controller.emit(
            "log",
            text=(
                f"Base Copier dry-run complete: {result.get('action_count', 0)} "
                "action(s) planned. No emulator was touched."
            ),
            level="success",
        )
        return result

    def copier_open_folder(self) -> dict[str, Any]:
        """Open the coc-base-copier folder in the OS file explorer."""
        import webbrowser

        from cocbot.base_copier_bridge import base_copier_root

        root = base_copier_root()
        if root is None:
            self.controller.emit("log", text="Base Copier folder not found.", level="warning")
            return {"ok": False, "error": "coc-base-copier folder not found"}
        try:
            webbrowser.open(root.as_uri())
            self.controller.emit("log", text=f"Opened Base Copier folder: {root}", level="info")
        except Exception as exc:
            self.controller.emit("log", text=f"Could not open folder: {exc}", level="error")
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def copier_open_docs(self) -> dict[str, Any]:
        """Open the Base Copier README / docs."""
        import webbrowser

        from cocbot.base_copier_bridge import base_copier_root

        root = base_copier_root()
        if root is None:
            self.controller.emit("log", text="Base Copier docs not found.", level="warning")
            return {"ok": False, "error": "coc-base-copier folder not found"}
        readme = root / "README.md"
        schema = root / "docs" / "layout-schema.md"
        target = readme if readme.exists() else schema if schema.exists() else root
        try:
            webbrowser.open(target.as_uri())
            self.controller.emit("log", text=f"Opened Base Copier docs: {target.name}", level="info")
        except Exception as exc:
            self.controller.emit("log", text=f"Could not open docs: {exc}", level="error")
            return {"ok": False, "error": str(exc)}
        return {"ok": True}


BRIDGE_METHODS = (
    "initial_state",
    "drain_events",
    "start_bot",
    "stop_bot",
    "save_settings",
    "load_settings",
    "default_settings",
    "reload_config",
    "check_update",
    "run_tool",
    "save_library",
    "open_link",
    "copy_link",
    "copier_dry_run",
    "copier_open_folder",
    "copier_open_docs",
)


def _bridge_script() -> str:
    methods = json.dumps(BRIDGE_METHODS)
    return f"""
<script>
(() => {{
  const methods = {methods};
  async function callPython(name, args) {{
    const response = await fetch(`/api/${{encodeURIComponent(name)}}`, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ args }})
    }});
    const text = await response.text();
    const data = text ? JSON.parse(text) : null;
    if (!response.ok) {{
      throw new Error((data && data.error) || `Python bridge error ${{response.status}}`);
    }}
    return data;
  }}
  const api = {{}};
  methods.forEach(name => {{
    api[name] = (...args) => callPython(name, args);
  }});
  window.pywebview = {{ api }};
}})();
</script>
"""


class QuietHandler(SimpleHTTPRequestHandler):
    api: WebApi | None = None

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if unquote(parsed.path).endswith(".html"):
            self._send_html_with_bridge(parsed.path)
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_error(404)
            return

        method_name = unquote(parsed.path.removeprefix("/api/"))
        if method_name not in BRIDGE_METHODS or self.api is None:
            self._send_json({"error": f"Unknown API method: {method_name}"}, status=404)
            return

        try:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw) if raw else {}
            args = payload.get("args", [])
            if not isinstance(args, list):
                raise ValueError("API args must be a list")
            result = getattr(self.api, method_name)(*args)
            self._send_json(result)
        except Exception as exc:
            try:
                self.api.controller.emit(
                    "log", text=f"GUI bridge error in {method_name}: {exc}", level="error"
                )
            except Exception:
                pass
            self._send_json({"error": str(exc)}, status=500)

    def _send_html_with_bridge(self, request_path: str) -> None:
        file_path = (WEB_DIR / unquote(request_path).lstrip("/")).resolve()
        if WEB_DIR.resolve() not in file_path.parents and file_path != WEB_DIR.resolve():
            self.send_error(403)
            return
        if not file_path.exists():
            self.send_error(404)
            return

        html = file_path.read_text(encoding="utf-8")
        script = _bridge_script()
        if "</head>" in html:
            html = html.replace("</head>", f"{script}\n</head>", 1)
        else:
            html = f"{script}\n{html}"
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start_server(api: WebApi) -> tuple[ThreadingHTTPServer, str]:
    port = _free_port()
    class ApiHandler(QuietHandler):
        pass

    ApiHandler.api = api
    handler = functools.partial(ApiHandler, directory=str(WEB_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    atexit.register(server.shutdown)
    return server, f"http://127.0.0.1:{port}/CoC%20Farm%20Bot.dc.html"


def main() -> None:
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError as exc:
        raise SystemExit(
            "PySide6 with QtWebEngine is required for the uploaded HTML GUI. "
            "Run: pip install -r requirements.txt"
        ) from exc

    if not WEB_DIR.exists():
        raise SystemExit(f"Missing HTML GUI folder: {WEB_DIR}")

    api = WebApi()
    _server, url = _start_server(api)

    app = QApplication(sys.argv)
    window = QWebEngineView()
    window.setWindowTitle(f"Clash of Clans Farm Bot - v{app_version()}")
    icon_path = BASE_DIR / "templates" / "logo.ico"
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.resize(1280, 760)
    window.setMinimumSize(1040, 640)
    window.load(QUrl(url))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
