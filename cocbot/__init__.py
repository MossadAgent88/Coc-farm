"""CoC Farm Bot package.

Versioning policy
-----------------
The GUI/updater reads this value at runtime and compares it with GitHub Release
tags (for example: local ``1.5.2`` vs remote ``v1.5.3``).

Bump this before publishing a new Release asset, otherwise the in-app updater
will correctly report "up to date" even if you uploaded a new executable.
"""

# Keep a single source of truth for app/version display + updater comparison.
# Semantic versioning:
# PATCH = bug fix / template tweak / tuning change
# MINOR = new feature (attack scheme, GUI control, event type)
# MAJOR = breaking change (resolution target, settings.json schema break)
__version__ = "1.5.8"
