"""Claude Vision detection — ONE API call per screenshot.

Returns the full building/trap/wall list as parsed JSON. We never call the
model per-building (slow + expensive); a single call returns everything.

The detection result is intentionally in **pixel space** (each item has a
``px``/``py`` center). Mapping pixel -> tile is the job of ``grid.py``; the
vision model only answers "what is at roughly which pixel, what level, how
confident". This split keeps tile math deterministic and testable.

Dependency note: this module uses the official ``anthropic`` SDK, imported
lazily so importing this package never requires it and tests can inject a fake
client. Justification for the new dep: it is the canonical, maintained client
for the Claude API and avoids hand-rolling auth/retry against the HTTP API.
Install with ``pip install anthropic`` (see src/copy/requirements.txt).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Protocol

import cv2
import numpy as np

try:
    from loguru import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("coc.copy.vision")

from src.copy.schema import VALID_CATEGORIES

# Model + limits. Kept here so they are easy to bump in one place.
DEFAULT_MODEL = "claude-opus-4-8"
MAX_TOKENS = 8192

# A raw detection straight from the vision model, before grid registration.
RawDetection = dict[str, Any]


class VisionTransport(Protocol):
    """Anything that turns (image_bytes, prompt) into raw model text.

    Implemented by :class:`AnthropicTransport` for production and by fakes in
    tests, so ``detect_objects`` never needs a network or API key under test.
    """

    def complete(self, *, image_png: bytes, prompt: str, system: str) -> str: ...


@dataclass
class AnthropicTransport:
    """Production transport using the Anthropic Python SDK (lazy import)."""

    model: str = DEFAULT_MODEL
    max_tokens: int = MAX_TOKENS
    api_key: str | None = None  # falls back to ANTHROPIC_API_KEY env var

    def complete(self, *, image_png: bytes, prompt: str, system: str) -> str:
        try:
            import anthropic  # noqa: PLC0415 - lazy by design
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                "The 'anthropic' package is required for live vision calls. "
                "Install it with `pip install anthropic`, or inject a custom "
                "VisionTransport for offline use."
            ) from exc

        client = (
            anthropic.Anthropic(api_key=self.api_key)
            if self.api_key
            else anthropic.Anthropic()
        )
        b64 = base64.standard_b64encode(image_png).decode("ascii")
        msg = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0,  # deterministic — required for idempotency
            system=system,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        # Concatenate text blocks (vision replies are a single text block).
        return "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        )


SYSTEM_PROMPT = (
    "You are a precise Clash of Clans base analyzer. You look at one screenshot "
    "of a village and return a strict JSON inventory of every visible object. "
    "You never invent objects you cannot see and never guess a level you cannot "
    "read — use null for unknown levels. You always output valid JSON only, with "
    "no prose, no markdown fences."
)

# The prompt mirrors the schema so the model's output maps 1:1 onto RawDetection.
USER_PROMPT = """\
Analyze this Clash of Clans village screenshot. Return ONE JSON object:

{
  "view": "normal" | "editor",            // is this the editable layout view?
  "town_hall_level": <int or null>,
  "detections": [
    {
      "type": "<canonical snake_case key, e.g. cannon, archer_tower, wall>",
      "category": "defense"|"resource"|"army"|"trap"|"obstacle"|"decoration",
      "level": <int or null>,             // null if you cannot read it; never guess
      "px": <int>, "py": <int>,           // pixel center of the object in THIS image
      "rotation": 0|90|180|270,
      "confidence": <float 0..1>          // your certainty for THIS object
    }
  ]
}

Rules:
- Report EVERY building, trap, wall piece, obstacle and decoration you can see.
- Each wall piece is its own detection with type "wall" (do not group them).
- Traps are only visible in the editor/layout view; if view is "normal", report
  the traps you can see (often none) and rely on confidence to flag uncertainty.
- Set confidence honestly. Anything you are unsure about should be < 0.7.
- px/py must be the on-screen pixel center of the object footprint.
- Output JSON ONLY. No commentary, no code fences.
"""


def _encode_png(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("failed to PNG-encode screenshot for vision call")
    return buf.tobytes()


def _strip_json(text: str) -> str:
    """Best-effort extraction of a JSON object from model text."""
    t = text.strip()
    if t.startswith("```"):
        # remove ```json ... ``` fences if the model added them anyway
        t = t.split("```", 2)[1] if t.count("```") >= 2 else t.strip("`")
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in vision response")
    return t[start : end + 1]


@dataclass
class VisionResult:
    view: str
    town_hall_level: int | None
    detections: list[RawDetection]
    raw_text: str


def detect_objects(
    image: np.ndarray,
    transport: VisionTransport | None = None,
) -> VisionResult:
    """Run the single vision call and return parsed, lightly-validated raw output.

    Parsing is strict-ish: malformed items are dropped from ``detections`` but
    recorded so the caller (detect.py) can surface them — nothing is silently
    swallowed without a trace in the logs.
    """
    transport = transport or AnthropicTransport()
    png = _encode_png(image)
    text = transport.complete(image_png=png, prompt=USER_PROMPT, system=SYSTEM_PROMPT)

    data = json.loads(_strip_json(text))
    if not isinstance(data, dict):
        raise ValueError("vision response was not a JSON object")

    raw_items = data.get("detections", [])
    if not isinstance(raw_items, list):
        raise ValueError("'detections' must be a list")

    clean: list[RawDetection] = []
    dropped = 0
    for item in raw_items:
        if not isinstance(item, dict):
            dropped += 1
            continue
        if "type" not in item or "px" not in item or "py" not in item:
            dropped += 1
            continue
        cat = item.get("category")
        if cat not in VALID_CATEGORIES:
            # keep it but normalize to a safe bucket; detect.py will warn
            item["category"] = _infer_category(str(item["type"]))
        clean.append(item)
    if dropped:
        logger.warning(f"vision: dropped {dropped} malformed detection item(s)")

    return VisionResult(
        view=str(data.get("view", "normal")),
        town_hall_level=data.get("town_hall_level"),
        detections=clean,
        raw_text=text,
    )


def _infer_category(type_key: str) -> str:
    from src.copy.schema import KNOWN_TYPES

    spec = KNOWN_TYPES.get(type_key)
    if spec:
        return spec[2]
    if type_key == "wall":
        return "defense"  # walls are handled separately; placeholder category
    return "decoration"
