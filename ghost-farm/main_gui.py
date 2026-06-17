"""
main_gui.py - Project: Ghost Farm  (v2.0)
=========================================
Application shell + the one place threads meet the UI.

Architecture in one breath:
  * BotLogic runs on its OWN daemon thread and pushes dict-messages onto a Queue.
  * The GUI NEVER reads bot state directly. Instead it drains that Queue every
    100 ms on the Tk main thread (`_drain_queue`) and updates widgets there.
  * Result: the window stays responsive no matter what the bot is doing, and
    there is exactly one threading rule to remember -> "only the drain touches widgets."

Run:  python main_gui.py
Deps: customtkinter (required), pystray + pillow (optional, for tray).
"""

import queue
import customtkinter as ctk

from bot_logic import BotLogic
from ui_components import Sidebar, Dashboard, Settings, BG, CYAN, SURFACE, BORDER, MUTED, TEXT

# Tray support is optional - the app must run fine without it.
try:
    import pystray
    from PIL import Image, ImageDraw
    _HAS_TRAY = True
except Exception:
    _HAS_TRAY = False


class FarmBotApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Project: Ghost Farm - v2.0")
        self.geometry("1100x700")
        self.minsize(900, 560)
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        self.configure(fg_color=BG)

        # -- The engineer's grid: fixed rail (col 0), fluid stage (col 1) --
        self.grid_columnconfigure(0, weight=0)   # sidebar - fixed width
        self.grid_columnconfigure(1, weight=1)   # main view - absorbs resize
        self.grid_rowconfigure(0, weight=1)

        # -- Thread bridge: bot -> queue -> GUI --
        self.q: "queue.Queue" = queue.Queue()
        self.bot = BotLogic(self.q)

        # -- Left rail --
        self.sidebar = Sidebar(self, on_start=self.start_bot, on_stop=self.stop_bot)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # -- Main stage: tabbed (Dashboard / Settings) --
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(
            self.main_frame, corner_radius=6, fg_color=SURFACE,
            border_width=1, border_color=BORDER,
            segmented_button_fg_color=BG,
            segmented_button_selected_color=CYAN,
            segmented_button_selected_hover_color="#33E0FF",
            segmented_button_unselected_color=SURFACE,
            text_color=TEXT,
        )
        self.tabs.grid(row=0, column=0, sticky="nsew")
        tab_dash = self.tabs.add("  DASHBOARD  ")
        tab_set = self.tabs.add("  SETTINGS  ")
        for t in (tab_dash, tab_set):
            t.grid_columnconfigure(0, weight=1)
            t.grid_rowconfigure(0, weight=1)

        self.dashboard = Dashboard(tab_dash)
        self.dashboard.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        self.settings = Settings(tab_set)
        self.settings.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.settings.on_save(self._on_settings_saved)

        # -- Tray + clean shutdown --
        self._tray_icon = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.dashboard.append_log("Ghost Farm online. Awaiting orders.", "info")
        if not _HAS_TRAY:
            self.dashboard.append_log(
                "Tray disabled (install pystray + pillow to enable).", "warning")

        # Kick off the 100 ms UI pump.
        self.after(100, self._drain_queue)

    # -- Control callbacks (fired by the sidebar button) ----------------
    def start_bot(self):
        self.bot.start_bot()

    def stop_bot(self):
        self.bot.stop_bot()

    def _on_settings_saved(self, cfg: dict):
        self.dashboard.append_log(
            f"Loadout saved -> strategy={cfg['strategy']} | priority={cfg['priority']}",
            "success")

    # -- The single thread-safe bridge ---------------------------------
    def _drain_queue(self):
        """Pull every pending message and apply it to the widgets. Runs on the
        Tk thread, so widget calls here are always safe."""
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg.get("kind")
                if kind == "log":
                    self.dashboard.append_log(msg["text"], msg.get("level", "info"))
                elif kind == "loot":
                    self.dashboard.set_loot(msg["gold"], msg["elixir"], msg["dark"])
                elif kind == "status":
                    self.sidebar.set_status(msg["running"])
                elif kind == "timer":
                    self.dashboard.set_timer(msg["seconds"])
        except queue.Empty:
            pass
        # Re-arm. 100 ms = imperceptible latency, negligible CPU.
        self.after(100, self._drain_queue)

    # -- Tray / lifecycle ----------------------------------------------
    def _on_close(self):
        """Closing the window minimizes to tray when available; otherwise quits."""
        if _HAS_TRAY:
            self.withdraw()
            self._show_tray()
        else:
            self._quit()

    def _make_tray_image(self):
        # Procedurally drawn 64x64 icon: cyan ring on the dark base. No asset file.
        img = Image.new("RGB", (64, 64), BG)
        d = ImageDraw.Draw(img)
        d.ellipse((10, 10, 54, 54), outline=CYAN, width=4)
        d.ellipse((26, 26, 38, 38), fill=CYAN)
        return img

    def _show_tray(self):
        if self._tray_icon is not None:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Show", self._restore, default=True),
            pystray.MenuItem("Quit", self._quit),
        )
        self._tray_icon = pystray.Icon("ghost_farm", self._make_tray_image(),
                                       "Ghost Farm", menu)
        # run_detached spins pystray's own thread; never blocks Tk's mainloop.
        self._tray_icon.run_detached()

    def _restore(self, *_):
        # Tray callbacks fire off-thread -> marshal back onto the Tk thread.
        self.after(0, self._do_restore)

    def _do_restore(self):
        if self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None
        self.deiconify()
        self.lift()

    def _quit(self, *_):
        self.bot.stop_bot()
        if self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None
        self.after(0, self.destroy)


if __name__ == "__main__":
    FarmBotApp().mainloop()
