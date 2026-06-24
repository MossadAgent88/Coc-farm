"""Mocked unit tests for the updater's asset detection, SHA256 parsing, and
version/asset logic. No network access required."""

from __future__ import annotations

import json

import pytest

from cocbot import updater


# ---------------------------------------------------------------------------
# _choose_asset
# ---------------------------------------------------------------------------


def _asset(name, url=None):
    return {"name": name, "browser_download_url": url or f"https://x/{name}"}


def test_choose_asset_prefers_coc_farm_windows_zip():
    assets = [
        _asset("CoC-Farm-Bot-Windows.zip"),
        _asset("CoC-Farm-Bot-Windows.zip.sha256"),
        _asset("source-code.tar.gz"),
        _asset("ghost-farm-lambda.zip"),
    ]
    chosen = updater._choose_asset(assets)
    assert chosen is not None
    assert chosen["name"] == "CoC-Farm-Bot-Windows.zip"
    assert chosen["kind"] == "zip"


def test_choose_asset_legacy_exe_fallback():
    """Older releases without a ZIP should still resolve to the legacy EXE."""
    assets = [_asset("coc-farm.exe"), _asset("notes.txt")]
    chosen = updater._choose_asset(assets)
    assert chosen is not None
    assert chosen["name"] == "coc-farm.exe"
    assert chosen["kind"] == "exe"


def test_choose_asset_missing_returns_none():
    assets = [_asset("source.tar.gz"), _asset("README.md")]
    assert updater._choose_asset(assets) is None


# ---------------------------------------------------------------------------
# _parse_sha256_from_notes
# ---------------------------------------------------------------------------

_HEX = "a" * 64


def test_parse_sha256_labelled():
    assert updater._parse_sha256_from_notes(f"SHA256: {_HEX}") == _HEX


def test_parse_sha256_sha256sum_style():
    body = f"{_HEX}  CoC-Farm-Bot-Windows.zip\n"
    assert updater._parse_sha256_from_notes(body) == _HEX


def test_parse_sha256_bare_hex_line():
    assert updater._parse_sha256_from_notes(f"some intro\n{_HEX}\nmore") == _HEX


def test_parse_sha256_missing_returns_none():
    assert updater._parse_sha256_from_notes("nothing here") is None
    assert updater._parse_sha256_from_notes("") is None
    assert updater._parse_sha256_from_notes(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _find_sha256_sidecar
# ---------------------------------------------------------------------------


def test_find_sha256_sidecar():
    assets = [_asset("CoC-Farm-Bot-Windows.zip"), _asset("CoC-Farm-Bot-Windows.zip.sha256", "https://sidecar")]
    assert updater._find_sha256_sidecar(assets) == "https://sidecar"


def test_find_sha256_sidecar_missing():
    assets = [_asset("CoC-Farm-Bot-Windows.zip")]
    assert updater._find_sha256_sidecar(assets) is None


# ---------------------------------------------------------------------------
# check_for_update (mocked urlopen)
# ---------------------------------------------------------------------------


def _fake_release(tag, assets, body=""):
    return {
        "tag_name": tag,
        "assets": assets,
        "body": body,
    }


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._data).encode()


def _patch_urlopen(monkeypatch, data):
    def fake_urlopen(req, timeout=None):
        return _FakeResp(data)
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)


def test_check_for_update_up_to_date_returns_none(monkeypatch):
    # cocbot.__version__ is something like "1.5.7"; use a same-or-lower tag.
    from cocbot import __version__
    same_tag = "v" + __version__
    _patch_urlopen(monkeypatch, _fake_release(same_tag, [_asset("CoC-Farm-Bot-Windows.zip")]))
    assert updater.check_for_update() is None


def test_check_for_update_missing_asset_raises(monkeypatch):
    _patch_urlopen(
        monkeypatch,
        _fake_release("v99.0.0", [_asset("source.tar.gz"), _asset("README.md")]),
    )
    with pytest.raises(updater.NoAssetError) as exc:
        updater.check_for_update()
    assert "No Windows ZIP asset" in str(exc.value)


def test_check_for_update_returns_info(monkeypatch):
    assets = [
        _asset("CoC-Farm-Bot-Windows.zip", "https://zip"),
        _asset("CoC-Farm-Bot-Windows.zip.sha256", "https://sidecar"),
    ]
    body = f"SHA256: {_HEX}\nrelease notes"
    _patch_urlopen(monkeypatch, _fake_release("v99.0.0", assets, body=body))
    info = updater.check_for_update()
    assert info is not None
    assert info["version"] == "99.0.0"
    assert info["asset_name"] == "CoC-Farm-Bot-Windows.zip"
    assert info["kind"] == "zip"
    assert info["sha256"] == _HEX
    assert info["sha256_url"] == "https://sidecar"


# ---------------------------------------------------------------------------
# fetch_sha256_from_sidecar (mocked urlopen)
# ---------------------------------------------------------------------------


import io


class _FakeBytesResp:
    """Context manager yielding a real stream so shutil.copyfileobj works."""

    def __init__(self, raw: bytes):
        self._raw = raw

    def __enter__(self):
        return io.BytesIO(self._raw)

    def __exit__(self, *a):
        return False


def test_fetch_sha256_from_sidecar_parses_hash(monkeypatch):
    payload = f"{_HEX}  CoC-Farm-Bot-Windows.zip\n".encode()
    monkeypatch.setattr(
        updater.urllib.request, "urlopen", lambda req, timeout=None: _FakeBytesResp(payload)
    )
    assert updater.fetch_sha256_from_sidecar("https://sidecar") == _HEX


# ---------------------------------------------------------------------------
# _download: SHA256 mismatch aborts
# ---------------------------------------------------------------------------


def test_download_aborts_on_sha256_mismatch(monkeypatch, tmp_path):
    blob = b"x" * 200_000  # above the 100KB sanity floor
    monkeypatch.setattr(
        updater.urllib.request, "urlopen", lambda req, timeout=None: _FakeBytesResp(blob)
    )
    dest = tmp_path / "update.zip"
    with pytest.raises(RuntimeError) as exc:
        updater._download("https://zip", dest, timeout=5, expected_sha256="b" * 64)
    assert "SHA256 mismatch" in str(exc.value)


def test_download_accepts_matching_sha256(monkeypatch, tmp_path):
    import hashlib

    blob = b"y" * 200_000
    good = hashlib.sha256(blob).hexdigest()
    monkeypatch.setattr(
        updater.urllib.request, "urlopen", lambda req, timeout=None: _FakeBytesResp(blob)
    )
    dest = tmp_path / "update.zip"
    updater._download("https://zip", dest, timeout=5, expected_sha256=good)  # no raise
    assert dest.read_bytes() == blob


# ---------------------------------------------------------------------------
# Swap script preserves user data (robocopy /XF /XD)
# ---------------------------------------------------------------------------


def test_zip_swap_script_preserves_user_files(tmp_path):
    script = updater._zip_swap_script(
        payload_dir=tmp_path / "payload",
        folder=tmp_path / "app",
        launch_exe=tmp_path / "app" / "Coc-farm.exe",
        temp_root=tmp_path / "tmp",
        exe_name="Coc-farm.exe",
    )
    # user data must be excluded from the /MIR mirror, or it would be deleted
    assert "/MIR" in script
    assert "/XF settings.json bases.json armies.json *.log" in script
    assert "/XD logs debug screenshots" in script
    # waits for the running EXE to close before swapping, then relaunches
    assert "waitlock" in script
    assert 'start "" "' in script