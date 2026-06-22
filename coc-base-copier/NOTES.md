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

> **UPDATE:** The `cli.py` SyntaxError blocker (#1 above) was fixed in commit
> `cbefd19`. `tests/test_paste_cli.py` now collects and passes. Blocker #2
> (live detector run) still needs the user's API key + network and is not
> verifiable in CI.

## Pyright type-check findings (cleanup task, 2026-06-22)

Ran `pyright` with `pyrightconfig.json` (`include: ["src"]`, strict off,
`reportMissingImports: true`). **Baseline: 20 errors.** After fixing the one
in-scope file (`src/paste/layout.py:196`), **19 errors remain — all in
out-of-scope files owned by Claude/Codex.** These are logged here per the
stop-conditions; they were NOT fixed.

Fixed (in-scope):
- `src/paste/layout.py:196` — `_slug(raw_type or name)` could pass `None`.
  Coalesced to `_slug(raw_type or name or "")`.

Remaining (for Claude/Codex — do NOT fix from cleanup task):

- `src/copy/detect.py:484:10` — `Import "cocbot.io" could not be resolved`.
  The base-copier is a namespaced sub-project; `cocbot` is the sibling bot
  package and is not on the path inside `coc-base-copier/`. This is a known
  cross-project dependency; either add `cocbot` to the base-copier install
  or guard the import. (Claude / detector owner.)
- `src/copy/vision.py:275:19` — `Cannot access attribute "text"` for ~11
  Anthropic SDK union members (`ThinkingBlock`, `ToolUseBlock`, etc.). The
  code iterates `response.content` and reads `.text`; needs a
  `getattr(block, "text", None)` or `isinstance` guard. (Claude / detector
  owner.)
- `src/paste/editor.py:21-23` — `cocbot.io` / `cocbot.vision` import not
  resolved (same cross-project issue as detect.py). (Codex / paster owner.)
- `src/paste/editor.py:333-335` — `Index 0 is out of range for type tuple[()]`
  on a cv2 `findContours` return shape. Needs typing fix or assertion.
  (Codex / paster owner.)
- `src/paste/roundtrip.py:65:30` — `Cannot access attribute
  "detect_from_device" for class "object"`. The injected detector object
  needs a Protocol/ABC type instead of `object`. (Codex / paster owner.)

## Ruff findings (cleanup task, 2026-06-22)

`ruff check --select F401 src/` → **1 finding, in a forbidden file:**
- `src/copy/detect.py:35` — `GridRegistrationError` imported but unused (F401).
  NOT fixed (detector-owned by Claude). Claude: either remove the import or
  use the symbol.

`ruff check --select I src/` → **7 import-sort findings.** Fixed the 4 in
allowed paste files (`src/paste/{__init__,__main__,accounts,cli}.py`). Left
the 3 in forbidden files for their owners:
- `src/copy/__init__.py:11` (Claude)
- `src/copy/schema.py:11` (Claude)
- `src/paste/editor.py:21` (Codex)

## What's left / needs Claude or Codex attention

### For Claude (detector owner — `src/copy/*`)

1. **`src/copy/detect.py:484`** — `import cocbot.io` doesn't resolve inside
   the `coc-base-copier/` sub-project. Either make `cocbot` an optional
   dependency of the base-copier or guard the import so the detector is
   importable/testable without the bot package.
2. **`src/copy/detect.py:35`** — unused `GridRegistrationError` import (F401).
3. **`src/copy/vision.py:275`** — `response.content` block `.text` access is
   unsafe across the Anthropic SDK union (ThinkingBlock/ToolUseBlock/etc.).
   Add an `isinstance(block, TextBlock)` guard or `getattr(..., "text", "")`.
4. **Import sort** in `src/copy/__init__.py` and `src/copy/schema.py` (I001).
5. **0 wall chains bug** (README troubleshooting §): the paster README
   references a known wall-grouping regression where the detector reports N
   walls but the paster yields 0 chains. Please confirm whether this is
   still reproducible on `origin/main` so the README can drop the
   conditional wording.

### For Codex (paster owner — `src/paste/{editor,place,roundtrip}.py`)

1. **`src/paste/editor.py:21-23`** — `cocbot.io` / `cocbot.vision` imports
   don't resolve inside `coc-base-copier/` (same cross-project issue as
   the detector).
2. **`src/paste/editor.py:333-335`** — cv2 `findContours` return index is
   typed `tuple[()]`; needs an assertion or a cast.
3. **`src/paste/roundtrip.py:65`** — the injected detector is typed `object`;
   use a `Protocol` (`SupportsDetectFromDevice`) so `.detect_from_device`
   type-checks.
4. **Import sort** in `src/paste/editor.py` (I001).

### Not verifiable from this cleanup (no device / no API key in CI)

- Live end-to-end `roundtrip()` match percentage (needs a real
  `ANTHROPIC_API_KEY` + working network — see "Remaining blocker" above).
- The live detector `APIConnectionError` (peer closed connection) last seen
  in Round 2.5. The transport now retries it, but a real run is needed to
  confirm it's resolved on the user's network.

### Cleanup summary (this task)

- **7 commits** (1 per task: README, requirements, typecheck, tests, CI,
  multi-account, final pass).
- **Pytest: 55 → 68 passed** (+13 new tests).
- **Pyright: 20 → 19 errors** (1 fixed in-scope; 19 logged for owners).
- **Ruff: F401 1 (forbidden), I001 7 → 4 fixed / 3 logged.**
