# Subsystem: Controller
# Role: Tests for JobService dependency injection (PR-0114C-T(x)).

"""Tests for JobService DI hooks.

PR-0114C-T(x): These tests verify that JobService correctly supports
dependency injection for runner and history service:

1. JobService uses StubRunner when runner_factory is injected.
2. JobService uses NullHistoryService when history_service is injected.
3. JobService creates default SingleNodeJobRunner when no factory provided.
4. Legacy API (direct runner parameter) still works.
"""

from __future__ import annotations

from src.controller.job_history_service import NullHistoryService
from src.controller.job_service import JobService
from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.queue.stub_runner import StubRunner


# ---------------------------------------------------------------------------
# Test: StubRunner DI
# ---------------------------------------------------------------------------


class TestStubRunnerDI:
    """Test that JobService correctly uses injected StubRunner."""

    def test_job_service_uses_stub_runner_when_injected(self) -> None:
        """JobService uses StubRunner from runner_factory."""
        queue = JobQueue()
        history = NullHistoryService()

        def stub_factory(jq, rc):
            return StubRunner(jq, run_callable=rc)

        service = JobService(
            job_queue=queue,
            runner_factory=stub_factory,
            history_service=history,
        )

        # Assert runner is a StubRunner
        assert isinstance(service.runner, StubRunner)
        assert not isinstance(service.runner, SingleNodeJobRunner)

    def test_stub_runner_start_does_not_spawn_thread(self) -> None:
        """StubRunner.start() does not spawn worker threads."""
        queue = JobQueue()
        runner = StubRunner(queue)

        runner.start()

        # StubRunner just sets a flag, no threading
        assert runner.is_running() is True
        runner.stop()
        assert runner.is_running() is False

    def test_stub_runner_run_once_returns_empty_dict(self) -> None:
        """StubRunner.run_once() returns empty result without execution."""
        queue = JobQueue()
        runner = StubRunner(queue)
        job = Job(
            job_id="test-stub-1",
            priority=JobPriority.NORMAL,
        )

        result = runner.run_once(job)

        assert result == {}


# ---------------------------------------------------------------------------
# Test: NullHistoryService DI
# ---------------------------------------------------------------------------


class TestNullHistoryServiceDI:
    """Test that JobService correctly uses injected NullHistoryService."""

    def test_job_service_uses_null_history_service_when_injected(self) -> None:
        """JobService uses NullHistoryService from history_service param."""
        queue = JobQueue()
        history = NullHistoryService()

        service = JobService(
            job_queue=queue,
            runner_factory=lambda jq, rc: StubRunner(jq, run_callable=rc),
            history_service=history,
        )

        # Assert history service is NullHistoryService
        assert service._history_service is history
        assert isinstance(service._history_service, NullHistoryService)

    def test_null_history_service_record_is_noop(self) -> None:
        """NullHistoryService.record() does nothing without errors."""
        history = NullHistoryService()
        job = Job(
            job_id="test-null-1",
            priority=JobPriority.NORMAL,
        )

        # Should not raise
        history.record(job, result={"status": "ok"})

    def test_null_history_service_record_failure_is_noop(self) -> None:
        """NullHistoryService.record_failure() does nothing without errors."""
        history = NullHistoryService()
        job = Job(
            job_id="test-null-2",
            priority=JobPriority.NORMAL,
        )

        # Should not raise
        history.record_failure(job, error="test error")

    def test_null_history_service_lists_return_empty(self) -> None:
        """NullHistoryService list methods return empty collections."""
        history = NullHistoryService()

        assert history.list_active_jobs() == []
        assert history.list_recent_jobs() == []
        assert history.get_job("any-id") is None


# ---------------------------------------------------------------------------
# Test: Default Runner Creation
# ---------------------------------------------------------------------------


class TestDefaultRunnerCreation:
    """Test that JobService creates SingleNodeJobRunner when no factory provided."""

    def test_job_service_creates_default_runner_when_no_factory(self) -> None:
        """JobService creates SingleNodeJobRunner when runner and factory are None."""
        queue = JobQueue()

        service = JobService(
            job_queue=queue,
            # No runner, no runner_factory
        )

        # Default should be SingleNodeJobRunner
        assert isinstance(service.runner, SingleNodeJobRunner)


# ---------------------------------------------------------------------------
# Test: Legacy API Compatibility
# ---------------------------------------------------------------------------


class TestLegacyAPICompatibility:
    """Test that legacy direct runner parameter still works."""

    def test_job_service_uses_direct_runner_when_provided(self) -> None:
        """JobService uses runner directly when passed (legacy API)."""
        queue = JobQueue()
        direct_runner = StubRunner(queue)

        service = JobService(
            job_queue=queue,
            runner=direct_runner,
        )

        # Should use the exact runner instance provided
        assert service.runner is direct_runner

    def test_direct_runner_takes_precedence_over_factory(self) -> None:
        """Direct runner parameter takes precedence over runner_factory."""
        queue = JobQueue()
        direct_runner = StubRunner(queue)
        factory_called = []

        def tracking_factory(jq, rc):
            factory_called.append(True)
            return StubRunner(jq)

        service = JobService(
            job_queue=queue,
            runner=direct_runner,
            runner_factory=tracking_factory,
        )

        # Factory should NOT be called when runner is provided
        assert factory_called == []
        assert service.runner is direct_runner


# ---------------------------------------------------------------------------
# Test: History Recording via JobService
# ---------------------------------------------------------------------------


class TestHistoryRecordingViaJobService:
    """Test that JobService delegates history recording to history_service."""

    def test_job_service_records_completion_via_history_service(self) -> None:
        """JobService._record_job_history calls history_service.record()."""
        queue = JobQueue()
        recorded_jobs = []

        class TrackingHistoryService(NullHistoryService):
            def record(self, job, *, result=None):
                recorded_jobs.append((job.job_id, "completed", result))

        history = TrackingHistoryService()
        service = JobService(
            job_queue=queue,
            runner_factory=lambda jq, rc: StubRunner(jq),
            history_service=history,
        )

        job = Job(
            job_id="track-1",
            priority=JobPriority.NORMAL,
        )
        job.result = {"images": ["test.png"]}

        service._record_job_history(job, JobStatus.COMPLETED)

        assert len(recorded_jobs) == 1
        assert recorded_jobs[0][0] == "track-1"
        assert recorded_jobs[0][1] == "completed"

    def test_job_service_records_failure_via_history_service(self) -> None:
        """JobService._record_job_history calls history_service.record_failure()."""
        queue = JobQueue()
        recorded_failures = []

        class TrackingHistoryService(NullHistoryService):
            def record_failure(self, job, error=None):
                recorded_failures.append((job.job_id, error))

        history = TrackingHistoryService()
        service = JobService(
            job_queue=queue,
            runner_factory=lambda jq, rc: StubRunner(jq),
            history_service=history,
        )

        job = Job(
            job_id="track-2",
            priority=JobPriority.NORMAL,
        )
        job.error_message = "test failure"

        service._record_job_history(job, JobStatus.FAILED)

        assert len(recorded_failures) == 1
        assert recorded_failures[0][0] == "track-2"
        assert recorded_failures[0][1] == "test failure"
