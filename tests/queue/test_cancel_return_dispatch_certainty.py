"""PR-RUNTIME-QUEUE-TRANSITION-ATOMICITY: Cancel and Return never requeues work whose dispatch is not provably absent.

A RUNNING job may go back to QUEUED under the same identity only when the existing dispatch-certainty evidence
(``FailureAssessment.safe_to_requeue``, the same rule the outage coordinator applies) positively shows that generation
never started. An empty checkpoint list is not evidence. Otherwise the stop request is honoured as a plain cancel, the
job is not requeued, and the operator is told through the existing job-failed event / error envelope that the outcome
is unknown and a deliberate Replay (a new NJR with lineage) is the only way to run it again.

Real ``JobQueue`` / SQLite ``JobRepository`` / ``SingleNodeJobRunner`` / ``JobService``; only the generation callable is
a fake. Pre-fix results refer to the code at ``15690eab``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from src.controller.job_service import JobService
from src.controller.runtime_state import CancellationError
from src.queue.job_model import Job, JobStatus, StageCheckpoint
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from tests.helpers.njr_factory import make_queue_job
from tests.helpers.queue_choreography import PATIENCE, assert_three_way_agreement

JOB = "job-1"
REFUSED_ACTION = "return_to_queue_refused_dispatch_uncertain"
REFUSED_TYPE = "CANCEL_RETURN_REFUSED_DISPATCH_UNCERTAIN"


# -- typed failure payloads (shape of ``webui_failure_evidence/1``) ---------------------------------------------------


def evidence(**fields: Any) -> dict[str, Any]:
    base = {
        "contract": "webui_failure_evidence/1",
        "error_code": None,
        "stage": "txt2img",
        "http_status": None,
        "method": "POST",
        "webui_unavailable": False,
        "crash_suspected": False,
        "request_may_have_executed": None,
        "timeout": False,
        "recovery_attempts": 0,
    }
    return {**base, **fields}


def failed(**fields: Any) -> dict[str, Any]:
    return {
        "success": False,
        "error": "generation failed",
        "metadata": {"failure_evidence": evidence(**fields)},
    }


CONNECTION = {"error_code": "connection", "webui_unavailable": True}


def _completed_work(_job: Job) -> dict[str, Any]:
    return {
        "success": True,
        "stage_events": [{"stage": "txt2img", "phase": "exit"}],
        "variants": [{"path": "out/test.png"}],
    }


def _checkpointed_then_unreachable(job: Job) -> dict[str, Any]:
    job.execution_metadata.stage_checkpoints = [
        StageCheckpoint(stage_name="txt2img", output_paths=["out/a.png"])
    ]
    return failed(**CONNECTION)


def _raise(exc: BaseException) -> Callable[[Job], dict[str, Any]]:
    def behavior(_job: Job) -> dict[str, Any]:
        raise exc

    return behavior


#: Possibly-dispatched work, including every case where no stage checkpoint was recorded.
REFUSED = {
    "completed_work": _completed_work,
    "success_without_outputs_or_checkpoints": lambda _job: {"success": True},
    "failure_without_typed_evidence": lambda _job: {"success": False, "error": "boom"},
    "dispatch_outcome_unknown": lambda _job: failed(request_may_have_executed=True),
    "definitive_http_500": lambda _job: failed(http_status=500),
    "timeout_without_proof": lambda _job: failed(timeout=True),
    "cancellation_error": _raise(CancellationError("cancelled")),
    "unclassified_exception": _raise(RuntimeError("boom")),
    "checkpointed_job_with_a_pre_dispatch_failure": _checkpointed_then_unreachable,
}

#: Positive evidence that nothing was dispatched (the same results the outage coordinator may requeue on).
RETURNED = {
    "ready_gate_refusal": lambda _job: {
        "success": False,
        "error": "not ready",
        "metadata": {"execution_path": "ready_gate"},
    },
    "connection_refused_before_dispatch": lambda _job: failed(**CONNECTION),
}


class Rig:
    def __init__(self, tmp_path: Path, behavior: Callable[[Job], Any] | None = None) -> None:
        self.repository = JobRepository(tmp_path / "jobs.sqlite3")
        self.queue = JobQueue(repository=self.repository)
        self.calls: list[str] = []
        self.behavior = behavior or (lambda _job: {"success": True})
        self.statuses: list[tuple[str, JobStatus]] = []
        self.runner = SingleNodeJobRunner(
            self.queue,
            self._run,
            poll_interval=0.01,
            on_status_change=lambda job, status: self.statuses.append((job.job_id, status)),
        )

    def _run(self, job: Job) -> Any:
        self.calls.append(job.job_id)
        self.runner.cancel_current(
            return_to_queue=True
        )  # the operator pressed Cancel and Return mid-generation
        return self.behavior(job)

    def submit(self) -> Job:
        job = make_queue_job(JOB)
        self.queue.submit(job)
        return job

    def row(self) -> Job:
        row = self.repository.get_job_model(JOB)
        assert row is not None
        return row

    def close(self) -> None:
        self.repository.close()


@pytest.fixture
def rig(tmp_path: Path):
    rigs: list[Rig] = []

    def factory(behavior: Callable[[Job], Any] | None = None) -> Rig:
        made = Rig(tmp_path, behavior)
        rigs.append(made)
        return made

    yield factory
    for made in rigs:
        made.close()


def _assert_refused(rig: Rig) -> None:
    row = rig.row()
    assert row.status is JobStatus.CANCELLED
    assert row.execution_metadata.return_to_queue_count == 0
    assert row.execution_metadata.last_control_action == REFUSED_ACTION
    envelope = row.error_envelope
    assert envelope is not None and envelope.error_type == REFUSED_TYPE
    assert envelope.context["action_required"] is True
    assert envelope.context["generation_outcome"] == "ambiguous"
    assert envelope.context["automatic_replay"] is False
    assert "Replay" in (row.error_message or "")
    assert rig.calls == [JOB], "the generation was dispatched once and is never re-submitted"
    assert rig.queue.claim_next_job() is None
    assert_three_way_agreement(rig.repository, rig.queue, JOB)


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_run_once_refuses_to_requeue_possibly_dispatched_work(rig, case):
    """Pre-fix: every one of these was put back in the queue (the completed-work case discarded its outputs and ran
    the whole job again)."""

    stack = rig(REFUSED[case])
    job = stack.submit()
    stack.runner.run_once(job)
    _assert_refused(stack)


@pytest.mark.parametrize("case", sorted(RETURNED))
def test_run_once_still_returns_work_that_was_provably_never_dispatched(rig, case):
    """Guard: positive evidence keeps the return working, under the same identity, once."""

    stack = rig(RETURNED[case])
    job = stack.submit()
    stack.runner.run_once(job)

    row = stack.row()
    assert row.status is JobStatus.QUEUED
    assert row.execution_metadata.return_to_queue_count == 1
    assert row.execution_metadata.last_control_action == "return_to_queue"
    assert stack.calls == [JOB]
    assert_three_way_agreement(stack.repository, stack.queue, JOB)
    assert stack.queue.claim_next_job().job_id == JOB  # the same identity is runnable again


def test_a_stop_requested_before_the_callable_runs_is_returned_without_dispatch(tmp_path):
    """Guard: the runner can prove nothing was dispatched when the callable was never invoked."""

    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    calls: list[str] = []
    holder: dict[str, SingleNodeJobRunner] = {}

    def _on_status(job: Job, status: JobStatus) -> None:
        if status is JobStatus.RUNNING:
            holder["runner"].cancel_current(return_to_queue=True)

    runner = SingleNodeJobRunner(
        queue,
        lambda job: calls.append(job.job_id) or {"success": True},
        on_status_change=_on_status,
    )
    holder["runner"] = runner
    job = make_queue_job(JOB)
    queue.submit(job)

    runner.run_once(job)

    row = repository.get_job_model(JOB)
    assert (
        calls == []
        and row.status is JobStatus.QUEUED
        and row.execution_metadata.return_to_queue_count == 1
    )
    assert_three_way_agreement(repository, queue, JOB)
    repository.close()


def test_the_worker_loop_refuses_the_same_way(tmp_path):
    """Pre-fix: the continuous worker requeued the job and immediately ran it again."""

    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    calls: list[str] = []
    settled = threading.Event()
    holder: dict[str, SingleNodeJobRunner] = {}

    def _run(job: Job) -> dict[str, Any]:
        calls.append(job.job_id)
        holder["runner"].cancel_current(return_to_queue=True)
        return _completed_work(job)

    def _on_status(job: Job, status: JobStatus) -> None:
        if status in {JobStatus.CANCELLED, JobStatus.QUEUED} or calls.count(job.job_id) > 1:
            settled.set()

    runner = SingleNodeJobRunner(queue, _run, poll_interval=0.01, on_status_change=_on_status)
    holder["runner"] = runner
    queue.submit(make_queue_job(JOB))
    runner.start()
    try:
        assert settled.wait(PATIENCE)
    finally:
        assert runner.stop(timeout=PATIENCE)

    assert calls == [JOB]
    row = repository.get_job_model(JOB)
    assert row.status is JobStatus.CANCELLED and row.execution_metadata.return_to_queue_count == 0
    assert_three_way_agreement(repository, queue, JOB)
    repository.close()


def test_the_operator_is_told_through_the_job_failed_event(tmp_path):
    """Pre-fix: the job was silently requeued; no failed event and no envelope reached the application."""

    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    holder: dict[str, SingleNodeJobRunner] = {}

    def _run(job: Job) -> dict[str, Any]:
        holder["runner"].cancel_current(return_to_queue=True)
        return _completed_work(job)

    runner = SingleNodeJobRunner(queue, _run, poll_interval=0.01)
    holder["runner"] = runner
    service = JobService(queue, runner=runner)
    events: list[Job] = []
    service.register_callback(JobService.EVENT_JOB_FAILED, events.append)
    job = make_queue_job(JOB)
    queue.submit(job)

    runner.run_once(job)

    assert [event.job_id for event in events] == [JOB]
    envelope = events[0].error_envelope  # what AppController shows in the structured-error modal
    assert envelope is not None and envelope.error_type == REFUSED_TYPE
    assert envelope.context["action_required"] is True and "Replay" in envelope.remediation
    assert events[0].status is JobStatus.CANCELLED
    repository.close()


# -- the service layer edits nothing ahead of the commit -------------------------------------------------------------


class _FailingRunner(SingleNodeJobRunner):
    def cancel_current(self, *, return_to_queue: bool = False) -> None:
        raise RuntimeError("the runner refused the signal")


def _service(tmp_path: Path, runner_type=SingleNodeJobRunner):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    service = JobService(queue, runner=runner_type(queue, lambda _job: {"success": True}))
    queue.submit(make_queue_job(JOB))
    running = queue.claim_next_job()
    assert running is not None
    return repository, queue, service, running


def test_cancel_current_with_return_does_not_edit_the_live_job_before_anything_commits(tmp_path):
    """Pre-fix: ``last_control_action`` was set to ``return_to_queue_requested`` on the live job first."""

    repository, queue, service, running = _service(tmp_path)

    service.cancel_current(return_to_queue=True)

    assert running.execution_metadata.last_control_action is None
    assert running.status is JobStatus.RUNNING
    assert_three_way_agreement(repository, queue, JOB)
    repository.close()


def test_a_runner_failure_leaves_the_live_job_unchanged(tmp_path):
    """Pre-fix: the live job kept ``return_to_queue_requested`` although nothing was signalled or committed."""

    repository, queue, service, running = _service(tmp_path, _FailingRunner)

    with pytest.raises(RuntimeError):
        service.cancel_current(return_to_queue=True)

    assert running.execution_metadata.last_control_action is None
    assert_three_way_agreement(repository, queue, JOB)
    repository.close()


def test_a_plain_cancel_leaves_the_live_job_and_the_row_in_agreement(tmp_path):
    """Pre-fix: the live job said ``cancel_requested`` after the commit; the durable row never did."""

    repository, queue, service, running = _service(tmp_path)

    service.cancel_current()

    assert repository.get_job_model(JOB).status is JobStatus.CANCELLED
    assert_three_way_agreement(repository, queue, JOB)
    repository.close()
