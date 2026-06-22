# Base Copier — Detector (the "copy" half)

Adds a **base copier** to the existing [Coc-farm](https://github.com/MossadAgent88/Coc-farm)
bot: it turns a screenshot of any village (clan chat, war, FC, another account)
into a canonical JSON layout. This deliverable is the **detector + schema only**.
The **paster is a separate task** and is intentionally not built here.

## What I read in the existing repo, and what I reused

| Existing file | What it does | How this module reuses it |
|---|---|---|
| `cocbot/io.py` | ADB/device layer: `capture_screenshot() -> BGR np.ndarray (1920x1080)`, `tap`, `swipe`, reconnect | `detect_from_device()` calls `capture_screenshot()` (lazy import) instead of re-implementing ADB |
| `cocbot/vision.py` | Pure `image -> answer` template matching, cv2+numpy+loguru, 1920x1080 ROI conventions | Mirrored its style: pure functions, `loguru` logger, cv2/numpy, "tuned for 1920x1080" contract |
| `cocbot/config.py` | `BotConfig` dataclass + frozen `cfg` singleton | Mirrored dataclass + module-constant style for `schema.py` (`SCHEMA_VERSION`, `GRID_SIZE`, `CONFIDENCE_FLOOR`) |
| `cocbot/session.py` | `emit()` structured events, `BotStopRequested` | Matched the explicit-failure ethos (`DetectionError` carries layout+reasons) |
| `cocbot/debug.py` | `dbg` annotated-screenshot overlay | Noted as the natural place to render a detection overlay later (paster aid) |
| `pyproject.toml` / `conftest.py` | `testpaths=["tests"]`, `python_files=["test_*.py"]`, PNG-fixture guard | Put new tests in `tests/` to match `testpaths`; pytest-only, no new test deps beyond repo's `pytest` |
| `requirements.txt` | `opencv-python>=4.13`, `numpy>=2.4`, `loguru` | Reused as-is; the ONLY new dep is `anthropic` (see `src/copy/requirements.txt`) |

No ADB, screenshot, or device code was duplicated — the new module sits on top of
the existing I/O layer.

## New files

```
docs/layout-schema.md        canonical JSON schema (the contract with the paster)
src/__init__.py              namespaces the package as `src.copy` (avoids shadowing stdlib `copy`)
src/copy/__init__.py
src/copy/schema.py           dataclasses + JSON (de)serialization, KNOWN_TYPES, footprints
src/copy/grid.py             OpenCV corner detection + homography; pixel_to_tile(x,y)
src/copy/vision.py           ONE Claude Vision call -> strict JSON (injectable transport)
src/copy/validate.py         schema + sanity checks (collisions, bounds, one TH, wall cap)
src/copy/detect.py           detect(screenshot_path) -> Layout; retries; wall-chain parsing; detect_from_device()
src/copy/requirements.txt    the single new dependency (anthropic), lazy-imported
tests/                       fake-screenshot pipeline, schema conformance, wall-chains, grid
samples/README.md            expected input format (repo has no village screenshot)
```

## Install & run

```bash
pip install -r requirements.txt          # existing repo deps (opencv, numpy, loguru)
pip install -r src/copy/requirements.txt # + anthropic (only for live calls)
export ANTHROPIC_API_KEY=sk-ant-...

python -m src.copy.detect samples/your_village.png --out layout.json
# or, live from the emulator via the existing ADB layer:
python -c "from src.copy.detect import detect_from_device; print(detect_from_device().to_json())"
```

Import path is `src.copy` (not `copy`) on purpose: a top-level package named
`copy` would shadow the standard-library `copy` module that OpenCV/numpy import.

## Tests

```bash
python -m pytest -q        # 28 tests, no network / no API key (fake vision transport)
```

Covered: full pipeline on a synthetic screenshot, schema conformance + JSON
round-trip, wall-chain parsing (lines, loops, T-junctions, diagonals,
determinism), and grid registration (corner detection, homography, sanity gate).

## Design guarantees

- **Idempotent** — `temperature=0` vision call + deterministic, sorted
  post-processing. Same screenshot bytes -> same `image_id` -> same detected
  content. (Only `source.captured_at` varies; it is excluded from the idempotency
  test.)
- **Confidence-gated** — anything `< 0.7` triggers a re-ask (max 2 retries); if
  it survives, it is surfaced in `warnings`, never silently used.
- **Failure-explicit** — buildings are never silently dropped; missing TH /
  collisions / out-of-bounds raise `DetectionError` carrying the best-effort
  layout and the exact reasons.
- **Android-first** — reuses `cocbot.io` for capture; no duplicate ADB code.
- **Python 3.11+**, fully type-hinted, one new dependency (`anthropic`).

## Known limitations (honest)

- LLM determinism is best-effort: temperature 0 + deterministic registration
  make it reliable, but the vision step is not bit-guaranteed across model
  revisions. The grid/validation/wall-chain layers ARE fully deterministic.
- Corner detection assumes the bright diamond border is the largest bright
  contour; it is gated by `corner_confidence` (>=0.7) and will refuse rather than
  register against a bogus grid. Heavy UI overlays may need a cropped input.
- Traps require an editor-view screenshot; normal views emit an explicit warning.
