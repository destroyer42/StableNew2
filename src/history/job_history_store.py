from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from src.history.history_record import HistoryRecord
from src.history.history_schema_v26 import (
    ALLOWED_FIELDS,
    HISTORY_SCHEMA_VERSION,
    HistorySchemaError,
    validate_entry,
)
from src.utils.jsonl_codec import JSONLCodec

logger = logging.getLogger(__name__)

# PR-PERSIST-001: History archival constants
MAX_ACTIVE_ENTRIES = 100
ARCHIVE_SUFFIX = "_archive.jsonl"


class JobHistoryStore:
    """NJR-only JSONL history store (strict v2.6 schema)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._codec = JSONLCodec(schema_validator=validate_entry, logger=logger.warning)

    def load(self) -> list[HistoryRecord]:
        raw_entries = self._codec.read_jsonl(self._path)
        hydrated: list[HistoryRecord] = []
        for entry in raw_entries:
            ok, errors = validate_entry(entry)
            if not ok:
                logger.warning("Dropping invalid history entry: %s", errors)
                continue
            hydrated.append(self._hydrate_record(entry))
        return hydrated

    def save(self, entries: Iterable[HistoryRecord | Mapping[str, Any]]) -> None:
        serializable: list[dict[str, Any]] = []
        for entry in entries:
            record = entry if isinstance(entry, HistoryRecord) else HistoryRecord.from_dict(entry)
            normalized = record.to_dict()
            ok, errors = validate_entry(normalized)
            if not ok:
                raise HistorySchemaError(errors)
            serializable.append(self._order_entry(normalized))
        self._codec.write_jsonl(self._path, serializable)

    def append(self, record: HistoryRecord | Mapping[str, Any]) -> None:
        entries = self.load()
        history_record = (
            record if isinstance(record, HistoryRecord) else HistoryRecord.from_dict(record)
        )
        entries.append(history_record)
        self.save(entries)
        
        # PR-PERSIST-001: Auto-archive if we exceed MAX_ACTIVE_ENTRIES
        if len(entries) > MAX_ACTIVE_ENTRIES:
            self.archive_old_entries()

    def archive_old_entries(self) -> int:
        """Move entries beyond MAX_ACTIVE_ENTRIES to archive file.
        
        Returns:
            Number of entries archived
        """
        entries = self.load()
        if len(entries) <= MAX_ACTIVE_ENTRIES:
            return 0
        
        # Split into active and to-be-archived
        active = entries[-MAX_ACTIVE_ENTRIES:]
        to_archive = entries[:-MAX_ACTIVE_ENTRIES]
        
        # Append to archive file
        archived_count = self._append_to_archive(to_archive)
        
        # Save only active entries
        self.save(active)
        
        logger.info(
            "Archived %d old history entries (keeping last %d active)",
            archived_count,
            len(active)
        )
        return archived_count

    def _append_to_archive(self, entries: list[HistoryRecord]) -> int:
        """Append entries to the archive file."""
        if not entries:
            return 0
        
        archive_path = self._get_archive_path()
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing archive (if any)
        existing_archive: list[dict[str, Any]] = []
        if archive_path.exists():
            try:
                existing_archive = self._codec.read_jsonl(archive_path)
            except Exception as e:
                logger.warning("Failed to load existing archive: %s", e)
        
        # Append new entries
        for entry in entries:
            normalized = entry.to_dict()
            existing_archive.append(self._order_entry(normalized))
        
        # Write back to archive
        try:
            self._codec.write_jsonl(archive_path, existing_archive)
            return len(entries)
        except Exception as e:
            logger.error("Failed to write to archive: %s", e)
            return 0

    def _get_archive_path(self) -> Path:
        """Get the archive file path based on the main history file."""
        stem = self._path.stem
        return self._path.parent / f"{stem}{ARCHIVE_SUFFIX}"

    def load_archive(self) -> list[HistoryRecord]:
        """Load archived history entries (read-only)."""
        archive_path = self._get_archive_path()
        if not archive_path.exists():
            return []
        
        try:
            raw_entries = self._codec.read_jsonl(archive_path)
            hydrated: list[HistoryRecord] = []
            for entry in raw_entries:
                ok, errors = validate_entry(entry)
                if not ok:
                    logger.warning("Dropping invalid archive entry: %s", errors)
                    continue
                hydrated.append(self._hydrate_record(entry))
            return hydrated
        except Exception as e:
            logger.error("Failed to load archive: %s", e)
            return []

    def _hydrate_record(self, data: Mapping[str, Any]) -> HistoryRecord:
        return HistoryRecord.from_dict(data)

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
            "result",
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
        data.setdefault("result", {})
        return data
