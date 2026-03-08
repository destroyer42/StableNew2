"""Tests for PR-203: JobQueueV2 and job models.

Validates:
- JobStatusV2 enum values
- QueueJobV2 creation and serialization
- JobQueueV2 queue operations (add, move, remove, clear)
- JobQueueV2 serialization and restore for persistence
"""

from __future__ import annotations

from src.pipeline.job_models_v2 import JobStatusV2, QueueJobV2
from src.pipeline.job_queue_v2 import JobQueueV2


class TestJobStatusV2:
    """Tests for JobStatusV2 enum."""

    def test_all_status_values_exist(self) -> None:
        assert JobStatusV2.QUEUED.value == "queued"
        assert JobStatusV2.RUNNING.value == "running"
        assert JobStatusV2.PAUSED.value == "paused"
        assert JobStatusV2.COMPLETED.value == "completed"
        assert JobStatusV2.CANCELLED.value == "cancelled"
        assert JobStatusV2.FAILED.value == "failed"


class TestQueueJobV2:
    """Tests for QueueJobV2 dataclass."""

    def test_create_generates_unique_ids(self) -> None:
        job1 = QueueJobV2.create({})
        job2 = QueueJobV2.create({})
        assert job1.job_id != job2.job_id

    def test_create_with_config_snapshot(self) -> None:
        config = {"model": "test_model", "steps": 20}
        job = QueueJobV2.create(config)
        assert job.config_snapshot == config
        assert job.status == JobStatusV2.QUEUED

    def test_get_display_summary(self) -> None:
        config = {"prompt": "a test prompt with many words"}
        job = QueueJobV2.create(config)
        summary = job.get_display_summary()
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_to_dict_and_from_dict_roundtrip(self) -> None:
        config = {"model": "test", "steps": 30}
        job = QueueJobV2.create(config)
        job.status = JobStatusV2.RUNNING
        job.progress = 0.5

        data = job.to_dict()
        restored = QueueJobV2.from_dict(data)

        assert restored.job_id == job.job_id
        assert restored.config_snapshot == job.config_snapshot
        assert restored.status == job.status
        assert restored.progress == job.progress


class TestJobQueueV2:
    """Tests for JobQueueV2 queue operations."""

    def test_queue_starts_empty(self) -> None:
        queue = JobQueueV2()
        assert len(queue) == 0
        assert queue.is_empty()

    def test_add_job_increases_length(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({"test": "config"})
        queue.add_job(job)
        assert len(queue) == 1
        assert not queue.is_empty()

    def test_add_job_sets_status_to_queued(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({})
        job.status = JobStatusV2.RUNNING  # Set to non-queued
        queue.add_job(job)
        assert job.status == JobStatusV2.QUEUED

    def test_add_jobs_adds_multiple(self) -> None:
        queue = JobQueueV2()
        jobs = [QueueJobV2.create({}) for _ in range(3)]
        queue.add_jobs(jobs)
        assert len(queue) == 3

    def test_remove_job_by_id(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({})
        queue.add_job(job)
        removed = queue.remove_job(job.job_id)
        assert removed is not None
        assert removed.job_id == job.job_id
        assert len(queue) == 0

    def test_remove_nonexistent_job_returns_none(self) -> None:
        queue = JobQueueV2()
        result = queue.remove_job("nonexistent_id")
        assert result is None

    def test_get_job_by_id(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({})
        queue.add_job(job)
        found = queue.get_job(job.job_id)
        assert found is not None
        assert found.job_id == job.job_id

    def test_move_job_up(self) -> None:
        queue = JobQueueV2()
        job1 = QueueJobV2.create({"order": 1})
        job2 = QueueJobV2.create({"order": 2})
        queue.add_jobs([job1, job2])

        assert queue.jobs[0].job_id == job1.job_id
        assert queue.jobs[1].job_id == job2.job_id

        result = queue.move_job_up(job2.job_id)
        assert result is True
        assert queue.jobs[0].job_id == job2.job_id
        assert queue.jobs[1].job_id == job1.job_id

    def test_move_job_up_at_top_returns_false(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({})
        queue.add_job(job)
        result = queue.move_job_up(job.job_id)
        assert result is False

    def test_move_job_down(self) -> None:
        queue = JobQueueV2()
        job1 = QueueJobV2.create({"order": 1})
        job2 = QueueJobV2.create({"order": 2})
        queue.add_jobs([job1, job2])

        result = queue.move_job_down(job1.job_id)
        assert result is True
        assert queue.jobs[0].job_id == job2.job_id
        assert queue.jobs[1].job_id == job1.job_id

    def test_move_job_down_at_bottom_returns_false(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({})
        queue.add_job(job)
        result = queue.move_job_down(job.job_id)
        assert result is False

    def test_clear_queue_removes_all_jobs(self) -> None:
        queue = JobQueueV2()
        queue.add_jobs([QueueJobV2.create({}) for _ in range(3)])
        count = queue.clear_queue()
        assert count == 3
        assert len(queue) == 0

    def test_get_next_job_returns_first(self) -> None:
        queue = JobQueueV2()
        job1 = QueueJobV2.create({"first": True})
        job2 = QueueJobV2.create({"second": True})
        queue.add_jobs([job1, job2])
        next_job = queue.get_next_job()
        assert next_job is not None
        assert next_job.job_id == job1.job_id

    def test_start_next_job_pops_and_marks_running(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({})
        queue.add_job(job)

        started = queue.start_next_job()
        assert started is not None
        assert started.status == JobStatusV2.RUNNING
        assert started.started_at is not None
        assert queue.running_job is not None
        assert len(queue) == 0

    def test_start_next_job_when_paused_returns_none(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({})
        queue.add_job(job)
        queue.pause_queue()
        result = queue.start_next_job()
        assert result is None

    def test_complete_running_job_success(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({})
        queue.add_job(job)
        queue.start_next_job()

        completed = queue.complete_running_job(success=True)
        assert completed is not None
        assert completed.status == JobStatusV2.COMPLETED
        assert completed.progress == 1.0
        assert queue.running_job is None

    def test_complete_running_job_failure(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({})
        queue.add_job(job)
        queue.start_next_job()

        failed = queue.complete_running_job(success=False, error_message="Test error")
        assert failed is not None
        assert failed.status == JobStatusV2.FAILED
        assert failed.error_message == "Test error"

    def test_cancel_running_job(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({})
        queue.add_job(job)
        queue.start_next_job()

        cancelled = queue.cancel_running_job()
        assert cancelled is not None
        assert cancelled.status == JobStatusV2.CANCELLED
        assert queue.running_job is None

    def test_cancel_running_job_return_to_queue(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({})
        queue.add_job(job)
        queue.start_next_job()

        cancelled = queue.cancel_running_job(return_to_queue=True)
        assert cancelled is not None
        assert cancelled.status == JobStatusV2.QUEUED
        assert len(queue) == 1

    def test_update_job_progress(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({})
        queue.add_job(job)
        queue.start_next_job()

        queue.update_job_progress(0.5, eta_seconds=30.0)
        assert queue.running_job is not None
        assert queue.running_job.progress == 0.5
        assert queue.running_job.eta_seconds == 30.0

    def test_pause_and_resume_queue(self) -> None:
        queue = JobQueueV2()
        assert queue.is_paused is False

        queue.pause_queue()
        assert queue.is_paused is True

        queue.resume_queue()
        assert queue.is_paused is False

    def test_auto_run_enabled_property(self) -> None:
        queue = JobQueueV2()
        assert queue.auto_run_enabled is False

        queue.auto_run_enabled = True
        assert queue.auto_run_enabled is True


class TestJobQueueV2Persistence:
    """Tests for JobQueueV2 serialization and restore."""

    def test_serialize_empty_queue(self) -> None:
        queue = JobQueueV2()
        data = queue.serialize()
        assert "jobs" in data
        assert len(data["jobs"]) == 0

    def test_serialize_includes_queued_jobs(self) -> None:
        queue = JobQueueV2()
        queue.add_jobs([QueueJobV2.create({}) for _ in range(2)])
        data = queue.serialize()
        assert len(data["jobs"]) == 2

    def test_serialize_includes_running_job(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({})
        queue.add_job(job)
        queue.start_next_job()
        data = queue.serialize()
        # Running job should be included
        assert len(data["jobs"]) == 1
        assert data["jobs"][0].get("was_running") is True

    def test_serialize_includes_auto_run_and_paused(self) -> None:
        queue = JobQueueV2()
        queue.auto_run_enabled = True
        queue.pause_queue()
        data = queue.serialize()
        assert data["auto_run_enabled"] is True
        assert data["is_paused"] is True

    def test_restore_queued_jobs(self) -> None:
        # Create and serialize a queue
        queue1 = JobQueueV2()
        queue1.add_jobs([QueueJobV2.create({"order": i}) for i in range(3)])
        data = queue1.serialize()

        # Restore into a new queue
        queue2 = JobQueueV2()
        queue2.restore(data)
        assert len(queue2) == 3

    def test_restore_running_job_becomes_queued(self) -> None:
        # Create a queue with a running job
        queue1 = JobQueueV2()
        job = QueueJobV2.create({})
        queue1.add_job(job)
        queue1.start_next_job()
        data = queue1.serialize()

        # Restore into a new queue - running job should go back to queue
        queue2 = JobQueueV2()
        queue2.restore(data)
        assert len(queue2) == 1
        assert queue2.jobs[0].status == JobStatusV2.QUEUED
        assert queue2.running_job is None

    def test_restore_preserves_auto_run_and_paused(self) -> None:
        queue1 = JobQueueV2()
        queue1.auto_run_enabled = True
        queue1.pause_queue()
        data = queue1.serialize()

        queue2 = JobQueueV2()
        queue2.restore(data)
        assert queue2.auto_run_enabled is True
        assert queue2.is_paused is True


class TestJobQueueV2Listeners:
    """Tests for JobQueueV2 change listeners."""

    def test_listener_called_on_add_job(self) -> None:
        queue = JobQueueV2()
        notifications = []

        def notify() -> None:
            notifications.append("notified")

        queue.add_listener(notify)

        queue.add_job(QueueJobV2.create({}))
        assert len(notifications) == 1

    def test_listener_called_on_remove_job(self) -> None:
        queue = JobQueueV2()
        job = QueueJobV2.create({})
        queue.add_job(job)

        notifications = []

        def notify() -> None:
            notifications.append("notified")

        queue.add_listener(notify)

        queue.remove_job(job.job_id)
        assert len(notifications) == 1

    def test_listener_called_on_move_job(self) -> None:
        queue = JobQueueV2()
        queue.add_jobs([QueueJobV2.create({}) for _ in range(2)])

        notifications = []

        def notify() -> None:
            notifications.append("notified")

        queue.add_listener(notify)

        queue.move_job_down(queue.jobs[0].job_id)
        assert len(notifications) == 1

    def test_listener_can_be_removed(self) -> None:
        queue = JobQueueV2()
        notifications = []

        def callback() -> None:
            notifications.append("notified")

        queue.add_listener(callback)
        queue.add_job(QueueJobV2.create({}))
        assert len(notifications) == 1

        queue.remove_listener(callback)
        queue.add_job(QueueJobV2.create({}))
        assert len(notifications) == 1  # No new notification
