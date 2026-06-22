from __future__ import annotations

import json

from src.copy import __main__ as copy_cli
from src.copy.schema import Layout, LayoutObject, SourceInfo, WallChain


def test_copy_cli_writes_layout_json_and_summary(monkeypatch, tmp_path, capsys):
    screenshot = tmp_path / "village.png"
    screenshot.write_bytes(b"not a real png; detect is mocked")
    output = tmp_path / "layout.json"

    layout = Layout(
        source=SourceInfo(kind="screenshot", image_width=1920, image_height=1080),
        objects=[
            LayoutObject(
                id="obj_0000",
                category="defense",
                type="town_hall",
                tile_x=20,
                tile_y=20,
                confidence=0.9,
            ),
            LayoutObject(
                id="obj_0001",
                category="trap",
                type="bomb",
                tile_x=21,
                tile_y=20,
                confidence=0.8,
            ),
        ],
        wall_chains=[
            WallChain(id="wall_00", tiles=[(1, 1), (2, 1)], confidence=0.7),
        ],
    )
    monkeypatch.setattr(copy_cli, "detect", lambda path: layout)

    assert copy_cli.main([str(screenshot), str(output)]) == 0

    written = json.loads(output.read_text(encoding="utf-8"))
    assert written == layout.to_dict()
    out = capsys.readouterr().out
    assert "2 objects, 1 wall_chains, 1 traps" in out
    assert "schema_version=1.1.0" in out
    assert "confidence_avg=0.800" in out


def test_copy_cli_returns_two_for_anthropic_errors(monkeypatch, tmp_path, capsys):
    class InternalServerError(RuntimeError):
        pass

    InternalServerError.__module__ = "anthropic"

    screenshot = tmp_path / "village.png"
    screenshot.write_bytes(b"not a real png; detect is mocked")

    def raise_error(path):
        raise InternalServerError("502 Bad Gateway")

    monkeypatch.setattr(copy_cli, "detect", raise_error)

    assert copy_cli.main([str(screenshot)]) == 2
    assert "anthropic.InternalServerError: 502 Bad Gateway" in capsys.readouterr().err
