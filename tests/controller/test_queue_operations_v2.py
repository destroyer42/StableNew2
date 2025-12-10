"""Tests for PR-GUI-F2: Controller Queue Operations.

Validates:
- move_up/move_down reorders queue
- remove removes a job
- clear empties the queue
- Controller methods delegate to queue correctly
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue


# -----------------------------------------------------------------------------
# JobQueue Method Tests
# -----------------------------------------------------------------------------


class TestJobQueueMoveUp:
    """Tests for JobQueue.move_up()."""

    def test_move_up_swaps_positions(self) -> None:
        """Moving a job up should swap it with the job above."""
        queue = JobQueue()
        job1 = Job(job_id="j1", config_snapshot={"prompt": "first"})
        job2 = Job(job_id="j2", config_snapshot={"prompt": "second"})
        job3 = Job(job_id="j3", config_snapshot={"prompt": "third"})

        queue.submit(job1)
        queue.submit(job2)
        queue.submit(job3)

        # Initially: j1, j2, j3
        # Move j2 up: j2, j1, j3
        result = queue.move_up("j2")
        assert result is True

        # Get next job should return j2 now (it moved up)
        jobs = [j for j in queue.list_jobs() if j.status == JobStatus.QUEUED]
        assert len(jobs) == 3

    def test_move_up_at_top_returns_false(self) -> None:
        """Moving the top job up should return False."""
        queue = JobQueue()
        job1 = Job(job_id="j1")
        job2 = Job(job_id="j2")

        queue.submit(job1)
        queue.submit(job2)

        # j1 is at top, can't move up
        result = queue.move_up("j1")
        assert result is False

    def test_move_up_nonexistent_returns_false(self) -> None:
        """Moving a nonexistent job returns False."""
        queue = JobQueue()
        result = queue.move_up("nonexistent")
        assert result is False


class TestJobQueueMoveDown:
    """Tests for JobQueue.move_down()."""

    def test_move_down_swaps_positions(self) -> None:
        """Moving a job down should swap it with the job below."""
        queue = JobQueue()
        job1 = Job(job_id="j1")
        job2 = Job(job_id="j2")

        queue.submit(job1)
        queue.submit(job2)

        # Move j1 down
        result = queue.move_down("j1")
        assert result is True

    def test_move_down_at_bottom_returns_false(self) -> None:
        """Moving the bottom job down should return False."""
        queue = JobQueue()
        job1 = Job(job_id="j1")
        job2 = Job(job_id="j2")

        queue.submit(job1)
        queue.submit(job2)

        # j2 is at bottom
        result = queue.move_down("j2")
        assert result is False

    def test_move_down_nonexistent_returns_false(self) -> None:
        """Moving a nonexistent job returns False."""
        queue = JobQueue()
        result = queue.move_down("nonexistent")
        assert result is False


class TestJobQueueRemove:
    """Tests for JobQueue.remove()."""

    def test_remove_returns_job(self) -> None:
        """Removing a job should return the removed job."""
        queue = JobQueue()
        job = Job(job_id="j1", config_snapshot={"test": True})
        queue.submit(job)

        removed = queue.remove("j1")
        assert removed is not None
        assert removed.job_id == "j1"

    def test_remove_deletes_from_queue(self) -> None:
        """Removed job should not appear in list_jobs."""
        queue = JobQueue()
        job1 = Job(job_id="j1")
        job2 = Job(job_id="j2")

        queue.submit(job1)
        queue.submit(job2)

        queue.remove("j1")
        jobs = queue.list_jobs()
        job_ids = [j.job_id for j in jobs if j.status == JobStatus.QUEUED]
        assert "j1" not in job_ids
        assert "j2" in job_ids

    def test_remove_nonexistent_returns_none(self) -> None:
        """Removing a nonexistent job returns None."""
        queue = JobQueue()
        removed = queue.remove("nonexistent")
        assert removed is None


class TestJobQueueClear:
    """Tests for JobQueue.clear()."""

    def test_clear_empties_queue(self) -> None:
        """Clear should remove all queued jobs."""
        queue = JobQueue()
        for i in range(5):
            queue.submit(Job(job_id=f"j{i}"))

        count = queue.clear()
        assert count == 5

        jobs = [j for j in queue.list_jobs() if j.status == JobStatus.QUEUED]
        assert len(jobs) == 0

    def test_clear_returns_count(self) -> None:
        """Clear should return number of removed jobs."""
        queue = JobQueue()
        queue.submit(Job(job_id="j1"))
        queue.submit(Job(job_id="j2"))

        count = queue.clear()
        assert count == 2

    def test_clear_empty_queue_returns_zero(self) -> None:
        """Clearing an empty queue returns 0."""
        queue = JobQueue()
        count = queue.clear()
        assert count == 0


# -----------------------------------------------------------------------------
# Controller Integration Tests
# -----------------------------------------------------------------------------


class TestControllerQueueMethods:
    """Tests for AppController queue operation methods."""

    @pytest.fixture
    def mock_queue(self) -> MagicMock:
        """Create a mock queue."""
        queue = MagicMock()
        queue.move_up = MagicMock(return_value=True)
        queue.move_down = MagicMock(return_value=True)
        queue.remove = MagicMock(return_value=MagicMock())
        queue.clear = MagicMock(return_value=3)
        return queue

    @pytest.fixture
    def mock_job_service(self, mock_queue: MagicMock) -> MagicMock:
        """Create a mock job service with queue."""
        service = MagicMock()
        service.queue = mock_queue
        return service

    def test_on_queue_move_up_calls_queue_move_up(
        self, mock_job_service: MagicMock, mock_queue: MagicMock
    ) -> None:
        """Controller should delegate move_up to queue."""
        from src.controller.app_controller import AppController

        controller = AppController.__new__(AppController)
        controller.job_service = mock_job_service
        controller._append_log = MagicMock()

        result = controller.on_queue_move_up_v2("j1")

        assert result is True
        mock_queue.move_up.assert_called_once_with("j1")

    def test_on_queue_move_down_calls_queue_move_down(
        self, mock_job_service: MagicMock, mock_queue: MagicMock
    ) -> None:
        """Controller should delegate move_down to queue."""
        from src.controller.app_controller import AppController

        controller = AppController.__new__(AppController)
        controller.job_service = mock_job_service
        controller._append_log = MagicMock()

        result = controller.on_queue_move_down_v2("j2")

        assert result is True
        mock_queue.move_down.assert_called_once_with("j2")

    def test_on_queue_remove_job_calls_queue_remove(
        self, mock_job_service: MagicMock, mock_queue: MagicMock
    ) -> None:
        """Controller should delegate remove to queue."""
        from src.controller.app_controller import AppController

        controller = AppController.__new__(AppController)
        controller.job_service = mock_job_service
        controller._append_log = MagicMock()

        result = controller.on_queue_remove_job_v2("j1")

        assert result is True
        mock_queue.remove.assert_called_once_with("j1")

    def test_on_queue_clear_calls_queue_clear(
        self, mock_job_service: MagicMock, mock_queue: MagicMock
    ) -> None:
        """Controller should delegate clear to queue."""
        from src.controller.app_controller import AppController

        controller = AppController.__new__(AppController)
        controller.job_service = mock_job_service
        controller._append_log = MagicMock()
        controller._save_queue_state = MagicMock()
        controller.app_state = None

        result = controller.on_queue_clear_v2()

        assert result == 3
        mock_queue.clear.assert_called_once()

    def test_controller_handles_missing_job_service(self) -> None:
        """Controller should handle missing job_service gracefully."""
        from src.controller.app_controller import AppController

        controller = AppController.__new__(AppController)
        controller.job_service = None

        assert controller.on_queue_move_up_v2("j1") is False
        assert controller.on_queue_move_down_v2("j1") is False
        assert controller.on_queue_remove_job_v2("j1") is False
        assert controller.on_queue_clear_v2() == 0


__all__ = [
    "TestJobQueueMoveUp",
    "TestJobQueueMoveDown",
    "TestJobQueueRemove",
    "TestJobQueueClear",
    "TestControllerQueueMethods",
]
