# Paster Notes

Round 2 imported the real detector contract from `origin/main`:

- `docs/layout-schema.md`
- `src/copy/schema.py`
- `src/copy/grid.py`
- `src/copy/validate.py`
- `src/copy/vision.py`
- `src/copy/detect.py`

No detector schema fields were added or changed.

## Contract fixes made

- `src.paste.layout.load_layout()` now calls
  `src.copy.schema.Layout.from_json(text)` exactly as implemented by the real
  schema.
- Wall chains now consume the canonical `WallChain.tiles` list.
- The editor grid now wraps `src.copy.grid.Grid` and delegates
  `tile_to_pixel(tx, ty)` to the detector grid implementation.
- `roundtrip()` now uses `src.copy.detect.detect_from_device()`.

## Live device findings

ADB connected to `emulator-5554`, Clash of Clans launched, and the account was
opened into Village Edit Mode. Real templates were captured from the device:

- `templates/editor_save.png`
- `templates/editor_show_traps_on.png`

Both templates matched the live editor screenshot at confidence `1.000` on the
capture they were cropped from.

Editor grid calibration succeeded on a live panned editor screenshot with
detector-grid confidence `0.762`:

```text
top    = (1449.0, -92.0)
right  = (1617.0, 916.0)
bottom = (74.0, 1172.0)
left   = (-93.0, 164.0)
tile_22_22 -> (746, 554)
```

The negative/offscreen corners are intentional: the detector grid accepts a
partly offscreen diamond when the contour confidence is high enough. The paster
now allows a bounded offscreen margin instead of rejecting valid detector-grid
corners.

## Remaining blocker

The actual live detector call could not complete. `ANTHROPIC_API_KEY` was set
and `anthropic` was installed from `src/copy/requirements.txt`, but repeated
vision calls failed with:

```text
anthropic.APIConnectionError: Connection error.
httpx.RemoteProtocolError: peer closed connection without sending complete message body
```

This happened with both the detector default model and a smaller explicit test
transport (`claude-3-5-sonnet-latest`, `max_tokens=2048`). Because detector JSON
could not be produced, a real `roundtrip()` match percentage was not measurable
in this run.

### Round 2.5 detector CLI verification

`samples/test_village.png` was captured from the live device through ADB in
Village Edit Mode Photo Mode after zooming fully out. The detector reached the
Anthropic transport but failed with the same API stability issue:

```text
anthropic.APIConnectionError: Connection error.
httpx.RemoteProtocolError: peer closed connection without sending complete message body (incomplete chunked read)
httpcore.RemoteProtocolError: peer closed connection without sending complete message body (incomplete chunked read)
h11._util.RemoteProtocolError: peer closed connection without sending complete message body (incomplete chunked read)
```

No `src.copy.vision` changes were made. Claude should harden the detector
transport/retry behavior separately.

## Editor placement gap

The live Village Edit Mode UI exposes a horizontal inventory strip, not the
category/shop layout assumed by the first paster scaffold. The code now avoids
tapping a nonexistent shop button, but full no-mistake placement still needs a
real inventory search/scroll/catalog mapping for every canonical `type`.

## Detector-side review (v1.0.0 wrap-up, Claude)

Reviewed `src/copy/{detect,vision,grid,schema,validate}.py`. All detector
invariants confirmed; no detector bugs or regressions found:

- vision.py: prompt asks for PIXEL centers only ("do NOT compute tile/grid
  coordinates"); `temperature` removed; **5xx/429 retry IS implemented** (commit
  d2c5f54) — `_retry_policies()` retries InternalServerError + RateLimitError +
  APIConnectionError + APITimeoutError with backoff. (The earlier "5xx retry
  pending" note is now OUTDATED — it's done.)
- detect.py: footprint centered on detected center tile
  (`anchor = center - (footprint-1)//2`), clamped in-bounds, nudged up to 3
  tiles or skipped; stores `pixel_x/pixel_y`; fails only if >10% skipped.
- grid.py: theme-agnostic multi-mask + auto-Canny + Hough corner detection;
  debug artifacts honor `COC_GRID_DEBUG_DIR`.
- schema.py: SCHEMA_VERSION = "1.1.0"; `BUILDING_FOOTPRINTS` present;
  `pixel_x/pixel_y` + `footprint_w/footprint_h` fields present.
- validate.py: footprint-aware collisions via `occupied_tiles()`; exactly-one-TH
  and wall-count sanity intact.

Tests: `pytest tests --ignore=tests/test_paste_cli.py` -> **50 passed**.
`test_copy_cli.py` already asserts `schema_version=1.1.0` (no change needed).

### RELEASE BLOCKERS (paste side — not detector)

1. `src/paste/cli.py` line ~56 has a SyntaxError (an incomplete `if`), so
   `from src.paste import cli` fails to import and `tests/test_paste_cli.py`
   cannot be collected. The paster CLI does not run until this is fixed.
2. Live end-to-end detector run NOT verified here: this sandbox has no
   `ANTHROPIC_API_KEY` and no outbound access to the Anthropic API, so
   `python -m src.copy samples/test_village.png` could not be executed. Prior
   live attempts (above) hit transient `APIConnectionError`; the transport now
   retries those, but a real run still needs the user's key + network.
