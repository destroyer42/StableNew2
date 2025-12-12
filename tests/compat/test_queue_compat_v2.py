from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.services.queue_store_v2 import QueueMigrationEngine, load_queue_snapshot
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot


FIXTURE_DIR = Path(__file__).resolve().parent / "data" / "queue_compat_v2"
QUEUE_FIXTURES = [
    ("queue_state_v2_0.json", "v2.0"),
    ("queue_state_v2_4_hybrid.json", "v2.4"),
    ("queue_state_v2_6_core1_pre.json", "v2.6"),
]


@pytest.mark.parametrize("filename,version", QUEUE_FIXTURES)
def test_queue_state_snapshot_loads(tmp_path: Path, filename: str, version: str) -> None:
    fixture = FIXTURE_DIR / filename
    dest = tmp_path / "queue_state.json"
    shutil.copy(fixture, dest)

    snapshot = load_queue_snapshot(dest)
    assert snapshot is not None, f"failed to load {filename}"
    assert snapshot.schema_version == "2.6"
    assert isinstance(snapshot.jobs, list)
    assert snapshot.jobs, "no jobs normalized"

    engine = QueueMigrationEngine()
    payload = json.loads(fixture.read_text())
    for job_dict in payload.get("jobs", []):
        normalized = engine.migrate_item(job_dict)
        assert normalized.get("queue_schema") == "2.6"
        njr_snapshot = normalized.get("njr_snapshot") or {}
        assert njr_snapshot.get("job_id"), f"missing job_id in normalized snapshot ({filename})"
        njr = normalized_job_from_snapshot({"normalized_job": njr_snapshot})
        assert njr.job_id, "NormalizedJobRecord missing job_id"
        prompt = njr.positive_prompt or (njr.config.get("prompt") if hasattr(njr, "config") and isinstance(njr.config, dict) else None)
        assert prompt, "NormalizedJobRecord should expose prompt"

    if version == "v2.0":
        assert snapshot.auto_run_enabled
