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


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start_server() -> tuple[ThreadingHTTPServer, str]:
    port = _free_port()
    handler = functools.partial(QuietHandler, directory=str(WEB_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    atexit.register(server.shutdown)
    return server, f"http://127.0.0.1:{port}/CoC%20Farm%20Bot.dc.html"


def main() -> None:
    try:
        import webview
    except ImportError as exc:
        raise SystemExit(
            "pywebview is required for the uploaded HTML GUI. "
            "Run: pip install -r requirements.txt"
        ) from exc

    if not WEB_DIR.exists():
        raise SystemExit(f"Missing HTML GUI folder: {WEB_DIR}")

    _server, url = _start_server()
    api = WebApi()
    window = webview.create_window(
        f"Clash of Clans Farm Bot - v{app_version()}",
        url,
        js_api=api,
        width=1280,
        height=760,
        min_size=(1040, 640),
    )
    webview.start(debug=False)


if __name__ == "__main__":
    main()
