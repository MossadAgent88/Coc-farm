"""Transport hardening: retry/backoff, resize, and coord rescale.

No network / no anthropic package needed -- we test the pure helpers directly,
including the required case: a connection error twice, then success.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from src.copy.vision import (
    _call_with_retries,
    _rescale_detection_coords,
    _resize_for_vision,
)


class _FakeConnError(Exception):
    """Stand-in for anthropic.APIConnectionError / incomplete chunked read."""


class _FakeAuthError(Exception):
    """Stand-in for a non-retryable auth error."""


def test_retry_succeeds_after_two_connection_errors():
    calls = {"n": 0}
    slept: list[float] = []

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _FakeConnError("incomplete chunked read")
        return "ok"

    out = _call_with_retries(
        fn, retryable=(_FakeConnError,), sleep=slept.append
    )
    assert out == "ok"
    assert calls["n"] == 3            # failed twice, succeeded on the 3rd
    assert slept == [1.0, 2.0]        # exponential backoff before each retry


def test_auth_error_is_not_retried():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise _FakeAuthError("401 unauthorized")

    with pytest.raises(_FakeAuthError):
        _call_with_retries(fn, retryable=(_FakeConnError,), sleep=lambda _s: None)
    assert calls["n"] == 1            # tried once, no retry


def test_exhausted_retries_reraise_last():
    def fn():
        raise _FakeConnError("server down")

    with pytest.raises(_FakeConnError):
        _call_with_retries(fn, retryable=(_FakeConnError,), sleep=lambda _s: None)


def test_resize_caps_long_side_and_reports_scale():
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    resized, scale = _resize_for_vision(img)
    assert max(resized.shape[:2]) == 1568
    assert abs(scale - 1920 / 1568) < 1e-6
    # already small -> untouched, scale 1.0
    small = np.zeros((100, 200, 3), dtype=np.uint8)
    r2, s2 = _resize_for_vision(small)
    assert s2 == 1.0 and r2.shape == small.shape


def test_rescale_maps_coords_back_to_original_space():
    text = json.dumps(
        {"view": "editor", "detections": [{"type": "cannon", "px": 100, "py": 50}]}
    )
    out = json.loads(_rescale_detection_coords(text, 2.0))
    assert out["detections"][0]["px"] == 200
    assert out["detections"][0]["py"] == 100
    assert out["view"] == "editor"  # other keys preserved
    # scale 1.0 is a no-op (returns input unchanged)
    assert _rescale_detection_coords(text, 1.0) == text
