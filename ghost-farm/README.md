# Project: Ghost Farm — Command-Center GUI

A dark, tactical "battle-station" dashboard for a Clash of Clans farm bot.
Sidebar + tabbed main view, threaded engine, thread-safe queue, color-coded
console, live loot counters, countdown timer, and minimize-to-tray.

## Files
| File | Role |
|------|------|
| `main_gui.py` | App shell, grid layout, the 100 ms queue→UI pump, tray, shutdown |
| `ui_components.py` | `Sidebar`, `Dashboard`, `Settings` frames + the color palette |
| `bot_logic.py` | **Mock** bot — emits fake log/loot/status/timer events so you can test the UI without the game |

## Run
```bash
pip install customtkinter pystray pillow
python main_gui.py
```
`pystray`/`pillow` are optional — without them the app runs fine, it just
won't minimize to the tray (it quits on close instead).

## How it stays smooth (the threading model)
- `BotLogic` runs on its **own daemon thread** and only ever pushes small dict
  messages onto a `queue.Queue`.
- The GUI **never** reads bot state directly. It drains that queue every 100 ms
  on the Tk main thread (`_drain_queue`) and updates widgets there.
- One rule: *only the drain touches widgets.* That's why the window never freezes.

## Wiring in the real bot
Replace `bot_logic.py` with your real automation, keeping:
- the methods `start_bot()` / `stop_bot()` and the `is_running` property, and
- the four message kinds it emits: `log`, `loot`, `status`, `timer`.

The GUI needs no changes — it just renders whatever comes through the queue.
