"""
bot_logic.py - Project: Ghost Farm
==================================
The engine room. This is a *mock* bot so the GUI can be tested without the
game running. It speaks to the UI through ONE channel only: a thread-safe
`queue.Queue`. The GUI never touches bot internals and the bot never touches
Tk widgets -- that separation is what keeps the window from freezing and what
lets you swap this dummy out for the real automation later.

Message protocol (every item put on the queue is a small dict):
    {"kind": "log",    "level": "success|info|warning|error", "text": str}
    {"kind": "loot",   "gold": int, "elixir": int, "dark": int}     # cumulative
    {"kind": "status", "running": bool}
    {"kind": "timer",  "seconds": int}                              # next attack ETA

To wire in the REAL bot: keep the same method names (start_bot / stop_bot)
and keep emitting the same message kinds. The GUI will not need to change.
"""

import queue
import random
import threading
import time


class BotLogic:
    """Mock automation core. All public methods are safe to call from the GUI
    thread; all heavy work happens on a daemon worker thread."""

    def __init__(self, message_queue: "queue.Queue") -> None:
        self.q = message_queue
        self._running = False
        self._thread = None
        # Cumulative loot since the current run started.
        self.loot = {"gold": 0, "elixir": 0, "dark": 0}

    # -- Public control surface (called from the GUI) ------------------
    def start_bot(self) -> None:
        if self._running:
            return
        self._running = True
        self.loot = {"gold": 0, "elixir": 0, "dark": 0}
        self._emit(kind="status", running=True)
        self._emit(kind="loot", **self.loot)
        self._log("Bot engaged - entering battle loop.", "success")
        # Daemon thread dies with the app; never blocks shutdown.
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop_bot(self) -> None:
        if not self._running:
            return
        self._running = False
        self._emit(kind="status", running=False)
        self._emit(kind="timer", seconds=0)
        self._log("Bot disengaged. Standing down.", "warning")

    @property
    def is_running(self) -> bool:
        return self._running

    # -- Worker thread (mock battle loop) ------------------------------
    def _run(self) -> None:
        cycle = 0
        while self._running:
            cycle += 1
            self._log(f"[Cycle {cycle}] Scouting for a target base...", "info")

            # Mock "next attack" countdown - emits one tick per second so the
            # GUI timer animates smoothly without the bot blocking the UI.
            if not self._countdown(random.randint(4, 8)):
                break

            self._log("Target locked. Deploying army on the edges...", "info")
            if not self._interruptible_sleep(2.0):
                break

            # Mock loot gain - accumulate and push the new totals.
            g = random.randint(40_000, 420_000)
            e = random.randint(40_000, 420_000)
            d = random.randint(200, 3_200)
            self.loot["gold"] += g
            self.loot["elixir"] += e
            self.loot["dark"] += d
            self._emit(kind="loot", **self.loot)

            # Mix in realistic-looking outcomes so all console colors show.
            roll = random.random()
            if roll < 0.72:
                self._log(
                    f"Attack successful!  +{g:,} Gold  +{e:,} Elixir  +{d:,} DE",
                    "success",
                )
            elif roll < 0.90:
                self._log("Training fresh troops for the next wave...", "warning")
            else:
                self._log("ERROR: Connection hiccup detected - recovering.", "error")

            if not self._interruptible_sleep(1.5):
                break

        # Loop exit (stop requested) - make sure the timer reads zero.
        self._emit(kind="timer", seconds=0)

    # -- Internal helpers ----------------------------------------------
    def _countdown(self, seconds: int) -> bool:
        """Emit a 1-Hz timer tick. Returns False if stopped mid-countdown."""
        for remaining in range(seconds, -1, -1):
            if not self._running:
                return False
            self._emit(kind="timer", seconds=remaining)
            time.sleep(1.0)
        return True

    def _interruptible_sleep(self, seconds: float) -> bool:
        """Sleep in slices so stop_bot() is honored almost immediately."""
        end = time.time() + seconds
        while time.time() < end:
            if not self._running:
                return False
            time.sleep(0.05)
        return True

    def _log(self, text: str, level: str = "info") -> None:
        self._emit(kind="log", level=level, text=text)

    def _emit(self, **payload) -> None:
        """Single choke point for everything that leaves the engine. The GUI
        drains this queue on a timer - no shared mutable state, no locks."""
        self.q.put(payload)
