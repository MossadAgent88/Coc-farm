"""The vision prompt must ask for PIXEL centers, never tile coordinates."""

from __future__ import annotations

from src.copy.vision import USER_PROMPT


def test_prompt_asks_for_pixel_center():
    low = USER_PROMPT.lower()
    assert "pixel" in low
    assert "center" in low


def test_prompt_forbids_tile_math():
    low = USER_PROMPT.lower()
    assert "do not compute tile" in low
    # never instructs the model to emit tile_x / tile_y
    assert "tile_x" not in USER_PROMPT and "tile_y" not in USER_PROMPT


def test_prompt_pushes_high_confidence_for_clear_buildings():
    low = USER_PROMPT.lower()
    assert ">= 0.85" in USER_PROMPT          # decisive floor for clear buildings
    assert "do not return confidence < 0.5" in low
    # defense + collector specific guidance present
    assert "defenses have very distinctive shapes" in low
    assert "drill / collector mechanism" in low
    # few-shot calibration examples (0.95 clear, 0.6 occluded)
    assert "0.95" in USER_PROMPT and "0.6" in USER_PROMPT
