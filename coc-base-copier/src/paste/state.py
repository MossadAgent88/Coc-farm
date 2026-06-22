"""Idempotent paste-state persistence."""

from __future__ import annotations

import json
import signal
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from loguru import logger

PlacementStatus = Literal["placed", "skipped", "failed"]


@dataclass(frozen=True)
class PasteStateRecord:
    tile_x: int
    tile_y: int
    type: str
    status: PlacementStatus
    retry_count: int
    key: str
    error: str | None = None


class PasteState:
    def __init__(
        self,
        path: Path,
        layout_hash: str,
        records: list[PasteStateRecord] | None = None,
    ) -> None:
        self.path = path
        self.layout_hash = layout_hash
        self.records: list[PasteStateRecord] = records or []

    @classmethod
    def load_for_layout(
        cls,
        layout_path: str | Path,
        layout_hash: str,
        resume: bool = True,
        state_path: str | Path | None = None,
    ) -> "PasteState":
        path = Path(state_path) if state_path else Path(layout_path).with_name("paste_state.json")
        if not resume or not path.exists():
            return cls(path=path, layout_hash=layout_hash)

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"Could not read paste state {path}: {exc}; starting fresh")
            return cls(path=path, layout_hash=layout_hash)

        if raw.get("layout_hash") != layout_hash:
            logger.warning("Existing paste_state.json belongs to a different layout; starting fresh")
            return cls(path=path, layout_hash=layout_hash)

        records = [
            PasteStateRecord(
                tile_x=int(item["tile_x"]),
                tile_y=int(item["tile_y"]),
                type=str(item["type"]),
                status=item["status"],
                retry_count=int(item.get("retry_count", 0)),
                key=str(item.get("key") or _legacy_key(item)),
                error=item.get("error"),
            )
            for item in raw.get("records", [])
        ]
        logger.info(f"Resuming paste from {path}: {len(records)} state record(s)")
        return cls(path=path, layout_hash=layout_hash, records=records)

    def latest_by_key(self) -> dict[str, PasteStateRecord]:
        latest: dict[str, PasteStateRecord] = {}
        for record in self.records:
            latest[record.key] = record
        return latest

    def is_complete(self, key: str) -> bool:
        latest = self.latest_by_key().get(key)
        return latest is not None and latest.status in {"placed", "skipped"}

    def retry_count(self, key: str) -> int:
        latest = self.latest_by_key().get(key)
        return latest.retry_count if latest else 0

    def append(
        self,
        *,
        key: str,
        tile_x: int,
        tile_y: int,
        type: str,
        status: PlacementStatus,
        retry_count: int,
        error: str | None = None,
    ) -> None:
        self.records.append(
            PasteStateRecord(
                tile_x=tile_x,
                tile_y=tile_y,
                type=type,
                status=status,
                retry_count=retry_count,
                key=key,
                error=error,
            )
        )
        self.flush()

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "layout_hash": self.layout_hash,
            "records": [asdict(record) for record in self.records],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)


def install_flush_handlers(state: PasteState) -> None:
    def flush_and_raise(signum: int, _frame: object) -> None:
        logger.warning(f"Received signal {signum}; flushing paste state")
        state.flush()
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, flush_and_raise)


def _legacy_key(item: dict[str, object]) -> str:
    return f"{item.get('type')}:{item.get('tile_x')}:{item.get('tile_y')}"

