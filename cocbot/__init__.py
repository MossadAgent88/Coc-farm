"""CoC bot — vision-based Clash of Clans automation.

Layer boundaries (one-way imports, no cycles):

    io  ──▶  vision  ──▶  actions  ──▶  loop
                              ▲              │
                              │              ▼
                           plans          config / session / debug

- io:       ADB primitives (capture, tap, swipe, launch, zoom)
- vision:   pure image → answer (find_template, read_loot, etc.)
- actions:  composite primitives (go_home, deploy_troops, search_for_good_loot)
- plans:    DeployPlan dataclass + LEFT / RIGHT / BOTTOM_RIGHT instances
- loop:     run_attack, run_loop, break/event scheduling, random events
- config:   BotConfig + cfg singleton
- session:  BotSession + deadline() context manager
- debug:    DebugContext + dbg singleton
"""

# Single source of truth for the build version.
# Bump manually when cutting a new build (GUI exe, shared package).
# SemVer: MAJOR.MINOR.PATCH
#   PATCH = bug fix / template tweak / tuning change
#   MINOR = new feature (attack scheme, GUI control, event type)
#   MAJOR = breaking change (resolution target, settings.json schema break)
__version__ = "1.3.1"

