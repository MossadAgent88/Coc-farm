"""Transport retry helper: policy-based backoff, resize, and coord rescale.

No network / no anthropic package needed -- the pure helpers are tested with
stand-in exception types and an injected sleep.
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
    """Stand-in for a retryable connection/5xx error."""


class _FakeAuthError(Exception):
    """Stand-in for a non-retryable 4xx error."""


# server-tier policy: 4 attempts (3 retries), base 1.0 -> sleeps 1, 2, 4
_SERVER = [((_FakeConnError,), 4, 1.0)]


def test_retry_succeeds_after_two_failures():
    calls = {"n": 0}
    slept: list[float] = []

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _FakeConnError("502 bad gateway")
        return "ok"

    out = _call_with_retries(fn, policies=_SERVER, sleep=slept.append)
    assert out == "ok"
    assert calls["n"] == 3
    assert slept == [1.0, 2.0]  # exponential backoff before each retry


def test_non_retryable_error_is_not_retried():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise _FakeAuthError("400 / 401 / 403 / 404")

    with pytest.raises(_FakeAuthError):
        _call_with_retries(fn, policies=_SERVER, sleep=lambda _s: None)
    assert calls["n"] == 1  # matched no policy -> immediate


def test_exhausted_retries_reraise_last_with_full_backoff():
    calls = {"n": 0}
    slept: list[float] = []

    def fn():
        calls["n"] += 1
        raise _FakeConnError("server down")

    with pytest.raises(_FakeConnError):
        _call_with_retries(fn, policies=_SERVER, sleep=slept.append)
    assert calls["n"] == 4
    assert slept == [1.0, 2.0, 4.0]


def test_rate_limit_policy_uses_longer_backoff():
    class _Rate(Exception):
        pass

    calls = {"n": 0}
    slept: list[float] = []
    # rate-limit tier: 5 attempts (4 retries), base 2.0 -> 2, 4, 8, 16
    policies = [((_Rate,), 5, 2.0)]

    def fn():
        calls["n"] += 1
        raise _Rate("429")

    with pytest.raises(_Rate):
        _call_with_retries(fn, policies=policies, sleep=slept.append)
    assert calls["n"] == 5
    assert slept == [2.0, 4.0, 8.0, 16.0]


def test_resize_caps_long_side_and_reports_scale():
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    resized, scale = _resize_for_vision(img)
    assert max(resized.shape[:2]) == 1568
    assert abs(scale - 1920 / 1568) < 1e-6
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
    assert out["view"] == "editor"
    assert _rescale_detection_coords(text, 1.0) == text
