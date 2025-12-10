from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.history.history_migration_engine import HistoryMigrationEngine
from src.history.history_record import HistoryRecord
from src.history.history_schema_v26 import (
    ALLOWED_FIELDS,
    HISTORY_SCHEMA_VERSION,
    HistorySchemaError,
    validate_entry,
)


class JobHistoryStore:
    """NJR-only JSONL history store with automatic legacy migration."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._migration = HistoryMigrationEngine()

    def load(self) -> list[HistoryRecord]:
        raw_entries = self._read_jsonl()
        migrated_entries = self._migration.migrate_all(raw_entries)
        validated: list[dict[str, Any]] = []
        for entry in migrated_entries:
            ok, errors = validate_entry(entry)
            if not ok:
                raise HistorySchemaError(errors)
            validated.append(entry)
        return [self._hydrate_record(entry) for entry in validated]

    def save(self, entries: Iterable[HistoryRecord | Mapping[str, Any]]) -> None:
        serializable: list[dict[str, Any]] = []
        for entry in entries:
            record = entry if isinstance(entry, HistoryRecord) else HistoryRecord.from_dict(entry)
            normalized = self._migration.normalize_schema(record.to_dict())
            ok, errors = validate_entry(normalized)
            if not ok:
                raise HistorySchemaError(errors)
            serializable.append(self._order_entry(normalized))
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
            data = self._order_entry(entry)
            lines.append(json.dumps(data, ensure_ascii=True))
        self._path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def _order_entry(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        """Return entry with deterministic key ordering per schema."""
        ordered_keys = [
            "id",
            "timestamp",
            "status",
            "history_schema",
            "njr_snapshot",
            "ui_summary",
            "metadata",
            "runtime",
        ]
        data = {k: entry[k] for k in ordered_keys if k in entry}
        # Preserve transitional history_version if present for compatibility
        if "history_version" in entry:
            data["history_version"] = entry["history_version"]
        # Drop unknown keys defensively
        for key in list(data.keys()):
            if key not in ALLOWED_FIELDS:
                data.pop(key, None)
        # Ensure defaults exist
        data.setdefault("history_schema", HISTORY_SCHEMA_VERSION)
        data.setdefault("ui_summary", {})
        data.setdefault("metadata", {})
        data.setdefault("runtime", {})
        return data
