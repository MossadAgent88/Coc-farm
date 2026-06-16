# TODO

## Anti-Detection
- [x] Randomize click positions on Attack button, Find Match, Army Attack, Next, etc. (add jitter to UI button taps)
- [ ] Add active hours / play schedule (e.g. 8:00-1:00, auto-sleep overnight)
- [x] Session fatigue — gradually increase delays as session goes on
- [ ] Daily attack limit — cap attacks per day, auto-stop after hitting limit
- [x] Occasional idle cycles — 5-10% chance to just sit on home screen, zoom around, then close
- [ ] Camera scouting — random swipes/zooms on scout screen before committing to attack
- [x] Add more random events (zoom around base, check army, open builder menu)
- [x] Add check_connection_lost() call after every maybe_take_break() for mid-cycle recovery
- [ ] Add open_army.png template for army check random event

## Attack Strats
- [ ] Bottom-left attack variation (strat 4)
- [ ] Fine-tune bottom-right deploy positions based on live testing
- [ ] Test bottom-right camera swipe positioning with different base layouts

## GUI
- [ ] Switch to CustomTkinter or PyQt for proper background images and modern widgets
- [ ] Add live stats panel (total loot gained, attacks won/lost)
- [ ] Add log export / save button

## Cleanup
- [x] Remove debug log file (cocbot.log) or make it optional
- [ ] Remove overlay PNGs from repo (jitter_overlay.png, strat1/2_overlay.png, etc.)
