"""PR-RUNTIME-QUEUE-TRANSITION-ATOMICITY: the queue itself enforces the dispatch-evidence gate on every return.

The runner and the outage coordinator decide *when* to ask for a return; ``JobQueue`` is the one place that performs
it, so it is also where a return is refused unless positive evidence says nothing was dispatched. These tests drive the
queue directly (no runner), plus the source-level guards that keep the old pre-commit edits from coming back.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.api.webui_failure_evidence import DispatchCertainty, FailureAssessment, FailureCategory
from src.controller.job_execution_controller import JobExecutionController
from src.controller.job_service import JobService
from src.controller.webui_outage_coordinator import ProbeResult, WebUIOutageCoordinator
from src.queue.dispatch_evidence import NEVER_INVOKED, assess_dispatch
from src.queue.job_model import Job, JobStatus, StageCheckpoint
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from tests.helpers.njr_factory import make_queue_job
from tests.helpers.queue_choreography import GatedRepository, assert_three_way_agreement, once

JOB = "job-1"
REFUSED_TYPE = "CANCEL_RETURN_REFUSED_DISPATCH_UNCERTAIN"


@pytest.fixture
def stack(tmp_path: Path):
    repository = GatedRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    yield SimpleNamespace(repository=repository, queue=queue)
    repository.close()


def _claimed(stack, job_id: str = JOB) -> Job:
    stack.queue.submit(make_queue_job(job_id))
    job = stack.queue.claim_next_job()
    assert job is not None
    return job


ORDINARY = FailureAssessment(FailureCategory.ORDINARY, DispatchCertainty.NOT_APPLICABLE)
OUTCOME_UNKNOWN = FailureAssessment(
    FailureCategory.OUTCOME_UNKNOWN, DispatchCertainty.UNKNOWN, suspects_outage=True
)
DISPATCHED = FailureAssessment(FailureCategory.DISPATCHED_HTTP_ERROR, DispatchCertainty.DISPATCHED)


def _assert_refused(stack) -> None:
    row = stack.repository.get_job_model(JOB)
    assert row.status is JobStatus.CANCELLED
    assert row.execution_metadata.return_to_queue_count == 0
    assert row.error_envelope.error_type == REFUSED_TYPE
    assert stack.queue.claim_next_job() is None
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


# --- Cancel and Return ---------------------------------------------------------------------------------------------


def test_a_return_with_no_evidence_is_refused(stack):
    _claimed(stack)
    settled = stack.queue.cancel_running_job(return_to_queue=True)
    assert settled is not None and settled.status is JobStatus.CANCELLED
    _assert_refused(stack)


@pytest.mark.parametrize(
    "assessment", [ORDINARY, OUTCOME_UNKNOWN, DISPATCHED], ids=lambda a: a.category.value
)
def test_an_empty_checkpoint_list_alone_is_not_evidence(stack, assessment):
    job = _claimed(stack)
    assert (
        job.execution_metadata.stage_checkpoints == []
    )  # nothing recorded - and that proves nothing
    stack.queue.cancel_running_job(return_to_queue=True, assessment=assessment)
    _assert_refused(stack)


def test_recorded_progress_overrides_positive_evidence(stack):
    job = _claimed(stack)
    job.execution_metadata.stage_checkpoints = [
        StageCheckpoint(stage_name="txt2img", output_paths=["a.png"])
    ]
    stack.queue.cancel_running_job(return_to_queue=True, assessment=NEVER_INVOKED)
    _assert_refused(stack)


def test_a_result_that_shows_output_overrides_positive_evidence(stack):
    job = _claimed(stack)
    job.result = {"variants": [{"path": "a.png"}]}
    stack.queue.cancel_running_job(return_to_queue=True, assessment=NEVER_INVOKED)
    _assert_refused(stack)


def test_positive_evidence_returns_the_same_identity_at_the_back(stack):
    first = _claimed(stack)
    stack.queue.submit(make_queue_job("other"))
    settled = stack.queue.cancel_running_job(return_to_queue=True, assessment=NEVER_INVOKED)
    assert settled is first and first.status is JobStatus.QUEUED
    assert [job.job_id for job in stack.queue.list_active_jobs_ordered()] == ["other", JOB]
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


def test_a_plain_cancel_is_never_annotated_as_a_refusal(stack):
    _claimed(stack)
    stack.queue.cancel_running_job()
    row = stack.repository.get_job_model(JOB)
    assert row.status is JobStatus.CANCELLED and row.error_envelope is None
    assert row.execution_metadata.last_control_action == "cancelled"
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


# --- the outage requeue is held to the same rule -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "assessment", [ORDINARY, OUTCOME_UNKNOWN, DISPATCHED], ids=lambda a: a.category.value
)
def test_an_outage_return_without_positive_evidence_changes_nothing(stack, assessment):
    live = _claimed(stack)
    before = (live.status, live.execution_metadata.return_to_queue_count, live.progress)

    assert stack.queue.return_undispatched_to_queue(JOB, reason="t", assessment=assessment) is None

    assert (live.status, live.execution_metadata.return_to_queue_count, live.progress) == before
    assert stack.repository.get_job_model(JOB).status is JobStatus.RUNNING
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


def test_an_outage_return_is_withheld_when_a_checkpoint_landed_after_the_decision(stack):
    live = _claimed(stack)
    live.execution_metadata.stage_checkpoints = [StageCheckpoint(stage_name="txt2img")]
    assert (
        stack.queue.return_undispatched_to_queue(JOB, reason="t", assessment=NEVER_INVOKED) is None
    )
    assert stack.repository.get_job_model(JOB).status is JobStatus.RUNNING


def test_the_coordinator_and_the_operator_gate_share_one_verdict(stack):
    job = _claimed(stack)
    coordinator = WebUIOutageCoordinator(
        stack.queue, probe=lambda: ProbeResult(False, "endpoint_free"), manager_getter=lambda: None
    )
    result: dict[str, Any] = {
        "success": False,
        "error": "unreachable",
        "metadata": {
            "failure_evidence": {
                "contract": "webui_failure_evidence/1",
                "error_code": "connection_error",
                "stage": "txt2img",
                "webui_unavailable": True,
            }
        },
    }
    shared, _ = assess_dispatch(job, result=result)
    assert coordinator.assess(job, result=result).assessment == shared
    assert shared.safe_to_requeue is True
    job.execution_metadata.stage_checkpoints = [StageCheckpoint(stage_name="txt2img")]
    withheld, _ = assess_dispatch(job, result=result)
    assert withheld.safe_to_requeue is False
    assert coordinator.assess(job, result=result).assessment == withheld


# --- exceptions after the commit point, for every kind of transition ---------------------------------------------------


@pytest.mark.parametrize("target", ["claim", "return", "cancel"])
def test_a_repository_failure_after_commit_never_leaves_the_projection_behind(stack, target):
    if target == "claim":
        stack.queue.submit(make_queue_job(JOB))
        stack.repository.after_commit = once(
            lambda _j, status: status is JobStatus.RUNNING,
            lambda *_: (_ for _ in ()).throw(OSError("after COMMIT")),
        )
        claimed = stack.queue.claim_next_job()
        assert claimed is not None and claimed.status is JobStatus.RUNNING
    else:
        _claimed(stack)
        wanted = JobStatus.QUEUED if target == "return" else JobStatus.CANCELLED
        stack.repository.after_commit = once(
            lambda _j, status: status is wanted,
            lambda *_: (_ for _ in ()).throw(OSError("after COMMIT")),
        )
        if target == "return":
            assert (
                stack.queue.return_undispatched_to_queue(JOB, reason="t", assessment=NEVER_INVOKED)
                is not None
            )
        else:
            assert stack.queue.mark_cancelled(JOB, "operator") is not None
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


def test_a_failure_before_the_commit_changes_nothing_live(stack):
    live = _claimed(stack)
    before = (live.status, live.progress, live.execution_metadata.return_to_queue_count)

    def _boom(_j: Job, _s: JobStatus) -> None:
        raise OSError("before COMMIT")

    stack.repository.before_commit = once(lambda _j, status: status is JobStatus.QUEUED, _boom)
    with pytest.raises(OSError):
        stack.queue.return_undispatched_to_queue(JOB, reason="t", assessment=NEVER_INVOKED)

    assert (live.status, live.progress, live.execution_metadata.return_to_queue_count) == before
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


# --- re-entrancy on the refusal path -----------------------------------------------------------------------------------


def test_listeners_may_re_enter_the_queue_while_a_refusal_is_announced(stack):
    _claimed(stack)
    stack.queue.submit(make_queue_job("next"))
    seen: list[tuple[str, str]] = []
    reclaimed: list[Job | None] = []

    def _status_listener(job: Job, status: JobStatus) -> None:
        seen.append((status.value, stack.queue.get_job(job.job_id).status.value))
        stack.queue.dispatch_summary()
        stack.queue.list_jobs()

    def _state_listener() -> None:
        if not reclaimed and stack.queue.get_job(JOB).status is JobStatus.CANCELLED:
            reclaimed.append(stack.queue.claim_next_job())

    def _observer(entry) -> None:
        seen.append((entry.status.value, stack.queue.get_job(entry.job_id).status.value))

    stack.queue.register_status_callback(_status_listener)
    stack.queue.register_state_listener(_state_listener)
    stack.repository.register_callback(_observer)

    stack.queue.cancel_running_job(return_to_queue=True)

    assert ("cancelled", "cancelled") in seen and all(a == b for a, b in seen)
    assert [job.job_id for job in reclaimed if job] == ["next"]
    assert_three_way_agreement(stack.repository, stack.queue, JOB)
    assert_three_way_agreement(stack.repository, stack.queue, "next")


# --- progress ---------------------------------------------------------------------------------------------------------


def test_record_progress_only_touches_a_running_job(stack):
    stack.queue.submit(make_queue_job(JOB))
    assert stack.queue.record_progress(JOB, 0.5, 3.0) is None  # still QUEUED
    assert stack.repository.get_job_model(JOB).progress == 0.0
    live = stack.queue.claim_next_job()
    assert stack.queue.record_progress(JOB, 0.5, 3.0) is live
    assert (
        stack.queue.record_progress(JOB, 0.3, None) is live
    )  # the high-water mark is kept, the ETA is the report's
    assert (live.progress, live.eta_seconds) == (0.5, None)
    assert stack.repository.get_job_model(JOB).eta_seconds is None
    stack.queue.mark_completed(JOB, {"success": True})
    assert stack.queue.record_progress(JOB, 0.9, 1.0) is None
    assert stack.queue.record_progress("unknown", 0.9, 1.0) is None
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


# --- the legacy runner contract ---------------------------------------------------------------------------------------


class _LegacyRunner(SingleNodeJobRunner):
    """A runner whose ``cancel_current`` cannot carry the return request."""

    def cancel_current(self, **kwargs: Any) -> None:
        if kwargs:
            raise TypeError("cancel_current() takes no arguments")
        self.signalled = True


def test_a_runner_that_cannot_carry_the_return_request_never_causes_a_requeue(stack):
    service = JobService(
        stack.queue, runner=_LegacyRunner(stack.queue, lambda _j: {"success": True})
    )
    running = _claimed(stack)

    assert service.cancel_current(return_to_queue=True) is running

    assert service.runner.signalled is True
    assert running.status is JobStatus.RUNNING  # nothing returned it behind the worker's back
    assert stack.repository.get_job_model(JOB).status is JobStatus.RUNNING
    assert_three_way_agreement(stack.repository, stack.queue, JOB)


# --- outage requeue versus an operator cancel, end to end ----------------------------------------------------------------


def test_an_operator_cancel_that_lands_before_an_outage_requeue_wins(tmp_path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    calls: list[str] = []

    def _probe() -> ProbeResult:
        # The operator cancels while the coordinator is still deciding.
        queue.mark_cancelled(JOB, "operator")
        return ProbeResult(False, "endpoint_free")

    coordinator = WebUIOutageCoordinator(queue, probe=_probe, manager_getter=lambda: None)
    runner = SingleNodeJobRunner(
        queue,
        lambda job: calls.append(job.job_id)
        or {
            "success": False,
            "error": "unreachable",
            "metadata": {
                "failure_evidence": {
                    "contract": "webui_failure_evidence/1",
                    "error_code": "connection_error",
                    "stage": "txt2img",
                    "webui_unavailable": True,
                }
            },
        },
        outage_observer=coordinator,
    )
    job = make_queue_job(JOB)
    queue.submit(job)

    runner.run_once(job)

    row = repository.get_job_model(JOB)
    assert row.status is JobStatus.CANCELLED and row.execution_metadata.return_to_queue_count == 0
    assert calls == [JOB] and queue.claim_next_job() is None
    assert_three_way_agreement(repository, queue, JOB)
    repository.close()


# --- source-level guards: no edit of a live job ahead of its commit ----------------------------------------------------


def _attribute_assignment_roots(function: Any) -> set[str]:
    """Names ``x`` that the function assigns through (``x.attr = ...`` / ``x[k] = ...`` / augmented forms)."""

    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if not isinstance(target, (ast.Attribute, ast.Subscript)):
                continue
            while isinstance(target, (ast.Attribute, ast.Subscript)):
                target = target.value
            if isinstance(target, ast.Name):
                roots.add(target.id)
    return roots


@pytest.mark.parametrize(
    ("function", "forbidden"),
    [
        (JobRepository.transition_job, {"job"}),  # the caller's candidate is read, never written
        (JobQueue.cancel_running_job, {"job", "running"}),
        (JobQueue.return_undispatched_to_queue, {"job", "running"}),
        (JobQueue._update_status, {"job"}),
        (JobQueue.claim_next_job, {"job"}),
        (JobService.cancel_current, {"running", "job"}),
        (JobExecutionController._handle_runtime_status_update, {"job"}),
    ],
    ids=lambda value: getattr(value, "__qualname__", None) or "-",
)
def test_no_transition_path_edits_a_live_job_before_it_commits(function, forbidden):
    """Pre-fix (15690eab) each of these assigned to the live job (``running.progress = 0.0``,
    ``job.execution_metadata.return_to_queue_count += 1``, ``job.progress = 0.0`` inside the repository, ...)."""

    assert not (_attribute_assignment_roots(function) & forbidden)


def test_record_progress_is_the_only_progress_writer_and_edits_after_its_guarded_write():
    # ``record_progress`` assigns ``job.progress`` / ``job.eta_seconds`` only after ``update_progress`` accepted the row.
    source = inspect.getsource(JobQueue.record_progress)
    assert source.index("update_progress") < source.index("job.progress, job.eta_seconds =")
