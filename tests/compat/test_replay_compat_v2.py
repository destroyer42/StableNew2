from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.history.history_migration_engine import HistoryMigrationEngine
from src.history.history_record import HistoryRecord
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot


FIXTURE_DIR = Path(__file__).resolve().parent / "data" / "history_compat_v2"
HISTORY_FIXTURES = [
    "history_v2_0_pre_njr.jsonl",
    "history_v2_4_hybrid.jsonl",
    "history_v2_6_core1_pre.jsonl",
]


@pytest.mark.parametrize("filename", HISTORY_FIXTURES)
def test_replay_migrated_entries_can_instantiate_njr(filename: str) -> None:
    fixture = FIXTURE_DIR / filename
    engine = HistoryMigrationEngine()
    for raw_line in fixture.read_text().splitlines():
        raw_entry = json.loads(raw_line)
        normalized = engine.migrate_entry(raw_entry)

        record = HistoryRecord.from_dict(normalized)
        njr = normalized_job_from_snapshot({"normalized_job": record.njr_snapshot})

        assert njr.job_id, "Replay entry must have job_id"
        assert njr.positive_prompt or njr.config.get("prompt"), "Replay entry must expose a prompt"
        assert record.history_schema == "2.6"
        assert isinstance(record.result, dict) or record.result is None
