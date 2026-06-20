# v1.5.6 — GUI bug-fix & data cleanup

Focused bug-fix release. No deployment-logic or design changes.

## Fixed
- **Log Copy** now actually copies. Reliable chain (backend clipboard → async
  Clipboard API → execCommand fallback); shows real "Copied ✓" or a real error
  toast instead of faking success. Copies the visible (filtered) log lines.
- **Debug Preview** shows real screenshots from `debug/runtime/`, `debug/`,
  `debug_screenshots/` and `screenshots/` (source + frozen safe). Removed the
  fake `cap_00X.png` placeholders. Clean "No debug screenshots yet" empty state.

## Changed
- **Army preset dropdown** is generated from backend-supported presets only.
  Removed unsupported `super_archer`, `barch`, `dragon_loon`, `hog_rider`.
  Only `broom_witch` and `electro_dragon` are shown; default `broom_witch`.
- Invalid/old presets in `settings.json` migrate with a logged warning
  (`broom_witches → broom_witch`, `E-Drag Spam → electro_dragon`, unknown →
  `broom_witch`), in both backend (`config.load_config`) and the GUI.
- Selected `army_preset` is saved/loaded using the backend key (not display
  text); dropdown, header label and equipment panel stay in sync.

## Added
- **Army Equipment panel** per preset: troops / heroes / spells / siege machine,
  supported Town Halls, and notes — sourced from the real `ARMY_PRESETS`
  deployment lists (`cocbot/army_catalog.py`). Picking an unsupported TH shows
  "Not supported for this TH".
- Backend bridge methods: `copy_text`, `list_debug_screenshots`, `army_presets`;
  in-process `/__shots__/<token>` image route (path-validated).
- `test_army_catalog.py` sanity tests.

## Note
- This source release does not include a prebuilt Windows EXE asset. The in-app
  updater looks for a Windows asset on the latest Release; build and attach
  `dist\CoCBot.exe` (via `build.bat`) for the updater to offer it.
