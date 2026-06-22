# Coc-farm Base Copier v1.0.0

Copy a Clash of Clans base from a screenshot and paste it into your own village
editor. The **detector** (`src/copy/`) reads a screenshot, calls Claude Vision to
find every building, and writes a tile-accurate `layout.json` (schema
[`docs/layout-schema.md`](docs/layout-schema.md), `v1.1.0`). The **paster**
(`src/paste/`) loads that JSON, opens the in-game village editor on an emulator
via ADB, and places each building and wall chain in the right tile.

## Install

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."   # Windows: set ANTHROPIC_API_KEY=...
```

## Prerequisites

- **LDPlayer** (or any Android emulator) running at **1920×1080**.
- **ADB connected** (`adb devices` shows your emulator, e.g. `emulator-5554`).
- Clash of Clans open with your village in **normal view** for *detection* —
  not photo mode, not the editor.
- The village **zoomed fully out** so the full play-area diamond is visible.
- For *pasting*, open the in-game **village editor** (the paster drives the
  editor UI itself).

## Quick start

Detect from a screenshot and paste it in one command:

```bash
python -m src.paste --roundtrip village.png
```

### Step by step

```bash
# 1. Detect buildings + walls from a screenshot -> layout.json
python -m src.copy village.png village.json

# 2. Paste the layout into your village editor
python -m src.paste village.json

# Preview the placement plan without touching ADB
python -m src.paste --dry-run village.json

# Resume an interrupted paste (continues from paste_state.json)
python -m src.paste --resume village.json

# Target a specific emulator
python -m src.paste --device emulator-5554 village.json
```

## Layout schema

The detector output and paster input is documented in
[`docs/layout-schema.md`](docs/layout-schema.md) (**schema `v1.1.0`**). Buildings
are placed on a 44×44 tile grid using the canonical type keys and footprints in
[`src/copy/schema.py`](src/copy/schema.py).

## Troubleshooting

| Error | Cause / Fix |
|-------|-------------|
| `GridRegistrationError` | The diamond grid corners couldn't be locked. **Zoom out more** so all four corners of the play area are visible, then re-capture. |
| `DetectionError: no town_hall` | The detector couldn't find a Town Hall. Usually a bad/partial screenshot. **Retry** with a clean, fully-zoomed-out capture. |
| `EditorModeError` | The paster didn't see the village editor. Capture a fresh editor screenshot and place it under `assets/editor/`; see the templates already there. |
| `anthropic.InternalServerError` | Transient upstream error from the API. **Just re-run** — detection is idempotent. |
| `0 wall chains` when the detector reported `N` walls | Known wall-grouping regression — fixed in the next patch (if not already fixed by Codex). See `NOTES.md`. |

## Limitations

- **English UI only.** Editor-button templates are matched against the English
  client.
- **Single village per run.** One screenshot in, one paste out. Use
  `--account <name>` (see `accounts/`) to switch emulators between runs.
- **Requires an Anthropic API key** for the single Claude Vision call during
  detection. Pasting alone (`src.paste`) does not call the API.