"""End-to-end transport retry through AnthropicTransport.complete().

Injects a fake `anthropic` module exposing the real exception class names so
the production policy wiring (_retry_policies) is exercised: 5xx is retried,
4xx is not. No network / no SDK required.
"""

from __future__ import annotations

import sys
import types

import cv2
import numpy as np
import pytest

from src.copy.detect import DetectionError
from src.copy.vision import AnthropicTransport


def _make_fake_anthropic(create_side_effect):
    """Build a fake `anthropic` module whose messages.create runs the callable."""
    exc_names = [
        "InternalServerError",
        "RateLimitError",
        "APIConnectionError",
        "APITimeoutError",
        "BadRequestError",
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
    ]
    mod = types.ModuleType("anthropic")
    for name in exc_names:
        setattr(mod, name, type(name, (Exception,), {}))

    class _Messages:
        def create(self, **kwargs):
            return create_side_effect(kwargs)

    class _Anthropic:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    mod.Anthropic = _Anthropic
    return mod


def _tiny_png() -> bytes:
    ok, buf = cv2.imencode(".png", np.zeros((20, 40, 3), dtype=np.uint8))
    assert ok
    return buf.tobytes()


def _ok_response():
    block = types.SimpleNamespace(type="text", text='{"detections": []}')
    return types.SimpleNamespace(content=[block])


def test_internal_server_error_is_retried_then_succeeds(monkeypatch):
    state = {"n": 0}

    def side_effect(_kwargs):
        state["n"] += 1
        if state["n"] < 3:
            raise sys.modules["anthropic"].InternalServerError("502 Bad Gateway")
        return _ok_response()

    monkeypatch.setitem(sys.modules, "anthropic", _make_fake_anthropic(side_effect))

    slept: list[float] = []
    out = AnthropicTransport(_sleep=slept.append).complete(
        image_png=_tiny_png(), prompt="p", system="s"
    )
    assert out == '{"detections": []}'
    assert state["n"] == 3          # failed twice, succeeded on the third
    assert slept == [1.0, 2.0]      # 5xx short backoff


def test_bad_request_is_not_retried(monkeypatch):
    state = {"n": 0}

    def side_effect(_kwargs):
        state["n"] += 1
        raise sys.modules["anthropic"].BadRequestError("400 invalid")

    monkeypatch.setitem(sys.modules, "anthropic", _make_fake_anthropic(side_effect))

    slept: list[float] = []
    with pytest.raises(DetectionError) as exc:
        AnthropicTransport(_sleep=slept.append).complete(
            image_png=_tiny_png(), prompt="p", system="s"
        )
    assert state["n"] == 1          # tried exactly once -- no retry
    assert slept == []              # never backed off
    assert "BadRequestError" in str(exc.value)
