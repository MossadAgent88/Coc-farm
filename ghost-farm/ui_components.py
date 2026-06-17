"""
ui_components.py - Project: Ghost Farm
======================================
All visual building blocks live here, kept out of main_gui.py so the app
loop stays readable. Three public frames:

    Sidebar    - static rail: logo, status lamp, the Start/Stop "Army Camp" button
    Dashboard  - loot counters, "next attack" timer, live color-coded console
    Settings   - grid-based config form (credentials, strategy, troop priority)

Design language ("Cyber-Farm"): flat surfaces, hairline borders, neon accents.
Tkinter can't do true CSS glow, so "neon" = a saturated border on a dark
surface plus brighter hover states. Corner radius is kept at a tasteful 6px.
"""

import customtkinter as ctk

# -- Palette (single source of truth for the whole app) ----------------
BG = "#0D1117"        # window background (GitHub-dark base)
SURFACE = "#161B22"   # raised panels / cards
SURFACE_2 = "#1C2333" # inputs / console
BORDER = "#30363D"    # hairline separators
CYAN = "#00D4FF"      # primary accent: activity / success / online
GOLD = "#FFD700"      # loot + statistics
RED = "#FF4444"       # errors / offline / stop
GREEN = "#3FB950"     # "attack successful"
YELLOW = "#E3B341"    # "training" / warnings
TEXT = "#E6EDF3"      # primary text
MUTED = "#8B949E"     # secondary text

FONT = "Segoe UI"
MONO = "Consolas"


class Sidebar(ctk.CTkFrame):
    """Static command rail. Owns the only two controls that must always be
    reachable: the status lamp and the Start/Stop button."""

    def __init__(self, master, on_start, on_stop):
        # corner_radius=0 so the rail reads as a structural panel, not a card.
        super().__init__(master, width=240, corner_radius=0, fg_color=SURFACE,
                         border_width=0)
        self._on_start = on_start
        self._on_stop = on_stop
        self._running = False
        self.grid_propagate(False)            # lock the 240px width
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)   # spacer row pushes button down

        # -- Brand block --
        ctk.CTkLabel(self, text="GHOST FARM", font=(FONT, 22, "bold"),
                     text_color=CYAN).grid(row=0, column=0, padx=24, pady=(28, 0),
                                           sticky="w")
        ctk.CTkLabel(self, text="// tactical automation", font=(FONT, 12),
                     text_color=MUTED).grid(row=1, column=0, padx=24, pady=(0, 24),
                                            sticky="w")

        # -- Status lamp (dot + label), recolored live --
        status = ctk.CTkFrame(self, fg_color="transparent")
        status.grid(row=2, column=0, padx=24, pady=8, sticky="w")
        self._lamp = ctk.CTkLabel(status, text="●", font=(FONT, 16),
                                  text_color=RED)        # filled circle glyph
        self._lamp.grid(row=0, column=0, padx=(0, 8))
        self._status_lbl = ctk.CTkLabel(status, text="OFFLINE", font=(FONT, 13, "bold"),
                                        text_color=MUTED)
        self._status_lbl.grid(row=0, column=1)

        # -- The "Army Camp" master switch --
        self._btn = ctk.CTkButton(
            self, text="▶  START BOT", height=46, corner_radius=6,
            font=(FONT, 15, "bold"), fg_color=CYAN, text_color=BG,
            hover_color="#33E0FF", border_width=2, border_color=CYAN,
            command=self._toggle,
        )
        self._btn.grid(row=5, column=0, padx=20, pady=20, sticky="ew")

    def _toggle(self):
        # One button, two states - clearer than two buttons fighting for space.
        if self._running:
            self._on_stop()
        else:
            self._on_start()

    def set_status(self, running: bool):
        """Recolor the lamp + reskin the button. Called from the GUI thread
        only (main_gui marshals queue events onto it)."""
        self._running = running
        if running:
            self._lamp.configure(text_color=CYAN)
            self._status_lbl.configure(text="ONLINE", text_color=CYAN)
            self._btn.configure(text="■  STOP BOT", fg_color=RED,
                                hover_color="#FF6666", border_color=RED)
        else:
            self._lamp.configure(text_color=RED)
            self._status_lbl.configure(text="OFFLINE", text_color=MUTED)
            self._btn.configure(text="▶  START BOT", fg_color=CYAN,
                                hover_color="#33E0FF", border_color=CYAN)


def _stat_card(master, label, accent):
    """Factory for a single loot counter card. Returns (card, value_label)."""
    card = ctk.CTkFrame(master, corner_radius=6, fg_color=SURFACE,
                        border_width=1, border_color=BORDER)
    card.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(card, text=label.upper(), font=(FONT, 11, "bold"),
                 text_color=MUTED).grid(row=0, column=0, padx=16, pady=(12, 0),
                                        sticky="w")
    value = ctk.CTkLabel(card, text="0", font=(MONO, 24, "bold"), text_color=accent)
    value.grid(row=1, column=0, padx=16, pady=(0, 14), sticky="w")
    return card, value


class Dashboard(ctk.CTkFrame):
    """Loot counters + countdown + live console. The console is the heartbeat:
    read-only, auto-scrolling, and color-coded per message level."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure((0, 1, 2), weight=1)
        self.grid_rowconfigure(2, weight=1)   # console row stretches

        # -- Row 0: loot stat cards --
        self._cards = {}
        for col, (key, label, accent) in enumerate([
            ("gold", "Gold", GOLD),
            ("elixir", "Elixir", "#D26BFF"),
            ("dark", "Dark Elixir", CYAN),
        ]):
            card, val = _stat_card(self, label, accent)
            pad = (0, 8) if col < 2 else (0, 0)
            card.grid(row=0, column=col, sticky="ew", padx=pad)
            self._cards[key] = val

        # -- Row 1: "next attack" timer banner --
        timer_bar = ctk.CTkFrame(self, corner_radius=6, fg_color=SURFACE,
                                 border_width=1, border_color=BORDER)
        timer_bar.grid(row=1, column=0, columnspan=3, sticky="ew", pady=12)
        timer_bar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(timer_bar, text="NEXT ATTACK IN", font=(FONT, 12, "bold"),
                     text_color=MUTED).grid(row=0, column=0, padx=16, pady=12)
        self._timer = ctk.CTkLabel(timer_bar, text="--:--", font=(MONO, 20, "bold"),
                                   text_color=CYAN)
        self._timer.grid(row=0, column=1, padx=16, pady=12, sticky="e")

        # -- Row 2: console --
        ctk.CTkLabel(self, text="CONSOLE", font=(FONT, 12, "bold"),
                     text_color=MUTED).grid(row=1, column=0, sticky="sw", padx=2)
        self._console = ctk.CTkTextbox(
            self, corner_radius=6, fg_color=SURFACE_2, border_width=1,
            border_color=BORDER, font=(MONO, 13), text_color=TEXT, wrap="word",
        )
        self._console.grid(row=2, column=0, columnspan=3, sticky="nsew")
        # Per-level colors. CTkTextbox proxies tag_config to the inner Text.
        self._console.tag_config("success", foreground=GREEN)
        self._console.tag_config("info", foreground=CYAN)
        self._console.tag_config("warning", foreground=YELLOW)
        self._console.tag_config("error", foreground=RED)
        self._console.tag_config("time", foreground=MUTED)
        self._console.configure(state="disabled")   # read-only

    def append_log(self, text: str, level: str = "info"):
        import time as _t
        stamp = _t.strftime("%H:%M:%S")
        self._console.configure(state="normal")
        self._console.insert("end", f"[{stamp}] ", "time")
        self._console.insert("end", text + "\n", level if level else "info")
        self._console.see("end")                     # auto-scroll to newest
        self._console.configure(state="disabled")

    def set_loot(self, gold: int, elixir: int, dark: int):
        self._cards["gold"].configure(text=f"{gold:,}")
        self._cards["elixir"].configure(text=f"{elixir:,}")
        self._cards["dark"].configure(text=f"{dark:,}")

    def set_timer(self, seconds: int):
        if seconds <= 0:
            self._timer.configure(text="--:--", text_color=MUTED)
        else:
            self._timer.configure(text=f"{seconds // 60:02d}:{seconds % 60:02d}",
                                  text_color=CYAN)


class Settings(ctk.CTkFrame):
    """Grid-based config form. Pure UI here (mock) - read values with
    get_settings(). Wire these to your real config when ready."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)

        form = ctk.CTkFrame(self, corner_radius=6, fg_color=SURFACE,
                            border_width=1, border_color=BORDER)
        form.grid(row=0, column=0, sticky="new")
        form.grid_columnconfigure(1, weight=1)

        def _row(r, label, widget):
            ctk.CTkLabel(form, text=label, font=(FONT, 13), text_color=TEXT,
                         anchor="w").grid(row=r, column=0, padx=(20, 12),
                                          pady=12, sticky="w")
            widget.grid(row=r, column=1, padx=(0, 20), pady=12, sticky="ew")

        ctk.CTkLabel(form, text="LOADOUT CONFIG", font=(FONT, 14, "bold"),
                     text_color=CYAN).grid(row=0, column=0, columnspan=2,
                                           padx=20, pady=(18, 4), sticky="w")

        self.user = ctk.CTkEntry(form, placeholder_text="account email",
                                 border_color=BORDER, fg_color=SURFACE_2)
        _row(1, "Account", self.user)

        self.pw = ctk.CTkEntry(form, placeholder_text="password", show="•",
                               border_color=BORDER, fg_color=SURFACE_2)
        _row(2, "Password", self.pw)

        self.strategy = ctk.CTkOptionMenu(
            form, values=["Edrag Spam", "Event Dump", "Queen Charge", "Super Archers"],
            fg_color=SURFACE_2, button_color=CYAN, button_hover_color="#33E0FF",
            text_color=TEXT,
        )
        _row(3, "Attack Strategy", self.strategy)

        self.priority = ctk.CTkOptionMenu(
            form, values=["Loot (Gold/Elixir)", "Dark Elixir", "Trophies",
                          "Event Points"],
            fg_color=SURFACE_2, button_color=CYAN, button_hover_color="#33E0FF",
            text_color=TEXT,
        )
        _row(4, "Troop Priority", self.priority)

        self.min_loot = ctk.CTkEntry(form, placeholder_text="1500000",
                                     border_color=BORDER, fg_color=SURFACE_2)
        _row(5, "Min Loot Threshold", self.min_loot)

        ctk.CTkButton(form, text="SAVE LOADOUT", height=40, corner_radius=6,
                      font=(FONT, 13, "bold"), fg_color=CYAN, text_color=BG,
                      hover_color="#33E0FF", command=self._save
                      ).grid(row=6, column=0, columnspan=2, padx=20, pady=20,
                             sticky="ew")

        self._saved_cb = None

    def on_save(self, callback):
        self._saved_cb = callback

    def _save(self):
        if self._saved_cb:
            self._saved_cb(self.get_settings())

    def get_settings(self) -> dict:
        return {
            "account": self.user.get(),
            "password_set": bool(self.pw.get()),   # never echo the password back
            "strategy": self.strategy.get(),
            "priority": self.priority.get(),
            "min_loot": self.min_loot.get() or "1500000",
        }
