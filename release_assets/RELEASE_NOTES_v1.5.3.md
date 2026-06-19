# CoC Farm Bot v1.5.3 - Fast Broom Witch Event Spam + Every Hero & Spell

This release makes Broom Witch event farming **fast and efficient** and ensures
**every hero and every spell** in the preset is used correctly during event
attacks.

## What Changed

### Broom Witch event spam (fast + efficient)
- Rewrote `cocbot/event_broom.py` with a bounded, high-throughput deployment loop.
- Added `broom_witch_taps_per_point` so multiple Broom Witches drop per point per round, depleting the slot quickly.
- New pressure-point layout (`WIZARD_TOWER_PRESSURE_POINTS`) covers bottom-right, right/top-right, and left/top-left lanes for better Wizard Tower coverage.
- Rounds, taps per round, and taps per point are all configurable and bounded so the spam stays fast without becoming an instant-tap burst.
- Deployment is interruptible (Stop stays responsive) via chunked sleeps.
- Slot detection now prefers the live troop bar and falls back to configured slots if vision fails.

### Every hero is used
- `deploy_heroes()` now deploys Queen, Warden, Minion Prince, and Duke each on their own entry-point lanes.
- `activate_all_hero_abilities()` activates every hero ability:
  - Queen - Royal Cloak (immediate)
  - Warden - Eternal Tome (after configurable `warden_tome_delay`, default 3s)
  - Minion Prince - Dark Quill (post-deploy)
  - Duke - ability (post-deploy)
- Added configurable hero slot X positions for each hero.

### Every spell is used
- `deploy_all_spells()` now drops Rage, Heal, **and** Totem, each on its own distinct drop-point lane so effects do not stack on one tile.
- Added configurable spell slot X positions and counts for Rage, Heal, and Totem.

### Config additions
- `broom_witch_taps_per_point`, `queen_slot_x`, `king_slot_x`, `minion_prince_slot_x`, `duke_slot_x`
- `heal_slot_x`, `totem_slot_x`, `heal_spell_count`, `totem_spell_count`

### Tests
- Expanded `test_event_broom.py` to cover multi-tap spam, every-hero ability activation, every-spell-type deployment, live slot detection, and the new config fields.
- Full suite: 52 passed.

## Upgrade Notes
- Existing `settings.json` files keep working. New fields use safe defaults.
- To tune speed, set `broom_witch_max_rounds`, `broom_witch_taps_per_round`, and `broom_witch_taps_per_point` in `settings.json`.

## Disclaimer
This project is unofficial and is not affiliated with, endorsed by, sponsored by, or approved by Supercell. Clash of Clans is a trademark of Supercell. Use at your own risk.