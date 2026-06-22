## Fast Broom Witch spam
- Added a new **`batch_tap()`** helper in `cocbot/io.py` that chains many taps into a **single `adb shell input` call**, eliminating the per-tap subprocess spawn that previously made Broom Witch deployment painfully slow.
- Each Broom Witch round now drops its slot-select + all pressure-point taps in **one fast burst** instead of N separate ADB invocations.

## Every hero & spell used correctly
- **Heroes** (Queen, Warden, Minion Prince, Duke) now deploy via `batch_tap` — the slot-select and entry-point taps land in a single ADB call.
- **Spells** (Rage, Heal, Totem) now deploy via `batch_tap` — the slot-select and all spell drops land in one burst, and each spell type uses a distinct drop-point lane.
- **Hero abilities** are batch-activated for all non-Warden heroes in one ADB call.

## Bug fix: Warden Eternal Tome double-delay
- The Warden's Eternal Tome was firing at `hero_ability_delay + tome_delay` (~5.5s) instead of just `tome_delay` (3.0s). Fixed with a new `skip_delay` flag so the Tome now fires at the configured time.

## Tests & cleanup
- Updated `test_event_broom.py` for the new batched-tap implementation.
- Stripped pre-existing null-byte corruption from `test_actions.py`, `test_config.py`, `test_plans.py`, `test_session.py`, `test_loop.py`.
- Dropped the redundant in-app titlebar in the web GUI (native window chrome is used).
- **All 52 tests pass.**