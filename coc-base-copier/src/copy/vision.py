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
import time
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


# --- transport hardening knobs ---
_MAX_IMAGE_LONG_SIDE = 1568   # Anthropic's recommended max long side for vision
_SERVER_ATTEMPTS = 4          # 5xx / connection: 3 retries -> sleeps 1s,2s,4s
_SERVER_BASE_S = 1.0
_RATELIMIT_ATTEMPTS = 5       # 429: 4 retries -> sleeps 2s,4s,8s,16s (longer)
_RATELIMIT_BASE_S = 2.0
_CLIENT_TIMEOUT_S = 60.0      # explicit client-side timeout


def _resize_for_vision(
    image: np.ndarray, max_side: int = _MAX_IMAGE_LONG_SIDE
) -> tuple[np.ndarray, float]:
    """Downscale so the long side <= max_side. Returns (image, scale_back).

    ``scale_back`` maps a coordinate in the *resized* image back to the
    *original* image (1.0 when no resize happened). Sending a smaller image
    avoids the large-base64 timeouts seen from sandboxed envs; the caller
    rescales the model's pixel coords back so the JSON contract (px/py in
    original-image space) is preserved.
    """
    h, w = image.shape[:2]
    long_side = max(h, w)
    if long_side <= max_side:
        return image, 1.0
    factor = max_side / float(long_side)
    new_w = max(1, int(round(w * factor)))
    new_h = max(1, int(round(h * factor)))
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return resized, float(w) / float(new_w)


def _rescale_detection_coords(text: str, scale: float) -> str:
    """Multiply every detection px/py by ``scale`` (resized -> original space).

    Operates on the model's JSON text and preserves all other keys. No-op when
    scale == 1.0 or the text is not parseable (left for detect_objects to
    surface strictly).
    """
    if scale == 1.0:
        return text
    try:
        data = json.loads(_strip_json(text))
    except Exception:
        return text
    for det in data.get("detections", []) or []:
        if isinstance(det, dict):
            if det.get("px") is not None:
                det["px"] = float(det["px"]) * scale
            if det.get("py") is not None:
                det["py"] = float(det["py"]) * scale
    return json.dumps(data)


def _retry_policies() -> list[tuple[tuple[type[BaseException], ...], int, float]]:
    """Backoff policies as (exception_types, max_attempts, base_delay_seconds).

    Two tiers, resolved lazily so anthropic/httpx stay optional:
      * 429 rate-limit -> longer backoff (2s, 4s, 8s, 16s)
      * 5xx + transient connection/timeout -> short backoff (1s, 2s, 4s)
    4xx client errors (400/401/403/404) are in NEITHER list, so they are never
    retried -- they propagate immediately.
    """
    server: list[type[BaseException]] = [TimeoutError, ConnectionError]
    rate: list[type[BaseException]] = []
    try:
        import anthropic  # noqa: PLC0415

        server += [
            anthropic.InternalServerError,  # 5xx (502 / 503 / ...)
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        ]
        rate += [anthropic.RateLimitError]  # 429
    except Exception:  # pragma: no cover - anthropic optional
        pass
    try:
        import httpx  # noqa: PLC0415

        server += [
            httpx.RemoteProtocolError,
            httpx.ReadTimeout,
            httpx.ConnectTimeout,
        ]
    except Exception:  # pragma: no cover - httpx optional
        pass

    policies: list[tuple[tuple[type[BaseException], ...], int, float]] = []
    if rate:
        policies.append((tuple(rate), _RATELIMIT_ATTEMPTS, _RATELIMIT_BASE_S))
    policies.append((tuple(server), _SERVER_ATTEMPTS, _SERVER_BASE_S))
    return policies


def _call_with_retries(
    fn,
    *,
    policies: list[tuple[tuple[type[BaseException], ...], int, float]],
    sleep=time.sleep,
):
    """Call ``fn``, retrying per ``policies`` with exponential backoff.

    Each policy is (exception_types, max_attempts, base_delay). On a matching
    error, wait ``base_delay * 2**(n-1)`` before retry ``n`` (counted per
    policy), up to that policy's max_attempts, then re-raise. Exceptions
    matching no policy (e.g. 400/401/403/404) propagate immediately.
    """
    counts: dict[int, int] = {}
    while True:
        try:
            return fn()
        except BaseException as exc:
            idx = next(
                (
                    i
                    for i, (types_, _a, _b) in enumerate(policies)
                    if isinstance(exc, types_)
                ),
                None,
            )
            if idx is None:
                raise
            _types, attempts, base_delay = policies[idx]
            counts[idx] = counts.get(idx, 0) + 1
            n = counts[idx]
            logger.warning(
                f"vision call failed (attempt {n}/{attempts}): "
                f"{exc.__class__.__name__}: {exc}"
            )
            if n >= attempts:
                raise
            sleep(base_delay * (2 ** (n - 1)))


@dataclass
class AnthropicTransport:
    """Production transport using the Anthropic Python SDK (lazy import).

    Hardened for flaky/sandboxed connectivity: downscales the image to
    Anthropic's recommended max long side, sets an explicit client-side
    timeout, and retries connection/timeout errors with exponential backoff.
    Auth errors are NOT retried. On final failure it raises DetectionError --
    it never silently returns empty. Signature and JSON contract are unchanged.
    """

    model: str = DEFAULT_MODEL
    max_tokens: int = MAX_TOKENS
    api_key: str | None = None  # falls back to ANTHROPIC_API_KEY env var
    timeout_s: float = _CLIENT_TIMEOUT_S
    _sleep: Any = time.sleep  # injectable for tests

    def complete(self, *, image_png: bytes, prompt: str, system: str) -> str:
        try:
            import anthropic  # noqa: PLC0415 - lazy by design
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                "The 'anthropic' package is required for live vision calls. "
                "Install it with `pip install anthropic`, or inject a custom "
                "VisionTransport for offline use."
            ) from exc

        # Decode the full-res PNG, downscale for the API, remember the scale so
        # the model's coords can be mapped back to original-image space.
        arr = cv2.imdecode(np.frombuffer(image_png, dtype=np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            send_bytes, scale = image_png, 1.0
        else:
            resized, scale = _resize_for_vision(arr)
            ok, buf = cv2.imencode(".png", resized)
            if ok:
                send_bytes = buf.tobytes()
            else:
                send_bytes, scale = image_png, 1.0
        b64 = base64.standard_b64encode(send_bytes).decode("ascii")

        client = (
            anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout_s)
            if self.api_key
            else anthropic.Anthropic(timeout=self.timeout_s)
        )

        def _do():
            return client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
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

        try:
            msg = _call_with_retries(
                _do, policies=_retry_policies(), sleep=self._sleep
            )
        except Exception as exc:  # final failure -> explicit, never silent
            from src.copy.detect import DetectionError  # lazy: avoid circular import
            from src.copy.schema import Layout

            raise DetectionError(
                f"vision API call failed after retries: "
                f"{exc.__class__.__name__}: {exc}",
                layout=Layout(),
                errors=[f"vision_transport: {exc!r}"],
            ) from exc

        text = "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        )
        return _rescale_detection_coords(text, scale)


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
      "px": <int>, "py": <int>,           // CENTER in PIXELS from the image top-left
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
- px/py are PIXEL coordinates of each object's center, measured from the
  top-left of the image you are shown. Report where each object APPEARS in
  pixels -- do NOT compute tile/grid coordinates or footprint sizes; the
  caller derives those from the pixel center plus its own grid calibration.
- Output JSON ONLY. No commentary, no code fences.

Confidence calibration (IMPORTANT -- be decisive, not timid):
- You MUST commit to confidence >= 0.85 for any building you can clearly see and
  identify. Reserve confidence < 0.85 ONLY for buildings that are partially
  occluded (by troops, another building, or UI) or sitting at the very edge of
  the diamond. Do NOT return confidence < 0.5 for anything you can name.
- DEFENSES have very distinctive shapes (cannon, archer_tower, mortar,
  wizard_tower, air_defense, x_bow, inferno_tower, eagle_artillery, scattershot,
  bomb_tower, air_sweeper, monolith). If you can identify the defense type, you
  ARE confident -- return 0.9 or higher.
- COLLECTORS / MINES (gold_mine, elixir_collector, dark_elixir_drill): identify
  them by the drill / collector mechanism (the pump, drill head, or collected
  resource on top), NOT by the base-building silhouette. Once identified, return
  0.85 or higher.

Examples of correct confidence:
- A fully visible, clearly centered cannon you can identify -> confidence 0.95.
- An archer_tower half-hidden behind deployed troops, type still recognizable
  but partially obscured -> confidence 0.6.
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
    h, w = image.shape[:2]
    prompt = f"The screenshot is about {w}x{h} pixels.\n\n" + USER_PROMPT
    text = transport.complete(image_png=png, prompt=prompt, system=SYSTEM_PROMPT)

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
