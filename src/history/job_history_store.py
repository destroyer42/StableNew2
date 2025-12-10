from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.history.history_migration_engine import HistoryMigrationEngine
from src.history.history_record import DEFAULT_HISTORY_VERSION, HistoryRecord

_LEGACY_KEYS = {
    "pipeline_config",
    "draft",
    "bundle",
    "draft_bundle",
    "job_bundle",
    "bundle_summary",
}


def _strip_legacy(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        return {}
    return {k: v for k, v in snapshot.items() if k not in _LEGACY_KEYS}


class JobHistoryStore:
    """NJR-only JSONL history store with automatic legacy migration."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._migration = HistoryMigrationEngine()

    def load(self) -> list[HistoryRecord]:
        raw_entries = self._read_jsonl()
        migrated_entries = self._migration.migrate_all(raw_entries)
        return [self._hydrate_record(entry) for entry in migrated_entries]

    def save(self, entries: Iterable[HistoryRecord | Mapping[str, Any]]) -> None:
        serializable: list[dict[str, Any]] = []
        for entry in entries:
            record = entry if isinstance(entry, HistoryRecord) else HistoryRecord.from_dict(entry)
            data = record.to_dict()
            data["history_version"] = DEFAULT_HISTORY_VERSION
            data["njr_snapshot"] = _strip_legacy(data.get("njr_snapshot"))
            serializable.append(data)
        self._write_jsonl(serializable)

    def append(self, record: HistoryRecord | Mapping[str, Any]) -> None:
        entries = self.load()
        history_record = record if isinstance(record, HistoryRecord) else HistoryRecord.from_dict(record)
        entries.append(history_record)
        self.save(entries)

    def _hydrate_record(self, data: Mapping[str, Any]) -> HistoryRecord:
        return HistoryRecord.from_dict(data)

    def _read_jsonl(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        entries: list[dict[str, Any]] = []
        for line in lines:
            if not line:
                continue
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    entries.append(parsed)
            except Exception:
                continue
        return entries

    def _write_jsonl(self, entries: Iterable[Mapping[str, Any]]) -> None:
        lines = []
        for entry in entries:
            data = dict(entry)
            data["history_version"] = DEFAULT_HISTORY_VERSION
            data["njr_snapshot"] = _strip_legacy(data.get("njr_snapshot"))
            lines.append(json.dumps(data, ensure_ascii=True))
        self._path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
