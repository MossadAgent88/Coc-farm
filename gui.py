import atexit
import json
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageTk

from cocbot import __version__

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_SETTINGS_FILE = Path.cwd() / "settings.json"

DEFAULTS = {
    "donate": True,
    "log_file": False,
    "random_events": True,
    "fatigue": True,
    "attack_side": "Random",
    "min_loot": "1500000",
    "min_remaining": "100000",
    "min_gold": "0",
    "min_elixir": "0",
    "min_de": "0",
    "max_search": "20",
    "max_cycles": "0",
    "reconnect_wait": "300",
    "break_every_min": "60",
    "break_every_max": "120",
    "break_dur_min": "4",
    "break_dur_max": "16",
    "skip_min": "0",
    "skip_max": "6",
    "skip_long_min": "5",
    "skip_long_max": "15",
    "skip_long_chance": "0.15",
    "event_every_min": "3",
    "event_every_max": "10",
    "post_attack_min": "3",
    "post_attack_max": "20",
    "fatigue_ramp": "120",
    "fatigue_max": "2.0",
    "splash_enabled": False,
    "debug_screenshots": False,
    "dump_mode": False,
    "army_preset": "broom_witch",
    "broom_witch_slot_xs": "250,330,410,490",
}

ACCENT = "#4488ff"
GREEN = "#00cc66"
RED = "#ff4444"
YELLOW = "#ffaa00"

_FROZEN = getattr(sys, "frozen", False)
if _FROZEN:
    _BASE_DIR = Path(sys._MEIPASS)
else:
    _BASE_DIR = Path(__file__).parent

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_LOOT_RE = re.compile(r"(G=)([\d,]+)( E=)([\d,]+)( DE=)([\d,]+)")
_EVENT_PREFIX = "__EVENT__ "


def _load_settings():
    if _SETTINGS_FILE.exists():
        try:
            return json.loads(_SETTINGS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_settings():
    data = {}
    for key, var in _SETTING_VARS.items():
        data[key] = var.get()
    _SETTINGS_FILE.write_text(json.dumps(data, indent=2))


# ── Main window ──
root = ctk.CTk()
root.title(f"Clash of Clans Farm Bot — v{__version__}")
root.geometry("960x680")
root.resizable(True, True)

_icon_path = Path(__file__).parent / "templates" / "logo.jpeg"
if _icon_path.exists():
    _icon_img = Image.open(_icon_path)
    _icon_photo = ImageTk.PhotoImage(_icon_img)
    _ico_path = Path(__file__).parent / "templates" / "logo.ico"
    if not _ico_path.exists():
        _icon_img.save(str(_ico_path), format="ICO", sizes=[(32, 32), (48, 48)])
    root.iconbitmap(str(_ico_path))
    root.iconphoto(True, _icon_photo)

bot_process = None
_start_time = None
_stop_in_progress = False


# ── Bot control ──
def _spawn_subprocess(subcmd: str, status_text: str, *extra_args: str):
    """Spawn a bot subprocess with the given subcommand. Output streams to log.

    `subcmd` is one of: "loop", "manual_attack", "detect_loot". Extra args
    are passed positionally after the subcmd. Reuses the global bot_process
    slot so Start/Stop/Manual buttons all share the same mutex.
    """
    global bot_process, _start_time
    if bot_process and bot_process.poll() is None:
        status_label.configure(text="Bot already running", text_color=YELLOW)
        return

    log_output.configure(state="normal")
    log_output.delete("1.0", tk.END)
    log_output.configure(state="disabled")

    _save_settings()

    if _FROZEN:
        cmd = [sys.executable, "--bot", subcmd, *extra_args]
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        venv_py = str(_BASE_DIR / ".venv" / "Scripts" / "python.exe")
        cmd = [venv_py, "-u", "-m", "cocbot", subcmd, *extra_args]
        flags = subprocess.CREATE_NEW_PROCESS_GROUP

    bot_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    _start_time = time.time()
    status_label.configure(
        text=f"{status_text} (PID {bot_process.pid})",
        text_color=GREEN,
    )
    start_btn.configure(state="disabled")
    stop_btn.configure(state="normal")

    threading.Thread(target=_read_output, daemon=True).start()


def start_bot():
    _spawn_subprocess("loop", "Farming...")


def manual_detect_loot():
    _spawn_subprocess("detect_loot", "Detecting loot...")


def manual_attack():
    side = manual_side_var.get()
    _spawn_subprocess("manual_attack", f"Manual attack ({side})...", side)


def _read_output():
    for line in bot_process.stdout:
        text = line.decode("utf-8", errors="replace").rstrip("\n\r")
        text = _ANSI_RE.sub("", text)
        if text.startswith(_EVENT_PREFIX):
            payload = text[len(_EVENT_PREFIX):]
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                root.after(0, _append_log, text)
                continue
            root.after(0, _handle_event, event)
            continue
        root.after(0, _append_log, text)
    root.after(0, _on_bot_exit)


def _handle_event(event):
    """Handle a structured event from the bot subprocess.

    Schema documented in cocbot/loop.py docstring.
    """
    kind = event.get("type")
    if kind == "cycle_start":
        cycle_val.configure(text=str(event.get("n", "")))
    elif kind == "step":
        step_val.configure(text=event.get("label", ""))
    elif kind == "version":
        bot_version = event.get("version", "?")
        if bot_version != __version__:
            # GUI was built against a different version than the running bot
            version_label.configure(
                text=f"GUI v{__version__} / bot v{bot_version}",
                text_color="#e08a2a",
            )


def _append_log(text):
    log_output.configure(state="normal")

    tag = None
    if "GOOD LOOT" in text:
        tag = "total"
    elif "surrendering early" in text.lower():
        tag = "warning"
    elif "ERROR" in text:
        tag = "error"
    elif "Step " in text and ": " in text:
        tag = "step"

    if tag:
        log_output.insert(tk.END, text + "\n", tag)
    elif "Loot: G=" in text and (
        "Available Loot:" in text or "Remaining Loot:" in text
    ):
        m = _LOOT_RE.search(text)
        if m:
            prefix = text[: m.start()]
            log_output.insert(tk.END, prefix, "loot_line")
            log_output.insert(tk.END, m.group(1), "loot_line")
            log_output.insert(tk.END, m.group(2), "gold_val")
            log_output.insert(tk.END, m.group(3), "loot_line")
            log_output.insert(tk.END, m.group(4), "elixir_val")
            log_output.insert(tk.END, m.group(5), "loot_line")
            log_output.insert(tk.END, m.group(6), "dark_val")
            log_output.insert(tk.END, text[m.end() :] + "\n", "loot_line")
        else:
            log_output.insert(tk.END, text + "\n")
    else:
        log_output.insert(tk.END, text + "\n")

    line_count = int(log_output.index("end-1c").split(".")[0])
    if line_count > 500:
        log_output.delete("1.0", f"{line_count - 500}.0")
    log_output.see(tk.END)
    log_output.configure(state="disabled")


def _on_bot_exit():
    global bot_process, _start_time
    if bot_process:
        bot_process = None
        _start_time = None
        status_label.configure(text="Bot idle", text_color=RED)
        start_btn.configure(state="normal")
        stop_btn.configure(state="disabled")


def _finish_stop_ui(proc=None, label="Bot stopped"):
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


# ── Helper: tooltip ──
def _tooltip(widget, tip_text):
    tip = None

    def _show(event):
        nonlocal tip
        tip = tk.Toplevel(widget)
        tip.wm_overrideredirect(True)
        tip.wm_attributes("-topmost", True)
        tip.wm_geometry(f"+{event.x_root + 12}+{event.y_root - 8}")
        tk.Label(
            tip,
            text=tip_text,
            font=("Segoe UI", 12),
            fg="#ffffff",
            bg="#333355",
            relief=tk.SOLID,
            bd=1,
            padx=6,
            pady=4,
            wraplength=300,
            justify=tk.LEFT,
        ).pack()

    def _hide(event):
        nonlocal tip
        if tip:
            tip.destroy()
            tip = None

    widget.bind("<Enter>", _show)
    widget.bind("<Leave>", _hide)


def _help_icon(parent, tip_text):
    lbl = ctk.CTkLabel(
        parent,
        text="?",
        font=("Segoe UI", 10, "bold"),
        text_color="#6666aa",
        width=16,
        cursor="question_arrow",
    )
    _tooltip(lbl, tip_text)
    return lbl


# ── Helper: range entry (min-max pair) ──
def _range_entry(parent, label, var_min, var_max, unit, tip, width=50):
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(frame, text=label, font=("Segoe UI", 13)).pack(
        side="left", padx=(0, 4)
    )
    _help_icon(frame, tip).pack(side="left", padx=(0, 4))
    ctk.CTkEntry(
        frame,
        textvariable=var_min,
        width=width,
        font=("Consolas", 13),
        justify="center",
    ).pack(side="left", padx=1)
    ctk.CTkLabel(frame, text="-", font=("Consolas", 13)).pack(side="left")
    ctk.CTkEntry(
        frame,
        textvariable=var_max,
        width=width,
        font=("Consolas", 13),
        justify="center",
    ).pack(side="left", padx=1)
    ctk.CTkLabel(frame, text=unit, font=("Segoe UI", 12), text_color="#888888").pack(
        side="left", padx=(2, 0)
    )
    return frame


def _single_entry(parent, label, var, unit, tip, width=70):
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(frame, text=label, font=("Segoe UI", 13)).pack(
        side="left", padx=(0, 4)
    )
    _help_icon(frame, tip).pack(side="left", padx=(0, 4))
    ctk.CTkEntry(
        frame, textvariable=var, width=width, font=("Consolas", 13), justify="center"
    ).pack(side="left", padx=1)
    if unit:
        ctk.CTkLabel(
            frame, text=unit, font=("Segoe UI", 12), text_color="#888888"
        ).pack(side="left", padx=(2, 0))
    return frame


# ══════════════════════════════════════════════════════════════════
# TOP BAR — Logo, status, buttons
# ══════════════════════════════════════════════════════════════════
def _check_update():
    """Kick off a background check against GitHub for a newer release."""
    update_btn.configure(state="disabled", text="CHECKING…")
    threading.Thread(target=_check_update_worker, daemon=True).start()


def _check_update_worker():
    try:
        from cocbot.updater import check_for_update

        info = check_for_update()
        root.after(0, _update_result, info, None)
    except Exception as e:  # network errors, etc.
        root.after(0, _update_result, None, str(e))


def _update_result(info, error):
    update_btn.configure(state="normal", text="UPDATE")
    if error:
        status_label.configure(
            text="Update check failed (no internet?)", text_color=YELLOW
        )
        _append_log(f"Update check failed: {error}\n")
        return
    if not info:
        status_label.configure(text="Already up to date", text_color=GREEN)
        return

    from tkinter import messagebox

    ok = messagebox.askyesno(
        "Update available",
        f"Version {info['version']} is available.\n\n"
        "Download and install it now? The app will restart.",
    )
    if ok:
        _apply_update(info)


def _apply_update(info):
    status_label.configure(text=f"Downloading v{info['version']}…", text_color=YELLOW)
    update_btn.configure(state="disabled")

    def worker():
        try:
            from cocbot.updater import download_and_apply

            download_and_apply(info["url"])
            root.after(0, _request_close_after_update)
        except Exception as e:
            root.after(
                0,
                lambda: status_label.configure(
                    text="Update failed — see log", text_color=RED
                ),
            )
            root.after(0, lambda: _append_log(f"Update failed: {e}\n"))
            root.after(0, lambda: update_btn.configure(state="normal"))

    threading.Thread(target=worker, daemon=True).start()


top_frame = ctk.CTkFrame(root, fg_color="transparent")
top_frame.pack(fill="x", padx=16, pady=(12, 4))

_logo_path = Path(__file__).parent / "templates" / "logo.jpeg"
if _logo_path.exists():
    _logo_img = ctk.CTkImage(Image.open(_logo_path), size=(40, 40))
    ctk.CTkLabel(top_frame, image=_logo_img, text="").pack(side="left", padx=(0, 10))

status_label = ctk.CTkLabel(
    top_frame,
    text="Bot idle",
    font=("Segoe UI", 16, "bold"),
    text_color=RED,
)
status_label.pack(side="left")

version_label = ctk.CTkLabel(
    top_frame,
    text=f"v{__version__}",
    font=("Segoe UI", 10),
    text_color="#888888",
)
version_label.pack(side="left", padx=(8, 0))

stop_btn = ctk.CTkButton(
    top_frame,
    text="STOP",
    width=80,
    height=36,
    font=("Segoe UI", 12, "bold"),
    fg_color="#cc3333",
    hover_color="#aa2222",
    command=stop_bot,
    state="disabled",
)
stop_btn.pack(side="right", padx=4)

start_btn = ctk.CTkButton(
    top_frame,
    text="START",
    width=220,
    height=36,
    font=("Segoe UI", 12, "bold"),
    fg_color="#00aa55",
    hover_color="#008844",
    command=start_bot,
)
start_btn.pack(side="right", padx=4)

reset_btn = ctk.CTkButton(
    top_frame,
    text="DEFAULTS",
    width=90,
    height=36,
    font=("Segoe UI", 11),
    fg_color="#555577",
    hover_color="#444466",
    command=lambda: _reset_defaults(),
)
reset_btn.pack(side="right", padx=4)

update_btn = ctk.CTkButton(
    top_frame,
    text="UPDATE",
    width=90,
    height=36,
    font=("Segoe UI", 11),
    fg_color="#3a6ea5",
    hover_color="#2f5a86",
    command=lambda: _check_update(),
)
update_btn.pack(side="right", padx=4)


# ══════════════════════════════════════════════════════════════════
# INFO BAR — Uptime, cycles, step
# ══════════════════════════════════════════════════════════════════
info_frame = ctk.CTkFrame(root, corner_radius=8)
info_frame.pack(fill="x", padx=16, pady=(0, 4))

ctk.CTkLabel(
    info_frame, text="UPTIME", font=("Segoe UI", 10), text_color="#888888"
).pack(side="left", padx=(12, 4))
uptime_val = ctk.CTkLabel(
    info_frame, text="0:00:00", font=("Consolas", 14, "bold"), text_color=ACCENT
)
uptime_val.pack(side="left", padx=(0, 16))

ctk.CTkLabel(
    info_frame, text="CYCLES", font=("Segoe UI", 10), text_color="#888888"
).pack(side="left", padx=(0, 4))
cycle_val = ctk.CTkLabel(info_frame, text="0", font=("Consolas", 14, "bold"))
cycle_val.pack(side="left")
ctk.CTkLabel(info_frame, text="/", font=("Consolas", 12), text_color="#666666").pack(
    side="left"
)
max_cycles_var = ctk.StringVar(value="0")
ctk.CTkEntry(
    info_frame,
    textvariable=max_cycles_var,
    width=40,
    font=("Consolas", 12),
    justify="center",
).pack(side="left", padx=2)
_help_icon(info_frame, "Stop after this many cycles. 0 = run forever.").pack(
    side="left", padx=(0, 16)
)

ctk.CTkLabel(info_frame, text="STEP", font=("Segoe UI", 10), text_color="#888888").pack(
    side="left", padx=(0, 4)
)
step_val = ctk.CTkLabel(
    info_frame, text="Idle", font=("Segoe UI", 12), text_color=ACCENT
)
step_val.pack(side="left", padx=(0, 12))


def _update_uptime():
    if _start_time is not None:
        elapsed = int(time.time() - _start_time)
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        uptime_val.configure(text=f"{h}:{m:02d}:{s:02d}")
    root.after(1000, _update_uptime)


root.after(1000, _update_uptime)


# ══════════════════════════════════════════════════════════════════
# TABVIEW — Settings + Log
# ══════════════════════════════════════════════════════════════════
tabview = ctk.CTkTabview(root, corner_radius=10)
tabview.pack(fill="both", expand=True, padx=16, pady=(0, 12))
tabview.add("Settings")
tabview.add("Log")
tabview.add("Manual")
tabview.set("Log")

settings_tab = tabview.tab("Settings")
log_tab = tabview.tab("Log")
manual_tab = tabview.tab("Manual")


# ── Settings tab — scrollable ──
settings_scroll = ctk.CTkScrollableFrame(settings_tab, fg_color="transparent")
settings_scroll.pack(fill="both", expand=True)

ROW_PAD = 6  # consistent vertical spacing between rows
ITEM_PAD = 20  # consistent horizontal spacing between items
CARD_PAD_X = 16
CARD_PAD_Y = (10, 10)
ENTRY_W = 70


def _section(parent, title):
    ctk.CTkLabel(
        parent,
        text=title,
        font=("Segoe UI", 13, "bold"),
        text_color=ACCENT,
        anchor="w",
    ).pack(fill="x", padx=8, pady=(4, 2))
    card = ctk.CTkFrame(parent, corner_radius=10)
    card.pack(fill="x", padx=8, pady=(0, 2))
    return card


def _row(card, pad_y=ROW_PAD):
    r = ctk.CTkFrame(card, fg_color="transparent")
    r.pack(fill="x", padx=CARD_PAD_X, pady=pad_y)
    return r


# ── ATTACKING ──
atk_card = _section(settings_scroll, "ATTACKING")

r = _row(atk_card, pad_y=(10, ROW_PAD))
ctk.CTkLabel(r, text="Strategy", font=("Segoe UI", 13)).pack(side="left", padx=(0, 6))
_help_icon(r, "Which side to deploy troops. Random picks each attack.").pack(
    side="left", padx=(0, 8)
)
attack_side_var = ctk.StringVar(value="Random")
ctk.CTkSegmentedButton(
    r,
    values=["Random", "Top left", "Top right", "Bottom right"],
    variable=attack_side_var,
    font=("Segoe UI", 12),
).pack(side="left")


r = _row(atk_card)
ctk.CTkLabel(r, text="Army preset", font=("Segoe UI", 13)).pack(side="left", padx=(0, 6))
_help_icon(r, "Switches deployment composition without changing code.").pack(side="left", padx=(0, 8))
army_preset_var = ctk.StringVar(value="broom_witch")
ctk.CTkOptionMenu(r, values=["broom_witch", "electro_dragon"], variable=army_preset_var, width=170).pack(side="left")

r = _row(atk_card)
_single_entry(
    r,
    "Min total loot",
    min_loot_var := ctk.StringVar(value="1500000"),
    "",
    "Min gold+elixir+DE to attack. Ignored if resource filters set.",
    width=ENTRY_W,
).pack(side="left", padx=(0, ITEM_PAD))
_single_entry(
    r,
    "Min remaining",
    min_remaining_var := ctk.StringVar(value="100000"),
    "",
    "Surrender when remaining loot drops below this.",
    width=ENTRY_W,
).pack(side="left", padx=(0, ITEM_PAD))
_single_entry(
    r,
    "Max searches",
    max_search_var := ctk.StringVar(value="20"),
    "",
    "Give up after this many opponents.",
    width=50,
).pack(side="left")

r = _row(atk_card, pad_y=(ROW_PAD, 10))
_single_entry(
    r,
    "Min Gold",
    min_gold_var := ctk.StringVar(value="0"),
    "",
    "Min gold. >0 overrides total loot.",
    width=ENTRY_W,
).pack(side="left", padx=(0, ITEM_PAD))
_single_entry(
    r,
    "Min Elixir",
    min_elixir_var := ctk.StringVar(value="0"),
    "",
    "Min elixir. >0 overrides total loot.",
    width=ENTRY_W,
).pack(side="left", padx=(0, ITEM_PAD))
_single_entry(
    r,
    "Min DE",
    min_de_var := ctk.StringVar(value="0"),
    "",
    "Min dark elixir. E.g. 12000 to farm DE.",
    width=ENTRY_W,
).pack(side="left")

# ── GENERAL ──
gen_card = _section(settings_scroll, "GENERAL")

r = _row(gen_card, pad_y=CARD_PAD_Y)
donate_var = ctk.BooleanVar(value=True)
ctk.CTkSwitch(r, text="Donations", variable=donate_var, font=("Segoe UI", 13)).pack(
    side="left", padx=(0, 6)
)
_help_icon(r, "Fill clan castle donation requests between attacks.").pack(
    side="left", padx=(0, ITEM_PAD)
)
log_file_var = ctk.BooleanVar(value=False)
ctk.CTkSwitch(r, text="Log file", variable=log_file_var, font=("Segoe UI", 13)).pack(
    side="left", padx=(0, 6)
)
_help_icon(r, "Save bot output to a timestamped log file.").pack(
    side="left", padx=(0, ITEM_PAD)
)
_single_entry(
    r,
    "Reconnect",
    reconnect_wait_var := ctk.StringVar(value="300"),
    "s",
    "Seconds to wait before reconnecting.",
    width=50,
).pack(side="left", padx=(0, ITEM_PAD))
splash_var = ctk.BooleanVar(value=False)
ctk.CTkSwitch(
    r,
    text="Splash disabled",
    variable=splash_var,
    font=("Segoe UI", 13),
).pack(side="left", padx=(0, 6))
_help_icon(r, "Startup banner/GIF is disabled for fast launch.").pack(
    side="left",
    padx=(0, ITEM_PAD),
)
debug_screenshots_var = ctk.BooleanVar(value=False)
ctk.CTkSwitch(
    r,
    text="Debug screenshots",
    variable=debug_screenshots_var,
    font=("Segoe UI", 13),
).pack(side="left", padx=(0, 6))
_help_icon(
    r,
    "Save annotated screenshots per step to debug/runtime/.",
).pack(side="left")

dump_mode_var = ctk.BooleanVar(value=False)
ctk.CTkSwitch(
    r,
    text="Event dump",
    variable=dump_mode_var,
    font=("Segoe UI", 13),
).pack(side="left", padx=(12, 6))
_help_icon(
    r,
    "Event farming: skip loot search and dump the WHOLE army on each base to "
    "burn troops for event points. Works with any army (no troop images needed).",
).pack(side="left")

# ── ANTI-DETECTION ──
ad_card = _section(settings_scroll, "ANTI-DETECTION")

r = _row(ad_card, pad_y=(10, ROW_PAD))
_range_entry(
    r,
    "Break every",
    break_every_min_var := ctk.StringVar(value="60"),
    break_every_max_var := ctk.StringVar(value="120"),
    "min",
    "Take a break every X-Y minutes.",
).pack(side="left", padx=(0, ITEM_PAD))
_range_entry(
    r,
    "Duration",
    break_dur_min_var := ctk.StringVar(value="4"),
    break_dur_max_var := ctk.StringVar(value="16"),
    "min",
    "How long each break lasts.",
).pack(side="left")

r = _row(ad_card)
_range_entry(
    r,
    "Search skip",
    skip_min_var := ctk.StringVar(value="0"),
    skip_max_var := ctk.StringVar(value="6"),
    "s",
    "Delay before hitting Next on a bad base.",
).pack(side="left", padx=(0, ITEM_PAD))
_range_entry(
    r,
    "Long skip",
    skip_long_min_var := ctk.StringVar(value="5"),
    skip_long_max_var := ctk.StringVar(value="15"),
    "s",
    "Occasional longer pause, like reading the base.",
).pack(side="left", padx=(0, ITEM_PAD))
_single_entry(
    r,
    "Long chance",
    skip_long_chance_var := ctk.StringVar(value="0.15"),
    "",
    "Probability (0-1) of long skip.",
    width=50,
).pack(side="left")

r = _row(ad_card)
random_events_var = ctk.BooleanVar(value=True)
ctk.CTkSwitch(
    r, text="Random events", variable=random_events_var, font=("Segoe UI", 13)
).pack(side="left", padx=(0, 6))
_help_icon(r, "Randomly open chat, profile, etc. to look human.").pack(
    side="left", padx=(0, ITEM_PAD)
)
_range_entry(
    r,
    "Every",
    event_every_min_var := ctk.StringVar(value="3"),
    event_every_max_var := ctk.StringVar(value="10"),
    "cycles",
    "Trigger a random event every X-Y cycles.",
).pack(side="left", padx=(0, ITEM_PAD))
_range_entry(
    r,
    "Post delay",
    post_attack_min_var := ctk.StringVar(value="3"),
    post_attack_max_var := ctk.StringVar(value="20"),
    "s",
    "Wait after each attack before next cycle.",
).pack(side="left")

r = _row(ad_card, pad_y=(ROW_PAD, 10))
fatigue_var = ctk.BooleanVar(value=True)
ctk.CTkSwitch(
    r, text="Session fatigue", variable=fatigue_var, font=("Segoe UI", 13)
).pack(side="left", padx=(0, 6))
_help_icon(r, "Gradually slow down over time like a real player.").pack(
    side="left", padx=(0, ITEM_PAD)
)
_single_entry(
    r,
    "Ramp over",
    fatigue_ramp_var := ctk.StringVar(value="120"),
    "min",
    "Minutes until fatigue reaches max.",
    width=50,
).pack(side="left", padx=(0, ITEM_PAD))
_single_entry(
    r,
    "Max multiplier",
    fatigue_max_var := ctk.StringVar(value="2.0"),
    "x",
    "At peak fatigue, delays multiplied by this.",
    width=50,
).pack(side="left")


# ── Settings persistence ──
_SETTING_VARS = {
    "donate": donate_var,
    "log_file": log_file_var,
    "random_events": random_events_var,
    "fatigue": fatigue_var,
    "attack_side": attack_side_var,
    "army_preset": army_preset_var,
    "min_loot": min_loot_var,
    "min_remaining": min_remaining_var,
    "min_gold": min_gold_var,
    "min_elixir": min_elixir_var,
    "min_de": min_de_var,
    "max_search": max_search_var,
    "max_cycles": max_cycles_var,
    "reconnect_wait": reconnect_wait_var,
    "break_every_min": break_every_min_var,
    "break_every_max": break_every_max_var,
    "break_dur_min": break_dur_min_var,
    "break_dur_max": break_dur_max_var,
    "skip_min": skip_min_var,
    "skip_max": skip_max_var,
    "skip_long_min": skip_long_min_var,
    "skip_long_max": skip_long_max_var,
    "skip_long_chance": skip_long_chance_var,
    "event_every_min": event_every_min_var,
    "event_every_max": event_every_max_var,
    "post_attack_min": post_attack_min_var,
    "post_attack_max": post_attack_max_var,
    "fatigue_ramp": fatigue_ramp_var,
    "fatigue_max": fatigue_max_var,
    "splash_enabled": splash_var,
    "debug_screenshots": debug_screenshots_var,
    "dump_mode": dump_mode_var,
}


def _apply_settings(data):
    for key, var in _SETTING_VARS.items():
        if key in data:
            var.set(data[key])


def _reset_defaults():
    _apply_settings(DEFAULTS)
    _save_settings()


_apply_settings(_load_settings())


# ══════════════════════════════════════════════════════════════════
# MANUAL TAB — One-shot actions on whatever screen is currently showing
# ══════════════════════════════════════════════════════════════════
manual_scroll = ctk.CTkScrollableFrame(manual_tab, fg_color="transparent")
manual_scroll.pack(fill="both", expand=True)

ctk.CTkLabel(
    manual_scroll,
    text="Trigger bot stages by hand. Useful when you've manually navigated "
    "to a base in-game and want to test/run a single action.",
    font=("Segoe UI", 12),
    text_color="#aaaaaa",
    wraplength=860,
    justify="left",
).pack(fill="x", padx=8, pady=(8, 12))

# ── Detect Loot card ──
loot_card = _section(manual_scroll, "DETECT LOOT")
r = _row(loot_card, pad_y=(10, 10))
ctk.CTkLabel(
    r,
    text="Read the 'Available Loot' panel from the current screen.",
    font=("Segoe UI", 12),
    text_color="#888888",
).pack(side="left", padx=(0, ITEM_PAD))
ctk.CTkButton(
    r,
    text="Detect Loot",
    width=140,
    height=32,
    font=("Segoe UI", 12, "bold"),
    fg_color=ACCENT,
    hover_color="#3377ee",
    command=manual_detect_loot,
).pack(side="right")

# ── Manual Attack card ──
atk_manual_card = _section(manual_scroll, "MANUAL ATTACK")
r = _row(atk_manual_card, pad_y=(10, ROW_PAD))
ctk.CTkLabel(
    r,
    text="Deploy troops on the base currently shown (skips matchmaking + loot search).",
    font=("Segoe UI", 12),
    text_color="#888888",
    wraplength=600,
    justify="left",
).pack(side="left", padx=(0, ITEM_PAD))

r = _row(atk_manual_card, pad_y=(ROW_PAD, 10))
ctk.CTkLabel(r, text="Side", font=("Segoe UI", 13)).pack(side="left", padx=(0, 6))
_help_icon(r, "Which side to deploy. Random picks each time.").pack(
    side="left", padx=(0, 8)
)
manual_side_var = ctk.StringVar(value="Random")
ctk.CTkSegmentedButton(
    r,
    values=["Random", "Top left", "Top right", "Bottom right"],
    variable=manual_side_var,
    font=("Segoe UI", 12),
).pack(side="left", padx=(0, ITEM_PAD))
ctk.CTkButton(
    r,
    text="Attack Now",
    width=140,
    height=32,
    font=("Segoe UI", 12, "bold"),
    fg_color="#00aa55",
    hover_color="#008844",
    command=manual_attack,
).pack(side="right")


# ══════════════════════════════════════════════════════════════════
# LOG TAB — Canvas watermark (fixed) + transparent Text overlay
# ══════════════════════════════════════════════════════════════════

# Scrollbar (packs right first)
log_scrollbar = ctk.CTkScrollbar(log_tab)
log_scrollbar.pack(side="right", fill="y", padx=(0, 2), pady=2)

# Container for layered canvas + text
_log_frame = ctk.CTkFrame(log_tab, fg_color="transparent")
_log_frame.pack(fill="both", expand=True, padx=(2, 0), pady=2)

# Fixed watermark canvas (bottom layer — never scrolls)
_wm_canvas = tk.Canvas(_log_frame, bg="#0a0a1a", highlightthickness=0, bd=0)
_wm_canvas.place(relwidth=1, relheight=1)

_console_bg_photo = None
_console_bg_path = Path(__file__).parent / "templates" / "console_background.png"
if _console_bg_path.exists():
    from PIL import ImageEnhance

    _cbg = Image.open(_console_bg_path)
    _cbg = ImageEnhance.Brightness(_cbg).enhance(0.15)
    _tile_w, _tile_h = 210, 160
    _cbg_tile = _cbg.resize((_tile_w, _tile_h), Image.LANCZOS)
    _cols, _rows_wm = 6, 5
    _cbg_grid = Image.new("RGB", (_tile_w * _cols, _tile_h * _rows_wm), (10, 10, 26))
    for _ri in range(_rows_wm):
        for _ci in range(_cols):
            _cbg_grid.paste(_cbg_tile, (_ci * _tile_w, _ri * _tile_h))
    _console_bg_photo = ImageTk.PhotoImage(_cbg_grid)
    _wm_canvas.create_image(0, 0, image=_console_bg_photo, anchor="nw")

# Color key — this exact color becomes transparent via Windows API
_BG_KEY = "#010001"

# Text widget (top layer) overlaid on the watermark canvas
log_output = tk.Text(
    _log_frame,
    font=("Consolas", 12),
    bg=_BG_KEY,
    fg="#cccccc",
    insertbackground="#cccccc",
    wrap=tk.WORD,
    relief=tk.FLAT,
    bd=0,
    padx=10,
    pady=6,
)
log_output.place(relwidth=1, relheight=1)
log_output.configure(yscrollcommand=log_scrollbar.set)
log_scrollbar.configure(command=log_output.yview)


def _apply_transparent_bg():
    """Windows layered-window API: make _BG_KEY pixels transparent."""
    try:
        import ctypes

        hwnd = log_output.winfo_id()
        ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, ex_style | 0x80000)
        # COLORREF 0x00BBGGRR — #010001 → R=1 G=0 B=1 → 0x00010001
        ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0x00010001, 0, 0x1)
    except Exception:
        log_output.configure(bg="#0a0a1a")


log_output.after(200, _apply_transparent_bg)

# Log text styles
log_output.tag_configure("loot_line", font=("Consolas", 14, "bold"))
log_output.tag_configure(
    "gold_val", font=("Consolas", 14, "bold"), foreground="#FFD700"
)
log_output.tag_configure(
    "elixir_val", font=("Consolas", 14, "bold"), foreground="#FF69B4"
)
log_output.tag_configure(
    "dark_val", font=("Consolas", 14, "bold"), foreground="#FFFFFF"
)
log_output.tag_configure("warning", font=("Consolas", 14, "bold"), foreground="#FF6600")
log_output.tag_configure("error", font=("Consolas", 14, "bold"), foreground="#FF3333")
log_output.tag_configure("total", font=("Consolas", 14, "bold"), foreground="#00FF00")
log_output.tag_configure("step", font=("Consolas", 14, "bold"), foreground="#4488FF")

# Read-only but allow copy
log_output.bind(
    "<Key>",
    lambda e: (
        "break" if e.keysym not in ("c", "C", "a", "A") or not (e.state & 0x4) else None
    ),
)

# Right-click context menu
_rc_menu = tk.Menu(root, tearoff=0, font=("Segoe UI", 9))
_rc_menu.add_command(
    label="Copy",
    command=lambda: (
        root.clipboard_clear()
        or root.clipboard_append(log_output.get(tk.SEL_FIRST, tk.SEL_LAST))
        if log_output.tag_ranges(tk.SEL)
        else None
    ),
)
_rc_menu.add_command(
    label="Select All",
    command=lambda: log_output.tag_add(tk.SEL, "1.0", tk.END),
)
log_output.bind("<Button-3>", lambda e: _rc_menu.tk_popup(e.x_root, e.y_root))
log_output.configure(state="disabled")


# ══════════════════════════════════════════════════════════════════
# SPLASH SCREEN
# ══════════════════════════════════════════════════════════════════
def _request_close_after_update():
    stop_bot()
    root.after(250, root.destroy)


def _on_window_close():
    stop_bot()
    root.after(250, root.destroy)


root.protocol("WM_DELETE_WINDOW", _on_window_close)
atexit.register(lambda: None)


def _play_splash():
    """Splash screen intentionally disabled for fast, clean startup."""
    root.deiconify()


def _run_bot_cli():
    """Run a bot subcommand directly (used by compiled exe subprocess).

    sys.argv looks like: [exe, "--bot", "loop"]  (or "manual_attack [side]",
    "detect_loot"). Defaults to "loop" if no subcommand is given so older
    callers stay compatible.
    """
    args_after_flag = sys.argv[sys.argv.index("--bot") + 1:]
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
    else:
        from loguru import logger

        logger.error(f"Unknown --bot subcommand: {subcmd}")
        sys.exit(2)


if "--bot" in sys.argv:
    _run_bot_cli()
else:
    root.withdraw()
    root.after(100, _play_splash)
    root.mainloop()
