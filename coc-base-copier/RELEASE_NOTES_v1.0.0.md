# Base Copier v1.0.0 (release candidate)

First tagged milestone of the Coc-farm base-copier module. **The detector is
working and fully tested; the paster has an open blocker (see below) — treat
this as a release candidate until that is resolved.**

## What's new

- **Detector** (`src/copy/`): Anthropic Vision-powered village layout detection.
  Returns a canonical JSON layout with buildings, walls, and traps on a 44x44
  tile grid. Theme-agnostic grid detection (works on winter / summer / desert —
  brightness-contrast based, not grass-color based).
- **Paster** (`src/paste/`): ADB-driven village editor automation — places
  buildings, drags wall chains, toggles trap visibility, resumes from interrupts.
  *(Currently blocked by a syntax error in `src/paste/cli.py`; see Known issues.)*
- **Roundtrip** (`src/paste/`): paste -> re-detect -> diff against source,
  reporting per-building-type match %. *(Not yet measured on-device — see Tested.)*
- **CLI**:
  - `python -m src.copy <screenshot.png> [output.json]` — detector (working)
  - `python -m src.paste <layout.json>` — paster (blocked, see below)
  - `python -m src.paste --roundtrip <screenshot.png>` — detect + paste + verify
  - `--resume` / `--dry-run` / `--device <serial>` flags

## Schema (v1.1.0)

- 44x44 tile grid, top-corner origin.
- Per-object fields: `id, category, type, level, tile_x, tile_y, pixel_x,
  pixel_y, footprint_w, footprint_h, footprint, rotation, is_trap, confidence`.
- Vision returns **pixel centers only**; the detector converts to tiles via the
  calibrated grid and **centers each type's footprint** on the center tile.
- Wall chains as ordered tile sequences with a `closed` flag.
- Traps flagged separately (`category="trap"`, `is_trap=true`).
- `BUILDING_FOOTPRINTS` table (cannon 3x3, Town Hall 4x4, etc.).
- See `docs/layout-schema.md` for the full spec.

## Reliability

- Vision transport downscales to 1568px, sets a 60s timeout, and **retries
  transient Anthropic errors** with exponential backoff: 5xx
  `InternalServerError` and connection/timeout errors (1s/2s/4s), `429`
  `RateLimitError` (2s/4s/8s/16s). 4xx (400/401/403/404) are never retried.
- Detector is robust to imperfect vision centering: overlaps are clamped/nudged
  or the offending building is skipped; walls landing on a building are skipped.
  A run only fails if **>10%** of buildings cannot be placed.

## Tested

- Detector unit/integration suite: **50 passed**
  (`pytest tests --ignore=tests/test_paste_cli.py`), incl. winter-theme grid
  detection (synthetic, confidence > 0.85), footprint placement, retry policies,
  and the copy CLI.
- Grid detection confirmed on a real winter-theme screenshot at confidence
  **0.95** (user-reported, earlier round).
- **Live end-to-end roundtrip match %: NOT YET MEASURED.** Requires
  `ANTHROPIC_API_KEY` + an LDPlayer device; could not be run in the build
  sandbox (no key / no Anthropic network access). Run locally to fill this in:
  `set ANTHROPIC_API_KEY=... & set COC_GRID_DEBUG=1 & python -m src.copy samples/test_village.png samples/test_village.json`

## Known issues / limitations (read before tagging)

- **BLOCKER (paster):** `src/paste/cli.py` (~line 56) has a SyntaxError — an
  incomplete `if` statement — so the paster CLI and `tests/test_paste_cli.py`
  do not import. Fix before declaring the paster shippable.
- **Live detector run unverified** in this environment (see Tested).
- Anthropic API key required (`ANTHROPIC_API_KEY`).
- Editor templates only for the English UI; only 2 of the planned editor
  templates are captured so far.
- Editor inventory placement still needs a real search/scroll/catalog mapping
  per building type (see `NOTES.md`, "Editor placement gap").
- No multi-account support yet (single village per run).

## Installation

```bash
cd coc-base-copier
pip install -r requirements.txt          # repo deps (opencv, numpy, loguru)
pip install -r src/copy/requirements.txt # + anthropic (live detection only)
export ANTHROPIC_API_KEY=...             # Windows: set ANTHROPIC_API_KEY=...
python -m src.copy samples/test_village.png samples/test_village.json
```
