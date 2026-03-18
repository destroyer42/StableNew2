from __future__ import annotations

import json
from pathlib import Path

from src.history.history_schema_v26 import HISTORY_SCHEMA_VERSION, validate_entry
from src.history.job_history_store import JobHistoryStore


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def test_roundtrip_normalizes_and_preserves_entries(tmp_path) -> None:
    history_path = tmp_path / "history.jsonl"
    entries = [
        {
            "id": "snapshot-002",
            "status": "completed",
            "timestamp": "2026-03-16T00:00:00Z",
            "history_schema": HISTORY_SCHEMA_VERSION,
            "snapshot": {
                "normalized_job": {
                    "job_id": "snapshot-002",
                    "positive_prompt": "sky",
                    "config": {"prompt": "sky"},
                }
            },
            "ui_summary": {},
            "metadata": {},
            "runtime": {},
        },
    ]
    _write_jsonl(history_path, entries)

    store = JobHistoryStore(history_path)
    first = store.load()
    store.save(first)
    second = store.load()

    first_dicts = [r.to_dict() for r in first]
    second_dicts = [r.to_dict() for r in second]

    assert first_dicts == second_dicts
    for entry in second_dicts:
        ok, errors = validate_entry(entry)
        assert ok, errors
        assert entry["history_schema"] == HISTORY_SCHEMA_VERSION
