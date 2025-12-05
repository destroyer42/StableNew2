"""Tests for PR-203: Queue persistence.

Validates:
- save_queue_state and load_queue_state functions
- Round-trip persistence
- Clear queue state
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.pipeline.job_models_v2 import QueueJobV2
from src.pipeline.job_queue_v2 import JobQueueV2
from src.utils.config import clear_queue_state, load_queue_state, save_queue_state


class TestQueuePersistence:
    """Tests for queue state persistence functions."""

    def test_save_queue_state_creates_file(self, tmp_path) -> None:
        queue_path = tmp_path / "queue_state_v2.json"
        with patch("src.utils.config.QUEUE_STATE_PATH", queue_path):
            data = {"jobs": [], "auto_run_enabled": False, "is_paused": False}
            result = save_queue_state(data)
            assert result is True
            assert queue_path.exists()

    def test_save_queue_state_writes_json(self, tmp_path) -> None:
        queue_path = tmp_path / "queue_state_v2.json"
        with patch("src.utils.config.QUEUE_STATE_PATH", queue_path):
            data = {"jobs": [{"job_id": "test123"}], "auto_run_enabled": True}
            save_queue_state(data)

            with queue_path.open("r") as f:
                loaded = json.load(f)
            assert loaded["jobs"][0]["job_id"] == "test123"
            assert loaded["auto_run_enabled"] is True

    def test_load_queue_state_returns_none_when_no_file(self, tmp_path) -> None:
        queue_path = tmp_path / "nonexistent.json"
        with patch("src.utils.config.QUEUE_STATE_PATH", queue_path):
            result = load_queue_state()
            assert result is None

    def test_load_queue_state_returns_data(self, tmp_path) -> None:
        queue_path = tmp_path / "queue_state_v2.json"
        with patch("src.utils.config.QUEUE_STATE_PATH", queue_path):
            data = {"jobs": [{"job_id": "test456"}], "auto_run_enabled": False}
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            with queue_path.open("w") as f:
                json.dump(data, f)

            loaded = load_queue_state()
            assert loaded is not None
            assert loaded["jobs"][0]["job_id"] == "test456"

    def test_clear_queue_state_removes_file(self, tmp_path) -> None:
        queue_path = tmp_path / "queue_state_v2.json"
        with patch("src.utils.config.QUEUE_STATE_PATH", queue_path):
            # Create file
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            queue_path.write_text("{}")

            # Clear it
            result = clear_queue_state()
            assert result is True
            assert not queue_path.exists()

    def test_clear_queue_state_when_no_file(self, tmp_path) -> None:
        queue_path = tmp_path / "nonexistent.json"
        with patch("src.utils.config.QUEUE_STATE_PATH", queue_path):
            result = clear_queue_state()
            assert result is True  # Should succeed even if file doesn't exist


class TestQueuePersistenceRoundTrip:
    """Tests for full round-trip persistence."""

    def test_queue_persist_and_restore(self, tmp_path) -> None:
        queue_path = tmp_path / "queue_state_v2.json"
        with patch("src.utils.config.QUEUE_STATE_PATH", queue_path):
            # Create a queue with jobs
            queue1 = JobQueueV2()
            queue1.add_jobs([
                QueueJobV2.create({"prompt": "test1"}),
                QueueJobV2.create({"prompt": "test2"}),
            ])
            queue1.auto_run_enabled = True

            # Serialize and save
            data = queue1.serialize()
            save_queue_state(data)

            # Load and restore
            loaded_data = load_queue_state()
            queue2 = JobQueueV2()
            queue2.restore(loaded_data)

            # Verify
            assert len(queue2) == 2
            assert queue2.auto_run_enabled is True

    def test_queue_persist_with_running_job(self, tmp_path) -> None:
        queue_path = tmp_path / "queue_state_v2.json"
        with patch("src.utils.config.QUEUE_STATE_PATH", queue_path):
            # Create a queue with a running job
            queue1 = JobQueueV2()
            queue1.add_job(QueueJobV2.create({"prompt": "running"}))
            queue1.start_next_job()

            # Serialize and save
            data = queue1.serialize()
            save_queue_state(data)

            # Load and restore
            loaded_data = load_queue_state()
            queue2 = JobQueueV2()
            queue2.restore(loaded_data)

            # Running job should be back in queue as queued
            assert len(queue2) == 1
            assert queue2.running_job is None
