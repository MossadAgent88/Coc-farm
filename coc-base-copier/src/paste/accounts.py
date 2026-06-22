"""Multi-account configuration for the paster.

Each ``accounts/<name>.toml`` file describes one emulator/account. The file
format is a single ``[account.<key>]`` table:

    [account.main]
    name = "main"
    adb_serial = "emulator-5554"
    th_level = 14
    layout_dir = "layouts/main"

``load_account(name)`` resolves the account named ``name`` across every
``accounts/*.toml`` file and returns an :class:`AccountConfig`.
``list_accounts()`` enumerates all configured accounts so a UI/CLI can offer
them.

This module is pure (stdlib ``tomllib`` + ``pathlib`` only) — no ADB, no
network — so it is trivially unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tomllib


class AccountError(KeyError):
    """Raised when an account name cannot be resolved."""


@dataclass(frozen=True)
class AccountConfig:
    """One emulator/account's settings, loaded from accounts/<name>.toml."""

    name: str
    adb_serial: str
    th_level: int | None = None
    layout_dir: str | None = None


def _accounts_dir() -> Path:
    """The accounts/ directory next to the coc-base-copier package root."""
    # src/paste/accounts.py -> src/paste -> src -> coc-base-copier/accounts
    return Path(__file__).resolve().parents[2] / "accounts"


def _iter_account_files(root: Path | None = None) -> list[Path]:
    root = root if root is not None else _accounts_dir()
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*.toml") if p.is_file())


def list_accounts(root: Path | None = None) -> list[AccountConfig]:
    """Every account defined across all ``accounts/*.toml`` files.

    Sorted by name for stable display. Duplicate names across files resolve
    to the first definition encountered (alphabetical filename order).
    """
    seen: dict[str, AccountConfig] = {}
    for path in _iter_account_files(root):
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        table = data.get("account", {})
        if not isinstance(table, dict):
            continue
        for _key, entry in table.items():
            if not isinstance(entry, dict):
                continue
            cfg = _account_from_entry(entry)
            if cfg.name not in seen:
                seen[cfg.name] = cfg
    return [seen[k] for k in sorted(seen)]


def load_account(name: str, root: Path | None = None) -> AccountConfig:
    """Resolve a single account by its ``name`` field.

    Raises :class:`AccountError` if no account with that name is configured.
    """
    for cfg in list_accounts(root):
        if cfg.name == name:
            return cfg
    available = ", ".join(c.name for c in list_accounts(root)) or "(none)"
    raise AccountError(
        f"Account {name!r} not found in accounts/*.toml. Available: {available}"
    )


def _account_from_entry(entry: dict[str, object]) -> AccountConfig:
    """Build an AccountConfig from a raw TOML table, with light validation."""
    name = str(entry.get("name", "")).strip()
    adb_serial = str(entry.get("adb_serial", "")).strip()
    if not name:
        raise AccountError("account entry is missing 'name'")
    if not adb_serial:
        raise AccountError(f"account {name!r} is missing 'adb_serial'")
    th_level_raw = entry.get("th_level")
    layout_dir_raw = entry.get("layout_dir")
    return AccountConfig(
        name=name,
        adb_serial=adb_serial,
        th_level=int(th_level_raw) if th_level_raw is not None else None,
        layout_dir=str(layout_dir_raw) if layout_dir_raw is not None else None,
    )