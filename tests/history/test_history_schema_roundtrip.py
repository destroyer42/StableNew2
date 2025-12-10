from __future__ import annotations

import json
from pathlib import Path

from src.history.job_history_store import JobHistoryStore
from src.history.history_schema_v26 import HISTORY_SCHEMA_VERSION, validate_entry


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def test_roundtrip_normalizes_and_preserves_entries(tmp_path) -> None:
    history_path = tmp_path / "history.jsonl"
    legacy_entries = [
        {
            "job_id": "legacy-001",
            "pipeline_config": {"prompt": "ancient job", "model": "v1", "sampler": "Euler a"},
        },
        {
            "id": "snapshot-002",
            "status": "completed",
            "snapshot": {"normalized_job": {"job_id": "snapshot-002", "positive_prompt": "sky"}},
        },
    ]
    _write_jsonl(history_path, legacy_entries)

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
