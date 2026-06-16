"""Process-scoped session state, deadline stack, structured event channel.

`session` is a module-level singleton (one process = one session).
Attribute mutation (`session.x = y`) never needs a `global` declaration
because the variable name `session` itself is never reassigned after init.

`deadline()` is a re-entrant context manager — nested calls push tighter
deadlines onto a stack; `check_deadline()` reads the top.

`emit()` prints a structured JSON line on stdout that the GUI parses as
state updates. Event types and fields are documented in `loop.py`.
"""

import json
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any


@dataclass
class BotSession:
    started_at: float
    next_break_at: float = 0.0
    break_blocked: bool = False
    next_event_at_cycle: int = 0
    # Fail-obviously counters (Phase 5):
    consecutive_unknown_states: int = 0
    # Timestamps of force_restart_coc calls in the last hour.
    recent_restarts: list[float] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.recent_restarts is None:
            self.recent_restarts = []


session = BotSession(started_at=time.time())


class BotStopRequested(Exception):
    """Raised to stop the loop from inside — bot cannot safely continue."""


class DeadlineExceeded(Exception):
    pass


_deadline_stack: list[float] = []


def check_deadline(step_name: str = ""):
    """Raise DeadlineExceeded if the innermost deadline has passed."""
    if _deadline_stack and time.time() > _deadline_stack[-1]:
        raise DeadlineExceeded(f"'{step_name}' exceeded deadline")


@contextmanager
def deadline(seconds: float):
    """Nestable deadline — the inner block must finish before `seconds` elapse."""
    _deadline_stack.append(time.time() + seconds)
    try:
        yield
    finally:
        _deadline_stack.pop()


EVENT_PREFIX = "__EVENT__ "


def emit(event_type: str, **fields: Any) -> None:
    """Emit a structured event line to stdout for the GUI to consume.

    Format: `__EVENT__ {"type": ..., ...}\\n`. Event schema lives in the
    `loop.py` module docstring.
    """
    payload = json.dumps({"type": event_type, **fields}, separators=(",", ":"))
    print(f"{EVENT_PREFIX}{payload}", flush=True, file=sys.stdout)
