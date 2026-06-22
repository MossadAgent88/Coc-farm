# Sample input for the base copier

The upstream repo ships only attack-flow screenshots (attack button, find-match,
end-battle, return-home) -- there is **no full village layout screenshot** to run
against, so this folder is a placeholder describing the expected input.

## Expected input

- A **single PNG/JPG screenshot** of one CoC village, captured at the emulator's
  native resolution (the repo's `cocbot.io.capture_screenshot` produces **1920x1080
  BGR**). Other resolutions work too -- registration is geometric -- but 1920x1080
  is the tuned target.
- The whole diamond playable area must be visible and reasonably centered
  (zoom out fully). The detector locates the bright diamond border to register
  the 44x44 grid.
- **Prefer the editor / "Edit Layout" view.** Traps are invisible in the normal
  village view; in the editor they are visible and the detector can place them.
  When given a normal view, the detector still works but emits a warning that
  traps were not recoverable (it never pretends the base is trap-free).

## How to run

```bash
# from the repo root, with ANTHROPIC_API_KEY set:
python -m src.copy.detect samples/your_village.png --out layout.json

# or live from the connected emulator (reuses the existing ADB layer):
python -c "from src.copy.detect import detect_from_device; \
           print(detect_from_device().to_json())"
```

Drop a real `your_village.png` here to try it; output conforms to
`docs/layout-schema.md`.
