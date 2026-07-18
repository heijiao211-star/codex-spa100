from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


class HistoryStore:
    """JSON history with deterministic replacement by the documented unique key."""

    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data.get("records", []) if isinstance(data, dict) else []

    def upsert(self, records: list[dict[str, Any]]) -> None:
        existing = self._load()
        index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for record in existing + records:
            key = (
                str(record.get("fund_code")),
                str(record.get("data_type")),
                str(record.get("data_date")),
                str(record.get("source_name")),
            )
            index[key] = record
        atomic_write_json(
            self.path,
            {
                "schema_version": "2.0",
                "records": [index[key] for key in sorted(index)],
            },
        )

