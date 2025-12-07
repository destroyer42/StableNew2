"""Tests for PR-GUI-F3: Queue persistence and control flags.

Tests:
- QueueSnapshotV1 serialization roundtrip
- load_queue_snapshot / save_queue_snapshot
- Pause state persistence
- Auto-run flag persistence
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.services.queue_store_v2 import (
    QueueSnapshotV1,
    delete_queue_snapshot,
    load_queue_snapshot,
    save_queue_snapshot,
)


class TestQueueSnapshotV1:
    """Tests for QueueSnapshotV1 dataclass."""

    def test_snapshot_defaults(self) -> None:
        """Snapshot has correct default values."""
        snapshot = QueueSnapshotV1()
        assert snapshot.jobs == []
        assert snapshot.auto_run_enabled is False
        assert snapshot.paused is False
        assert snapshot.schema_version == 1

    def test_snapshot_with_values(self) -> None:
        """Snapshot stores provided values."""
        jobs = [{"job_id": "test-1", "config": {}}]
        snapshot = QueueSnapshotV1(
            jobs=jobs,
            auto_run_enabled=True,
            paused=True,
        )
        assert snapshot.jobs == jobs
        assert snapshot.auto_run_enabled is True
        assert snapshot.paused is True


class TestQueuePersistence:
    """Tests for load/save queue snapshot functions."""

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """Saving and loading a snapshot preserves all fields."""
        state_file = tmp_path / "queue_state.json"
        
        original = QueueSnapshotV1(
            jobs=[{"job_id": "job-1", "model": "sdxl"}],
            auto_run_enabled=True,
            paused=False,
        )
        
        assert save_queue_snapshot(original, state_file) is True
        assert state_file.exists()
        
        loaded = load_queue_snapshot(state_file)
        assert loaded is not None
        assert loaded.jobs == original.jobs
        assert loaded.auto_run_enabled == original.auto_run_enabled
        assert loaded.paused == original.paused

    def test_load_missing_file_returns_none(self, tmp_path: Path) -> None:
        """Loading from non-existent file returns None."""
        state_file = tmp_path / "nonexistent.json"
        result = load_queue_snapshot(state_file)
        assert result is None

    def test_load_invalid_json_returns_none(self, tmp_path: Path) -> None:
        """Loading invalid JSON returns None."""
        state_file = tmp_path / "invalid.json"
        state_file.write_text("not valid json {{{")
        
        result = load_queue_snapshot(state_file)
        assert result is None

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        """Saving creates parent directory if needed."""
        state_file = tmp_path / "subdir" / "nested" / "queue_state.json"
        
        snapshot = QueueSnapshotV1(auto_run_enabled=True)
        assert save_queue_snapshot(snapshot, state_file) is True
        assert state_file.exists()

    def test_delete_removes_file(self, tmp_path: Path) -> None:
        """Deleting removes the state file."""
        state_file = tmp_path / "queue_state.json"
        state_file.write_text("{}")
        
        assert state_file.exists()
        assert delete_queue_snapshot(state_file) is True
        assert not state_file.exists()

    def test_delete_nonexistent_returns_true(self, tmp_path: Path) -> None:
        """Deleting non-existent file returns True (idempotent)."""
        state_file = tmp_path / "nonexistent.json"
        assert delete_queue_snapshot(state_file) is True


class TestQueuePersistenceFlags:
    """Tests for pause and auto-run flag persistence."""

    def test_paused_state_persists(self, tmp_path: Path) -> None:
        """Paused state is saved and restored correctly."""
        state_file = tmp_path / "queue_state.json"
        
        # Save paused=True
        save_queue_snapshot(QueueSnapshotV1(paused=True), state_file)
        loaded = load_queue_snapshot(state_file)
        assert loaded is not None
        assert loaded.paused is True
        
        # Save paused=False
        save_queue_snapshot(QueueSnapshotV1(paused=False), state_file)
        loaded = load_queue_snapshot(state_file)
        assert loaded is not None
        assert loaded.paused is False

    def test_auto_run_state_persists(self, tmp_path: Path) -> None:
        """Auto-run state is saved and restored correctly."""
        state_file = tmp_path / "queue_state.json"
        
        # Save auto_run=True
        save_queue_snapshot(QueueSnapshotV1(auto_run_enabled=True), state_file)
        loaded = load_queue_snapshot(state_file)
        assert loaded is not None
        assert loaded.auto_run_enabled is True
        
        # Save auto_run=False
        save_queue_snapshot(QueueSnapshotV1(auto_run_enabled=False), state_file)
        loaded = load_queue_snapshot(state_file)
        assert loaded is not None
        assert loaded.auto_run_enabled is False

    def test_combined_flags_persist(self, tmp_path: Path) -> None:
        """Both flags are persisted and restored together."""
        state_file = tmp_path / "queue_state.json"
        
        snapshot = QueueSnapshotV1(
            auto_run_enabled=True,
            paused=True,
            jobs=[{"id": "j1"}],
        )
        save_queue_snapshot(snapshot, state_file)
        
        loaded = load_queue_snapshot(state_file)
        assert loaded is not None
        assert loaded.auto_run_enabled is True
        assert loaded.paused is True
        assert loaded.jobs == [{"id": "j1"}]
