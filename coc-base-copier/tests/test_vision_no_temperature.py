"""Regression: the Anthropic call must NOT pass the deprecated `temperature`.

Claude Opus 4.x / Sonnet 4.x reject `temperature` with a 400. We inject a fake
`anthropic` module so the test needs no network/SDK, capture the kwargs handed
to messages.create(), and assert `temperature` is absent.
"""

from __future__ import annotations

import sys
import types

import cv2
import numpy as np

from src.copy.vision import AnthropicTransport


def _install_fake_anthropic(monkeypatch, recorder: dict):
    class _Messages:
        def create(self, **kwargs):
            recorder["kwargs"] = kwargs
            block = types.SimpleNamespace(type="text", text='{"detections": []}')
            return types.SimpleNamespace(content=[block])

    class _Anthropic:
        def __init__(self, *args, **kwargs):
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic
    fake.APIConnectionError = type("APIConnectionError", (Exception,), {})
    fake.APITimeoutError = type("APITimeoutError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "anthropic", fake)


def _tiny_png() -> bytes:
    img = np.zeros((20, 40, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def test_create_call_omits_temperature(monkeypatch):
    recorder: dict = {}
    _install_fake_anthropic(monkeypatch, recorder)

    out = AnthropicTransport().complete(
        image_png=_tiny_png(), prompt="p", system="s"
    )

    assert "kwargs" in recorder, "messages.create was never called"
    assert "temperature" not in recorder["kwargs"], (
        "temperature must NOT be sent (deprecated on Opus/Sonnet 4.x)"
    )
    # sanity: the call still carries the essentials it always did
    assert recorder["kwargs"]["model"]
    assert recorder["kwargs"]["max_tokens"]
    assert out == '{"detections": []}'
