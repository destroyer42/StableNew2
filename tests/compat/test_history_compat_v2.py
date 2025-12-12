from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.history.history_migration_engine import HistoryMigrationEngine
from src.history.history_record import HistoryRecord
from src.pipeline.legacy_njr_adapter import build_njr_from_history_dict
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot


FIXTURE_DIR = Path(__file__).resolve().parent / "data" / "history_compat_v2"
HISTORY_FIXTURES = [
    ("history_v2_0_pre_njr.jsonl", "v2.0"),
    ("history_v2_4_hybrid.jsonl", "v2.4"),
    ("history_v2_6_core1_pre.jsonl", "v2.6"),
]


@pytest.mark.parametrize("filename,version", HISTORY_FIXTURES)
def test_history_migration_engine_hydrates_legacy_entries(filename: str, version: str) -> None:
    fixture = FIXTURE_DIR / filename
    engine = HistoryMigrationEngine()
    for raw_line in fixture.read_text().splitlines():
        raw_entry = json.loads(raw_line)
        normalized = engine.migrate_entry(raw_entry)
        record = HistoryRecord.from_dict(normalized)

        assert record.id
        assert record.status
        assert record.history_schema == "2.6"
        assert record.njr_snapshot

        njr = normalized_job_from_snapshot({"normalized_job": record.njr_snapshot})
        assert njr is not None
        assert njr.job_id
        prompt = njr.positive_prompt or (njr.config.get("prompt") if hasattr(njr, "config") and isinstance(njr.config, dict) else None)
        assert prompt, f"Positive prompt missing in normalized NJR ({filename})"

        if version == "v2.6":
            assert isinstance(record.result, dict)


@pytest.mark.parametrize("filename,_", HISTORY_FIXTURES)
def test_legacy_adapter_hydrates_raw_entries(filename: str, _: str) -> None:
    fixture = FIXTURE_DIR / filename
    raw_entry = json.loads(fixture.read_text().splitlines()[0])
    njr = build_njr_from_history_dict(raw_entry)
    assert njr.job_id, "legacy adapter should provide job_id"
    prompt = njr.positive_prompt or njr.config.get("prompt")
    assert prompt, "legacy adapter should fill prompt"
