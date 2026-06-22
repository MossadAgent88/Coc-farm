"""Tests for multi-account config (pure stdlib only)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.paste.accounts import (
    AccountConfig,
    AccountError,
    list_accounts,
    load_account,
)


def _write_accounts(tmp_path: Path, body: str, name: str = "test.toml") -> Path:
    (tmp_path / name).write_text(textwrap.dedent(body), encoding="utf-8")
    return tmp_path


def test_load_account_returns_config(tmp_path: Path):
    _write_accounts(
        tmp_path,
        """
        [account.main]
        name = "main"
        adb_serial = "emulator-5554"
        th_level = 14
        layout_dir = "layouts/main"
        """,
    )
    cfg = load_account("main", root=tmp_path)
    assert isinstance(cfg, AccountConfig)
    assert cfg.name == "main"
    assert cfg.adb_serial == "emulator-5554"
    assert cfg.th_level == 14
    assert cfg.layout_dir == "layouts/main"


def test_load_account_missing_raises(tmp_path: Path):
    _write_accounts(tmp_path, '[account.main]\nname="main"\nadb_serial="x"\n')
    with pytest.raises(AccountError):
        load_account("does_not_exist", root=tmp_path)


def test_list_accounts_sorted_by_name(tmp_path: Path):
    _write_accounts(
        tmp_path,
        """
        [account.zeta]
        name = "zeta"
        adb_serial = "emulator-2"
        [account.alpha]
        name = "alpha"
        adb_serial = "emulator-1"
        """,
        name="multi.toml",
    )
    names = [c.name for c in list_accounts(root=tmp_path)]
    assert names == ["alpha", "zeta"]


def test_optional_fields_default_none(tmp_path: Path):
    _write_accounts(
        tmp_path,
        """
        [account.min]
        name = "min"
        adb_serial = "emulator-9"
        """,
    )
    cfg = load_account("min", root=tmp_path)
    assert cfg.th_level is None
    assert cfg.layout_dir is None


def test_missing_adb_serial_raises(tmp_path: Path):
    _write_accounts(tmp_path, '[account.bad]\nname = "bad"\n')
    with pytest.raises(AccountError):
        list_accounts(root=tmp_path)