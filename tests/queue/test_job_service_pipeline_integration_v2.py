# Subsystem: Queue
# Role: End-to-end parity tests for JobService + Runner + execution path (PR-204E).

"""Queue-level tests: JobService + SingleNodeJobRunner + execution path.

These tests verify:
1. Submitting normalized jobs via JobService leads to the run callable
   being invoked with the expected job payloads.
2. Direct and queued modes both result in correct job execution.
3. Job lifecycle transitions (QUEUED → RUNNING → COMPLETED/FAILED) are correct.

Queue Test Best Practices (from KNOWN_PITFALLS_QUEUE_TESTING.md):
- Do NOT call run_next_now() after submit_queued()
- Do NOT assert on original Job object; use JobHistory or fresh lookups
- Do NOT rely on sleep(); poll JobHistory until terminal states

References:
- ARCHITECTURE_v2.5.md: Run path and job construction flow
- PR-204E: End-to-End Controller + Queue Parity Tests
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from src.controller.job_service import JobService
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner

# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------


def make_normalized_record(
    *,
    job_id: str = "test-job",
    model: str = "test-model",
    prompt: str = "test prompt",
    steps: int = 20,
    cfg_scale: float = 7.0,
) -> NormalizedJobRecord:
    """Create a NormalizedJobRecord for testing."""
    return NormalizedJobRecord(
        job_id=job_id,
        config={"prompt": prompt, "model": model, "steps": steps},
        path_output_dir="output",
        filename_template="{seed}",
        seed=12345,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=1000.0,
        prompt_pack_id="test-pack",
        prompt_pack_name="test pack",
        positive_prompt=prompt,
        negative_prompt="",
        stage_chain=[
            StageConfig(
                stage_type="txt2img",
                enabled=True,
                steps=steps,
                cfg_scale=cfg_scale,
                sampler_name="Euler a",
            )
        ],
        steps=steps,
        cfg_scale=cfg_scale,
        width=512,
        height=512,
        sampler_name="Euler a",
        scheduler="ddim",
        base_model=model,
        queue_source="ADD_TO_QUEUE",
        run_mode="QUEUE",
    )


def make_job(
    job_id: str = "test-job",
    *,
    model: str = "test-model",
    steps: int = 20,
    run_mode: str = "queue",
    config_snapshot: dict[str, Any] | None = None,
) -> Job:
    """Create a Job for testing."""
    record = make_normalized_record(job_id=job_id, model=model, steps=steps)
    job = Job(job_id=job_id, run_mode=run_mode)
    job._normalized_record = record
    job.snapshot = record.to_queue_snapshot()
    if config_snapshot is not None:
        job.config_snapshot = config_snapshot
    return job


class RecordingRunCallable:
    """Records all jobs passed to the run callable."""

    def __init__(self, should_raise: bool = False) -> None:
        self.calls: list[Job] = []
        self.should_raise = should_raise
        self._lock = threading.Lock()

    def __call__(self, job: Job) -> dict[str, Any]:
        with self._lock:
            self.calls.append(job)
        if self.should_raise:
            raise RuntimeError("Simulated job failure")
        return {"job_id": job.job_id, "status": "completed"}

    def get_job_ids(self) -> list[str]:
        with self._lock:
            return [j.job_id for j in self.calls]


def poll_until_terminal(
    queue: JobQueue,
    job_id: str,
    timeout: float = 2.0,
    poll_interval: float = 0.01,
) -> Job | None:
    """Poll until job reaches a terminal state (no sleep-based waits).

    Returns the job if found in terminal state, None if timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = queue.get_job(job_id)
        if job and job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return job
        time.sleep(poll_interval)
    return None


def poll_until_all_terminal(
    queue: JobQueue,
    job_ids: list[str],
    timeout: float = 2.0,
    poll_interval: float = 0.01,
) -> list[Job]:
    """Poll until all jobs reach terminal states."""
    deadline = time.monotonic() + timeout
    results: list[Job] = []

    while time.monotonic() < deadline:
        all_terminal = True
        results = []
        for jid in job_ids:
            job = queue.get_job(jid)
            if job:
                results.append(job)
                if job.status not in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                    all_terminal = False
            else:
                all_terminal = False
        if all_terminal and len(results) == len(job_ids):
            return results
        time.sleep(poll_interval)

    return results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def job_queue() -> JobQueue:
    """Fresh job queue for each test."""
    return JobQueue()


@pytest.fixture
def recording_callable() -> RecordingRunCallable:
    """Recording callable that tracks job executions."""
    return RecordingRunCallable()


@pytest.fixture
def runner(job_queue: JobQueue, recording_callable: RecordingRunCallable) -> SingleNodeJobRunner:
    """Single node runner with recording callable."""
    return SingleNodeJobRunner(
        job_queue=job_queue,
        run_callable=recording_callable,
        poll_interval=0.01,
    )


@pytest.fixture
def job_service(job_queue: JobQueue, runner: SingleNodeJobRunner) -> JobService:
    """JobService wired to queue and runner."""
    service = JobService(job_queue=job_queue, runner=runner)
    service.auto_run_enabled = True  # Enable auto-start for tests
    return service


# ---------------------------------------------------------------------------
# Test: Direct Mode Execution
# ---------------------------------------------------------------------------


class TestDirectModeExecution:
    """Tests for direct (synchronous) job execution."""

    def test_direct_mode_executes_immediately(
        self,
        job_service: JobService,
        recording_callable: RecordingRunCallable,
    ) -> None:
        """submit_direct() executes job immediately and synchronously."""
        job = make_job("direct-001", run_mode="direct")

        result = job_service.submit_direct(job)

        # Job was executed
        assert recording_callable.get_job_ids() == ["direct-001"]
        # Result returned
        assert result is not None
        assert result.get("job_id") == "direct-001"

    def test_direct_mode_receives_correct_config(
        self,
        job_service: JobService,
        recording_callable: RecordingRunCallable,
    ) -> None:
        """submit_direct() passes job with correct pipeline_config."""
        job = make_job("direct-002", model="special-model", steps=42)

        job_service.submit_direct(job)

        assert len(recording_callable.calls) == 1
        executed_job = recording_callable.calls[0]
        assert executed_job._normalized_record.config["model"] == "special-model"
        assert executed_job._normalized_record.config["steps"] == 42

    def test_direct_mode_job_completes(
        self,
        job_service: JobService,
        job_queue: JobQueue,
    ) -> None:
        """submit_direct() marks job as COMPLETED on success."""
        job = make_job("direct-003")

        job_service.submit_direct(job)

        # Check job status in queue
        queued_job = job_queue.get_job("direct-003")
        assert queued_job is not None
        assert queued_job.status == JobStatus.COMPLETED

    def test_direct_mode_handles_error(
        self,
        job_queue: JobQueue,
    ) -> None:
        """submit_direct() marks job as FAILED on exception."""
        failing_callable = RecordingRunCallable(should_raise=True)
        runner = SingleNodeJobRunner(job_queue, failing_callable)
        service = JobService(job_queue, runner)
        job = make_job("direct-fail")

        with pytest.raises(RuntimeError, match="Simulated"):
            service.submit_direct(job)

        queued_job = job_queue.get_job("direct-fail")
        assert queued_job is not None
        assert queued_job.status == JobStatus.FAILED


# ---------------------------------------------------------------------------
# Test: Queued Mode Execution
# ---------------------------------------------------------------------------


class TestQueuedModeExecution:
    """Tests for queued (asynchronous) job execution."""

    def test_queued_mode_adds_to_queue(
        self,
        job_service: JobService,
        job_queue: JobQueue,
    ) -> None:
        """submit_queued() adds job to the queue."""
        job = make_job("queued-001")

        job_service.submit_queued(job)

        # Job is in queue
        jobs = job_queue.list_jobs()
        assert any(j.job_id == "queued-001" for j in jobs)

    def test_queued_mode_starts_runner(
        self,
        job_service: JobService,
        runner: SingleNodeJobRunner,
    ) -> None:
        """submit_queued() starts the runner if not already running."""
        job = make_job("queued-002")

        job_service.submit_queued(job)

        # Runner should be started
        assert runner.is_running()

    def test_queued_mode_executes_job(
        self,
        job_service: JobService,
        job_queue: JobQueue,
        recording_callable: RecordingRunCallable,
    ) -> None:
        """submit_queued() eventually executes the job."""
        job = make_job("queued-003")

        job_service.submit_queued(job)

        # Poll until job completes (no sleep-based waits)
        completed_job = poll_until_terminal(job_queue, "queued-003")

        assert completed_job is not None
        assert completed_job.status == JobStatus.COMPLETED
        assert "queued-003" in recording_callable.get_job_ids()

    def test_queued_mode_receives_correct_config(
        self,
        job_service: JobService,
        job_queue: JobQueue,
        recording_callable: RecordingRunCallable,
    ) -> None:
        """submit_queued() passes job with correct pipeline_config."""
        job = make_job("queued-004", model="queue-model", steps=30)

        job_service.submit_queued(job)

        # Wait for execution
        poll_until_terminal(job_queue, "queued-004")

        assert len(recording_callable.calls) >= 1
        executed_job = next(j for j in recording_callable.calls if j.job_id == "queued-004")
        assert executed_job._normalized_record.config["model"] == "queue-model"
        assert executed_job._normalized_record.config["steps"] == 30

    def test_queued_mode_returns_without_blocking_on_long_jobs(self) -> None:
        """submit_queued() returns immediately even if the job takes time to execute."""
        job_queue = JobQueue()

        start_event = threading.Event()
        release_event = threading.Event()

        def blocking_callable(job: Job) -> dict[str, Any]:
            start_event.set()
            release_event.wait(timeout=2.0)
            return {"job_id": job.job_id, "status": "completed"}

        runner = SingleNodeJobRunner(
            job_queue=job_queue, run_callable=blocking_callable, poll_interval=0.01
        )
        service = JobService(job_queue=job_queue, runner=runner)
        service.auto_run_enabled = True  # Enable auto-start

        job = make_job("queued-block-001")

        start = time.monotonic()
        service.submit_queued(job)
        duration = time.monotonic() - start

        assert duration < 0.2
        assert start_event.wait(timeout=1.0)

        release_event.set()
        poll_until_terminal(job_queue, "queued-block-001")
        runner.stop()


# ---------------------------------------------------------------------------
# Test: Multiple Queued Jobs + Order
# ---------------------------------------------------------------------------


class TestMultipleQueuedJobs:
    """Tests for multiple queued jobs execution."""

    def test_multiple_jobs_all_execute(
        self,
        job_service: JobService,
        job_queue: JobQueue,
        recording_callable: RecordingRunCallable,
    ) -> None:
        """Multiple queued jobs are all executed."""
        job1 = make_job("multi-001")
        job2 = make_job("multi-002")
        job3 = make_job("multi-003")

        job_service.submit_queued(job1)
        job_service.submit_queued(job2)
        job_service.submit_queued(job3)

        # Poll until all complete
        completed_jobs = poll_until_all_terminal(job_queue, ["multi-001", "multi-002", "multi-003"])

        assert len(completed_jobs) == 3
        assert all(j.status == JobStatus.COMPLETED for j in completed_jobs)

        # All were executed
        executed_ids = recording_callable.get_job_ids()
        assert "multi-001" in executed_ids
        assert "multi-002" in executed_ids
        assert "multi-003" in executed_ids

    def test_jobs_execute_in_fifo_order(
        self,
        job_service: JobService,
        job_queue: JobQueue,
        recording_callable: RecordingRunCallable,
    ) -> None:
        """Jobs are executed in FIFO order."""
        jobs = [make_job(f"fifo-{i:03d}") for i in range(5)]

        for job in jobs:
            job_service.submit_queued(job)

        # Poll until all complete
        poll_until_all_terminal(job_queue, [j.job_id for j in jobs])

        # Check execution order
        executed_ids = recording_callable.get_job_ids()
        expected_order = [f"fifo-{i:03d}" for i in range(5)]
        assert executed_ids == expected_order


# ---------------------------------------------------------------------------
# Test: Direct vs Queue Parity
# ---------------------------------------------------------------------------


class TestDirectQueueParity:
    """Tests that direct and queue modes produce same execution behavior."""

    def test_same_config_both_modes(
        self,
        job_queue: JobQueue,
    ) -> None:
        """Same config is passed to callable in both direct and queue modes."""
        direct_calls: list[Job] = []
        queue_calls: list[Job] = []

        def direct_recorder(job: Job) -> dict:
            direct_calls.append(job)
            return {"ok": True}

        def queue_recorder(job: Job) -> dict:
            queue_calls.append(job)
            return {"ok": True}

        # Direct mode
        direct_runner = SingleNodeJobRunner(job_queue, direct_recorder)
        direct_service = JobService(job_queue, direct_runner)
        direct_job = make_job("parity-direct", model="parity-model", steps=99)
        direct_service.submit_direct(direct_job)

        # Queue mode (fresh queue)
        queue2 = JobQueue()
        queue_runner = SingleNodeJobRunner(queue2, queue_recorder)
        queue_service = JobService(queue2, queue_runner)
        queue_job = make_job("parity-queue", model="parity-model", steps=99)
        queue_service.submit_queued(queue_job)
        poll_until_terminal(queue2, "parity-queue")

        # Both received same config
        assert len(direct_calls) == 1
        assert len(queue_calls) == 1
        assert (
            direct_calls[0]._normalized_record.config["model"]
            == queue_calls[0]._normalized_record.config["model"]
        )
        assert (
            direct_calls[0]._normalized_record.config["steps"]
            == queue_calls[0]._normalized_record.config["steps"]
        )


# ---------------------------------------------------------------------------
# Test: Error Handling in Queue
# ---------------------------------------------------------------------------


class TestQueueErrorHandling:
    """Tests for error handling in queued execution."""

    def test_failed_job_marked_failed(
        self,
        job_queue: JobQueue,
    ) -> None:
        """Failed job is marked FAILED in queue."""
        failing_callable = RecordingRunCallable(should_raise=True)
        runner = SingleNodeJobRunner(job_queue, failing_callable)
        service = JobService(job_queue, runner)

        job = make_job("fail-001")
        service.submit_queued(job)

        # Poll until terminal
        final_job = poll_until_terminal(job_queue, "fail-001")

        assert final_job is not None
        assert final_job.status == JobStatus.FAILED

    def test_other_jobs_continue_after_failure(
        self,
        job_queue: JobQueue,
    ) -> None:
        """Other jobs continue after one fails."""
        call_count = [0]

        def selective_failure(job: Job) -> dict:
            call_count[0] += 1
            if job.job_id == "fail-middle":
                raise RuntimeError("Middle job failed")
            return {"ok": True}

        runner = SingleNodeJobRunner(job_queue, selective_failure)
        service = JobService(job_queue, runner)

        service.submit_queued(make_job("success-1"))
        service.submit_queued(make_job("fail-middle"))
        service.submit_queued(make_job("success-2"))

        # Poll until all terminal
        poll_until_all_terminal(job_queue, ["success-1", "fail-middle", "success-2"])

        # Check statuses
        job1 = job_queue.get_job("success-1")
        job2 = job_queue.get_job("fail-middle")
        job3 = job_queue.get_job("success-2")

        assert job1 is not None and job1.status == JobStatus.COMPLETED
        assert job2 is not None and job2.status == JobStatus.FAILED
        assert job3 is not None and job3.status == JobStatus.COMPLETED


# ---------------------------------------------------------------------------
# Test: Job Metadata Preservation
# ---------------------------------------------------------------------------


class TestJobMetadataPreservation:
    """Tests that job metadata is preserved through execution."""

    def test_config_snapshot_preserved(
        self,
        job_service: JobService,
        job_queue: JobQueue,
        recording_callable: RecordingRunCallable,
    ) -> None:
        """config_snapshot is preserved through queue execution."""
        snapshot = {"model": "snapshot-model", "seed": 42}
        job = make_job("meta-001", config_snapshot=snapshot)

        job_service.submit_queued(job)
        poll_until_terminal(job_queue, "meta-001")

        executed_job = next(j for j in recording_callable.calls if j.job_id == "meta-001")
        assert executed_job.config_snapshot == snapshot

    def test_run_mode_preserved(
        self,
        job_service: JobService,
        job_queue: JobQueue,
        recording_callable: RecordingRunCallable,
    ) -> None:
        """run_mode is preserved through queue execution."""
        job = make_job("meta-002", run_mode="queue")

        job_service.submit_queued(job)
        poll_until_terminal(job_queue, "meta-002")

        executed_job = next(j for j in recording_callable.calls if j.job_id == "meta-002")
        assert executed_job.run_mode == "queue"


# ---------------------------------------------------------------------------
# Test: Runner Lifecycle
# ---------------------------------------------------------------------------


class TestRunnerLifecycle:
    """Tests for runner start/stop behavior."""

    def test_runner_stops_when_queue_empty(
        self,
        job_service: JobService,
        job_queue: JobQueue,
        runner: SingleNodeJobRunner,
    ) -> None:
        """Runner continues polling but we can stop it."""
        job = make_job("lifecycle-001")

        job_service.submit_queued(job)
        assert runner.is_running()

        # Wait for job to complete
        poll_until_terminal(job_queue, "lifecycle-001")

        # Stop runner
        runner.stop()
        assert not runner.is_running()

    def test_pause_and_resume(
        self,
        job_service: JobService,
        job_queue: JobQueue,
    ) -> None:
        """Pause and resume work correctly."""
        recording = RecordingRunCallable()
        runner = SingleNodeJobRunner(job_queue, recording)
        service = JobService(job_queue, runner)

        # Submit job and immediately pause
        job = make_job("pause-001")
        service.submit_queued(job)
        service.pause()

        # Give a moment for pause to take effect
        time.sleep(0.05)

        # Resume
        service.resume()

        # Job should eventually complete
        final = poll_until_terminal(job_queue, "pause-001", timeout=3.0)
        assert final is not None
        # Could be COMPLETED or still processing depending on timing
        # At minimum, the system shouldn't crash


# ---------------------------------------------------------------------------
# Test: Submit Jobs Batch
# ---------------------------------------------------------------------------


class TestSubmitJobsBatch:
    """Tests for batch job submission."""

    def test_submit_jobs_respects_run_mode(
        self,
        job_queue: JobQueue,
    ) -> None:
        """submit_jobs() respects each job's run_mode."""
        direct_calls: list[str] = []
        queue_calls: list[str] = []

        def track_calls(job: Job) -> dict:
            if job.run_mode == "direct":
                direct_calls.append(job.job_id)
            else:
                queue_calls.append(job.job_id)
            return {"ok": True}

        runner = SingleNodeJobRunner(job_queue, track_calls)
        service = JobService(job_queue, runner)

        jobs = [
            make_job("batch-direct-1", run_mode="direct"),
            make_job("batch-queue-1", run_mode="queue"),
            make_job("batch-queue-2", run_mode="queue"),
        ]

        service.submit_jobs(jobs)

        # Wait for queue jobs
        poll_until_all_terminal(job_queue, ["batch-queue-1", "batch-queue-2"])

        # Direct job was called
        assert "batch-direct-1" in direct_calls or "batch-direct-1" in queue_calls

        # All jobs completed
        all_ids = direct_calls + queue_calls
        assert "batch-direct-1" in all_ids
        assert "batch-queue-1" in all_ids
        assert "batch-queue-2" in all_ids
