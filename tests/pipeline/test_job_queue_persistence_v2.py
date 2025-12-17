"""Tests for PR-CORE1-D5A: NJR-aligned queue persistence."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from src.controller.job_execution_controller import JobExecutionController
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_history_store import JSONLJobHistoryStore
from src.queue.job_model import Job, JobPriority
from src.services.queue_store_v2 import (
    SCHEMA_VERSION,
    QueueSnapshotV1,
    UnsupportedQueueSchemaError,
    delete_queue_snapshot,
    load_queue_snapshot,
    save_queue_snapshot,
    validate_queue_item,
)


def _make_normalized_record(job_id: str = "job-1") -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id=job_id,
        config={},
        path_output_dir="output",
        filename_template="{seed}",
    )


class TestQueueSnapshot:
    def test_snapshot_defaults(self) -> None:
        snapshot = QueueSnapshotV1()
        assert snapshot.jobs == []
        assert snapshot.auto_run_enabled is False
        assert snapshot.paused is False
        assert snapshot.schema_version == SCHEMA_VERSION

    def test_snapshot_with_values(self) -> None:
        job_entry = {
            "queue_id": "job-1",
            "njr_snapshot": {"normalized_job": {"job_id": "job-1"}},
            "priority": 1,
            "status": "queued",
            "created_at": "2025-01-01T00:00:00Z",
            "queue_schema": SCHEMA_VERSION,
            "metadata": {"source": "test"},
        }
        snapshot = QueueSnapshotV1(
            jobs=[job_entry],
            auto_run_enabled=True,
            paused=True,
        )
        assert snapshot.jobs == [job_entry]
        assert snapshot.auto_run_enabled
        assert snapshot.paused
        assert snapshot.schema_version == SCHEMA_VERSION


class TestQueueValidation:
    def test_validate_detects_missing_fields(self) -> None:
        valid, errors = validate_queue_item({"queue_id": "missing"})
        assert valid is False
        assert any("njr_snapshot" in error for error in errors)

    def test_validate_metadata_type(self) -> None:
        payload = {
            "queue_id": "job-1",
            "njr_snapshot": {"normalized_job": {"job_id": "job-1"}},
            "priority": 0,
            "status": "queued",
            "created_at": "2025-01-01T00:00:00Z",
            "queue_schema": SCHEMA_VERSION,
            "metadata": "not-a-dict",
        }
        valid, errors = validate_queue_item(payload)
        assert valid is False
        assert "metadata must be dict" in errors


class TestQueuePersistence:
    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        state_file = tmp_path / "queue_state.json"
        record = _make_normalized_record("job-1")
        job = {
            "queue_id": "job-1",
            "njr_snapshot": {"normalized_job": asdict(record)},
            "priority": 3,
            "status": "running",
            "created_at": "2025-12-10T00:00:00Z",
            "queue_schema": SCHEMA_VERSION,
            "metadata": {"source": "test"},
        }

        snapshot = QueueSnapshotV1(
            jobs=[job],
            auto_run_enabled=True,
            paused=False,
        )

        assert save_queue_snapshot(snapshot, state_file)
        persisted = json.loads(state_file.read_text())
        assert persisted["schema_version"] == SCHEMA_VERSION

        job_record = persisted["jobs"][0]
        assert job_record["queue_schema"] == SCHEMA_VERSION
        assert job_record["priority"] == 3
        assert "pipeline_config" not in job_record["njr_snapshot"]

        loaded = load_queue_snapshot(state_file)
        assert loaded is not None
        assert loaded.schema_version == SCHEMA_VERSION
        assert len(loaded.jobs) == 1
        assert loaded.jobs[0]["priority"] == 3

    def test_load_legacy_snapshot_normalizes(self, tmp_path: Path) -> None:
        state_file = tmp_path / "queue_state.json"
        legacy_entry = {
            "job_id": "legacy-job",
            "_normalized_record": asdict(_make_normalized_record("legacy-job")),
            "priority": "2",
            "status": "paused",
            "created_at": "2025-11-01T00:00:00Z",
            "metadata": {"legacy": True},
            "pipeline_config": {"model": "old"},
        }
        payload = {
            "jobs": [legacy_entry],
            "auto_run_enabled": False,
            "paused": True,
            "schema_version": 1,
        }
        state_file.write_text(json.dumps(payload))

        with pytest.raises(UnsupportedQueueSchemaError):
            load_queue_snapshot(state_file)

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        state_file = tmp_path / "subdir" / "nested" / "queue_state.json"
        snapshot = QueueSnapshotV1(auto_run_enabled=True)
        assert save_queue_snapshot(snapshot, state_file)
        assert state_file.exists()

    def test_load_missing_file_returns_none(self, tmp_path: Path) -> None:
        state_file = tmp_path / "nonexistent.json"
        assert load_queue_snapshot(state_file) is None

    def test_load_invalid_json_returns_none(self, tmp_path: Path) -> None:
        state_file = tmp_path / "invalid.json"
        state_file.write_text("not valid json {{{")
        assert load_queue_snapshot(state_file) is None

    def test_delete_removes_file(self, tmp_path: Path) -> None:
        state_file = tmp_path / "queue_state.json"
        state_file.write_text("{}")
        assert delete_queue_snapshot(state_file) is True
        assert not state_file.exists()

    def test_delete_nonexistent_returns_true(self, tmp_path: Path) -> None:
        state_file = tmp_path / "nonexistent.json"
        assert delete_queue_snapshot(state_file) is True

    def test_save_writes_single_jsonl_entry(self, tmp_path: Path) -> None:
        state_file = tmp_path / "queue_state.json"
        snapshot = QueueSnapshotV1(
            jobs=[
                {
                    "queue_id": "jsonl-job",
                    "njr_snapshot": {"normalized_job": {"job_id": "jsonl-job"}},
                    "priority": 0,
                    "status": "queued",
                    "created_at": "2025-01-01T00:00:00Z",
                    "queue_schema": SCHEMA_VERSION,
                }
            ],
            auto_run_enabled=True,
            paused=False,
        )

        assert save_queue_snapshot(snapshot, state_file)
        contents = state_file.read_text(encoding="utf-8")
        lines = contents.splitlines()
        assert len(lines) == 1
        assert contents.endswith("\n")


class TestQueuePersistenceFlags:
    def test_paused_state_persists(self, tmp_path: Path) -> None:
        state_file = tmp_path / "queue_state.json"
        save_queue_snapshot(QueueSnapshotV1(paused=True), state_file)
        loaded = load_queue_snapshot(state_file)
        assert loaded is not None
        assert loaded.paused is True

        save_queue_snapshot(QueueSnapshotV1(paused=False), state_file)
        loaded = load_queue_snapshot(state_file)
        assert loaded is not None
        assert loaded.paused is False

    def test_auto_run_state_persists(self, tmp_path: Path) -> None:
        state_file = tmp_path / "queue_state.json"
        save_queue_snapshot(QueueSnapshotV1(auto_run_enabled=True), state_file)
        loaded = load_queue_snapshot(state_file)
        assert loaded is not None
        assert loaded.auto_run_enabled is True

        save_queue_snapshot(QueueSnapshotV1(auto_run_enabled=False), state_file)
        loaded = load_queue_snapshot(state_file)
        assert loaded is not None
        assert loaded.auto_run_enabled is False

    def test_combined_flags_persist(self, tmp_path: Path) -> None:
        state_file = tmp_path / "queue_state.json"
        snapshot = QueueSnapshotV1(
            auto_run_enabled=True,
            paused=True,
            jobs=[
                {
                    "queue_id": "j1",
                    "njr_snapshot": {"normalized_job": {"job_id": "j1"}},
                    "priority": 0,
                    "status": "queued",
                    "created_at": "2025-01-01T00:00:00Z",
                    "queue_schema": SCHEMA_VERSION,
                }
            ],
        )
        save_queue_snapshot(snapshot, state_file)

        loaded = load_queue_snapshot(state_file)
        assert loaded is not None
        assert loaded.auto_run_enabled is True
        assert loaded.paused is True
        assert loaded.jobs[0]["queue_schema"] == SCHEMA_VERSION


def test_queue_history_snapshots_share_njr(tmp_path: Path) -> None:
    record = _make_normalized_record("shared-njr")
    job = Job(job_id=record.job_id, priority=JobPriority.NORMAL)
    job.snapshot = {"normalized_job": asdict(record)}
    job._normalized_record = record  # type: ignore[attr-defined]
    history_store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    history_store.record_job_submission(job)
    history_entry = history_store.list_jobs()[0]
    history_njr = history_entry.snapshot.get("normalized_job") if history_entry.snapshot else {}

    queue_entry = {
        "queue_id": job.job_id,
        "njr_snapshot": {"normalized_job": asdict(record)},
        "priority": 1,
        "status": "queued",
        "created_at": job.created_at.isoformat(),
        "queue_schema": SCHEMA_VERSION,
        "metadata": {"source": "test"},
    }

    assert queue_entry["njr_snapshot"]["normalized_job"] == history_njr
    assert "pipeline_config" not in queue_entry["njr_snapshot"]
    assert "pipeline_config" not in history_njr


def test_job_execution_controller_restores_and_persists(monkeypatch) -> None:
    entry = {
        "queue_id": "restored-job",
        "njr_snapshot": asdict(_make_normalized_record("restored-job")),
        "priority": 1,
        "status": "queued",
        "created_at": "2025-07-01T12:00:00Z",
        "queue_schema": SCHEMA_VERSION,
        "metadata": {"run_mode": "queue", "source": "gui", "prompt_source": "pack"},
    }

    def fake_load(*_, **__) -> QueueSnapshotV1:
        return QueueSnapshotV1(jobs=[entry], auto_run_enabled=True, paused=True)

    saved_snapshots: list[QueueSnapshotV1] = []

    def fake_save(snapshot: QueueSnapshotV1) -> bool:
        saved_snapshots.append(snapshot)
        return True

    monkeypatch.setattr("src.controller.job_execution_controller.load_queue_snapshot", fake_load)
    monkeypatch.setattr("src.controller.job_execution_controller.save_queue_snapshot", fake_save)

    controller = JobExecutionController(execute_job=lambda job: {"ok": True})
    queue = controller.get_queue()
    assert len(queue.list_jobs()) == 1
    assert controller.auto_run_enabled
    assert controller.is_queue_paused

    job = Job("new-job", JobPriority.NORMAL)
    record = _make_normalized_record("new-job")
    job._normalized_record = record  # type: ignore[attr-defined]
    job.snapshot = asdict(record)
    queue.submit(job)

    assert saved_snapshots
    persisted = saved_snapshots[-1]
    assert persisted.auto_run_enabled
    assert persisted.paused
    assert any(entry["queue_id"] == "new-job" for entry in persisted.jobs)
    for entry in persisted.jobs:
        assert "pipeline_config" not in entry["njr_snapshot"]
