from __future__ import annotations

import json

from src.history.history_migration_engine import HistoryMigrationEngine
from src.history.history_schema_v26 import (
    DEPRECATED_FIELDS,
    HISTORY_SCHEMA_VERSION,
    REQUIRED_FIELDS,
    validate_entry,
)


def _legacy_entries():
    return [
        {
            "job_id": "v1-job",
            "pipeline_config": {"prompt": "old", "model": "v1", "sampler": "Euler"},
            "legacy_job": True,
        },
        {
            "job_id": "v2-job",
            "snapshot": {"normalized_job": {"job_id": "v2-job", "positive_prompt": "tree"}},
            "draft_bundle_summary": {"foo": "bar"},
        },
        {
            "id": "v25-job",
            "status": "completed",
            "njr_snapshot": {"job_id": "v25-job", "positive_prompt": "castle"},
            "job_bundle_summary": {"bar": "baz"},
        },
        {
            "id": "v26-job",
            "history_schema": "2.6",
            "njr_snapshot": {"job_id": "v26-job", "positive_prompt": "sky"},
            "ui_summary": {},
            "metadata": {},
            "runtime": {},
        },
    ]


def test_migration_compacts_mixed_entries() -> None:
    engine = HistoryMigrationEngine()
    entries = _legacy_entries()
    migrated = engine.migrate_all(entries)
    compacted = [engine.normalize_schema(e) for e in migrated]

    for entry in compacted:
        ok, errors = validate_entry(entry)
        assert ok, errors
        assert entry["history_schema"] == HISTORY_SCHEMA_VERSION
        assert set(DEPRECATED_FIELDS).isdisjoint(entry.keys())
        for field in REQUIRED_FIELDS:
            assert field in entry
        assert isinstance(entry.get("ui_summary"), dict)
        assert isinstance(entry.get("metadata"), dict)
        assert isinstance(entry.get("runtime"), dict)

    # Idempotence and deterministic ordering
    serialized = [json.dumps(e, sort_keys=True) for e in compacted]
    compacted_again = [engine.normalize_schema(e) for e in compacted]
    serialized_again = [json.dumps(e, sort_keys=True) for e in compacted_again]
    assert serialized_again == serialized
