"""PR-QUEUE-WEBUI-171: backend-scoped WebUI outage containment and safe recovery.

Real ``JobQueue`` / SQLite ``JobRepository`` / ``SingleNodeJobRunner`` / ``JobService``. Only the generation transport
(``run_callable``), the readiness probe and the owned process manager are fakes. Nothing starts a real WebUI, Comfy or
SVD runtime and no test depends on a wall-clock outcome beyond bounded polling.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.api.types import GenerateError, GenerateErrorCode
from src.api.webui_failure_evidence import (
    DispatchCertainty,
    FailureCategory,
    assess_evidence,
    assess_exception,
    assess_result,
    build_failure_evidence,
)
from src.controller.job_service import JobService
from src.controller.job_service_outage import bind_webui_outage_containment
from src.controller.webui_outage_coordinator import ProbeResult, WebUIHealth, WebUIOutageCoordinator
from src.pipeline.stage_models import StageType
from src.queue.backend_dependency import BackendDependency, classify_job
from src.queue.job_model import JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from src.utils.error_envelope_v2 import wrap_exception
from tests.helpers.njr_factory import make_queue_job, make_stage_config

URL = "http://127.0.0.1:7871"
DEADLINE = 8.0


# -- job builders ----------------------------------------------------------------------------------------------------


def image(job_id: str, priority: JobPriority = JobPriority.NORMAL, **overrides: Any):
    return make_queue_job(job_id, priority=priority, **overrides)


def svd(job_id: str):
    return make_queue_job(
        job_id,
        stage_chain=[make_stage_config(StageType.TXT2IMG, enabled=False), make_stage_config("svd_native")],
    )


def comfy(job_id: str):
    return make_queue_job(
        job_id,
        stage_chain=[make_stage_config("video_workflow")],
        config={"video_workflow": {"video_execution": {"backend_id": "comfy"}}},
    )


def unresolved(job_id: str):
    """A video workflow with no explicit backend identity: never assumed independent."""
    return make_queue_job(job_id, stage_chain=[make_stage_config("video_workflow")])


# -- typed failure payloads ------------------------------------------------------------------------------------------


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
    return {"success": False, "error": "generation failed", "metadata": {"failure_evidence": evidence(**fields)}}


CONNECTION = {"error_code": GenerateErrorCode.CONNECTION.value, "webui_unavailable": True}


def raising(**fields: Any) -> Exception:
    exc = RuntimeError("Connection refused while contacting WebUI")
    wrap_exception(
        exc,
        subsystem="pipeline",
        stage="txt2img",
        context={
            "diagnostics": {
                "request_summary": {
                    "endpoint": "/sdapi/v1/txt2img",
                    "method": "POST",
                    "stage": "txt2img",
                    "status": fields.get("http_status"),
                },
                "webui_unavailable": fields.get("webui_unavailable", True),
                "crash_suspected": False,
                "error_message": "Connection refused while contacting WebUI",
            }
        },
    )
    return exc


# -- fakes -----------------------------------------------------------------------------------------------------------


class Backend:
    """The configured runtime as seen by the read-only probe."""

    def __init__(self, up: bool = False) -> None:
        self.up = up
        self.probes = 0

    def probe(self) -> ProbeResult:
        self.probes += 1
        return ProbeResult(self.up, "ready" if self.up else "endpoint_free", URL, "forge_webui")


class FakeManager:
    runtime_identity = "forge_webui"
    endpoint = URL
    pid = 4242

    def __init__(self, backend: Backend, *, owns: bool = True, recovers: bool = True) -> None:
        self.backend = backend
        self.owns_process = owns
        self.recovers = recovers
        self.restarts = 0
        self.stops = 0
        self.starts = 0
        self.listeners: list[Callable[[Any], None]] = []
        self.gate: threading.Event | None = None

    def restart_webui(self, **_kwargs: Any) -> bool:
        self.restarts += 1
        if self.gate is not None:
            assert self.gate.wait(DEADLINE)
        self.backend.up = self.recovers
        return self.recovers

    def stop_webui(self, *a: Any, **k: Any) -> bool:
        self.stops += 1
        return True

    def start(self) -> None:
        self.starts += 1

    def get_stdout_tail_text(self, _lines: int = 40) -> str:
        return "boot line 1\nboot line 2"

    def add_ready_listener(self, listener: Callable[[Any], None]) -> None:
        self.listeners.append(listener)


class Stack:
    def __init__(
        self,
        tmp_path: Path,
        behavior: Callable[[Any], Any] | None = None,
        *,
        up: bool = False,
        manager: FakeManager | None = None,
        startup_gate: bool = False,
        repository: JobRepository | None = None,
        release_interval_s: float = 0.0,
    ) -> None:
        self.backend = manager.backend if manager is not None else Backend(up)
        self.manager = manager
        self.repository = repository or JobRepository(tmp_path / "queue.db")
        self.queue = JobQueue(repository=self.repository)
        self.calls: list[str] = []
        self._lock = threading.Lock()
        self.behavior = behavior or (lambda job: {"success": True})
        self.coordinator = WebUIOutageCoordinator(
            self.queue,
            probe=self.backend.probe,
            manager_getter=lambda: self.manager,
            release_interval_s=release_interval_s,
        )
        self.runner = SingleNodeJobRunner(
            self.queue,
            self._run,
            poll_interval=0.005,
            held_poll_interval=0.02,
            outage_observer=self.coordinator,
        )
        if startup_gate:
            self.coordinator.enable_startup_gate()

    def _run(self, job: Any) -> Any:
        with self._lock:
            self.calls.append(job.job_id)
        outcome = self.behavior(job)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def submit(self, *jobs: Any) -> None:
        for job in jobs:
            self.queue.submit(job)

    def status(self, job_id: str) -> JobStatus:
        job = self.queue.get_job(job_id)
        assert job is not None, job_id
        return job.status

    def statuses(self) -> dict[str, str]:
        return {job.job_id: job.status.value for job in self.queue.list_jobs()} | {
            jid: job.status.value for jid, job in self.queue._finalized_jobs.items()
        }

    def queued_order(self) -> list[str]:
        return [job.job_id for job in self.queue.list_active_jobs_ordered() if job.status is JobStatus.QUEUED]

    def start(self) -> None:
        self.runner.start()

    def close(self) -> None:
        self.runner.stop(timeout=3)


@pytest.fixture
def make_stack(tmp_path: Path):
    stacks: list[Stack] = []

    def factory(*args: Any, **kwargs: Any) -> Stack:
        stack = Stack(tmp_path, *args, **kwargs)
        stacks.append(stack)
        return stack

    yield factory
    for stack in stacks:
        stack.close()


def wait_for(predicate: Callable[[], bool], timeout: float = DEADLINE) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached before the deadline")


def settle(seconds: float = 0.25) -> None:
    threading.Event().wait(seconds)  # real-clock settle, independent of any patched time.sleep


def done(status: JobStatus) -> bool:
    return status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


# =====================================================================================================================
# Pure classification
# =====================================================================================================================


@pytest.mark.parametrize(
    ("job", "expected"),
    [
        (lambda: image("i"), BackendDependency.REQUIRES_WEBUI),
        (
            lambda: image("a1111", backend_options={"image": {"backend_id": "a1111_webui"}}),
            BackendDependency.REQUIRES_WEBUI,
        ),
        (
            lambda: image("forge", backend_options={"image": {"backend_id": "forge_webui"}}),
            BackendDependency.REQUIRES_WEBUI,
        ),
        (
            lambda: image("other", backend_options={"image": {"backend_id": "experimental_diffusers"}}),
            BackendDependency.UNRESOLVED,
        ),
        (lambda: svd("s"), BackendDependency.INDEPENDENT_VIDEO),
        (lambda: comfy("c"), BackendDependency.INDEPENDENT_VIDEO),
        (lambda: unresolved("u"), BackendDependency.UNRESOLVED),
        (
            lambda: make_queue_job("ad", stage_chain=[make_stage_config("animatediff")]),
            BackendDependency.REQUIRES_WEBUI,
        ),
        (
            lambda: make_queue_job("train", stage_chain=[make_stage_config("train_lora")]),
            BackendDependency.UNRESOLVED,
        ),
    ],
    ids=["image", "a1111", "forge", "unknown-image-backend", "svd", "comfy", "workflow-no-backend", "animatediff", "training"],
)
def test_dependency_is_classified_from_the_frozen_identity_only(job, expected):
    assert classify_job(job()).dependency is expected


def test_a_job_without_a_frozen_record_is_unresolved_and_a_snapshot_is_classified():
    from src.queue.job_model import Job

    assert classify_job(Job(job_id="bare")).dependency is BackendDependency.UNRESOLVED
    historical = image("hist")
    restored = Job(job_id="hist", snapshot=historical.snapshot)  # no NJR object: persisted snapshot shape only
    assert classify_job(restored).dependency is BackendDependency.REQUIRES_WEBUI


def test_classification_never_mutates_or_recompiles_the_record():
    job = svd("s")
    before = job._normalized_record.to_dict()
    classify_job(job)
    assert job._normalized_record.to_dict() == before


def test_failure_evidence_is_typed_and_content_free():
    exc = raising(webui_unavailable=True)
    data = build_failure_evidence(exc)
    assert data["contract"] == "webui_failure_evidence/1"
    assert data["webui_unavailable"] is True and data["stage"] == "txt2img"
    assert not {"prompt", "negative_prompt", "output_dir"} & set(data)


@pytest.mark.parametrize(
    ("fields", "category", "certainty", "suspects", "requeue"),
    [
        (CONNECTION, FailureCategory.PRE_DISPATCH_UNAVAILABLE, DispatchCertainty.NOT_DISPATCHED, True, True),
        (
            {"error_code": GenerateErrorCode.OUTCOME_UNKNOWN.value, "request_may_have_executed": True},
            FailureCategory.OUTCOME_UNKNOWN,
            DispatchCertainty.UNKNOWN,
            True,
            False,
        ),
        ({"http_status": 500}, FailureCategory.DISPATCHED_HTTP_ERROR, DispatchCertainty.DISPATCHED, True, False),
        ({"http_status": 422}, FailureCategory.DISPATCHED_HTTP_ERROR, DispatchCertainty.DISPATCHED, False, False),
        ({"crash_suspected": True, "webui_unavailable": True}, FailureCategory.DISPATCHED_HTTP_ERROR, DispatchCertainty.DISPATCHED, True, False),
        ({"timeout": True}, FailureCategory.TIMEOUT, DispatchCertainty.UNKNOWN, False, False),
        (
            {"error_code": GenerateErrorCode.INVALID_SAMPLER.value},
            FailureCategory.ORDINARY,
            DispatchCertainty.NOT_APPLICABLE,
            False,
            False,
        ),
        (
            {"error_code": GenerateErrorCode.PAYLOAD_VALIDATION.value},
            FailureCategory.ORDINARY,
            DispatchCertainty.NOT_APPLICABLE,
            False,
            False,
        ),
    ],
    ids=["connection", "outcome-unknown", "http-500", "http-422", "crash-after-500", "timeout", "invalid-sampler", "payload"],
)
def test_assessment_categories(fields, category, certainty, suspects, requeue):
    assessment = assess_evidence(evidence(**fields))
    assert (assessment.category, assessment.certainty) == (category, certainty)
    assert assessment.suspects_outage is suspects and assessment.safe_to_requeue is requeue


def test_partial_progress_is_never_safe_to_requeue():
    result = failed(**CONNECTION)
    result["stage_events"] = [{"stage": "txt2img", "event": "exit"}]
    assert assess_result(result).safe_to_requeue is False


def test_ready_gate_result_is_not_dispatched_evidence():
    result = {"success": False, "error": "WebUI not ready", "metadata": {"execution_path": "ready_gate"}}
    assessment = assess_result(result)
    assert (assessment.category, assessment.certainty) == (
        FailureCategory.READINESS_FAILURE,
        DispatchCertainty.NOT_DISPATCHED,
    )
    assert assessment.safe_to_requeue is True


def test_non_webui_jobs_are_not_webui_failures():
    assert assess_result(failed(**CONNECTION), job_runs_webui_stage=False).category is FailureCategory.NOT_WEBUI
    assert assess_exception(raising(), job_runs_webui_stage=False).category is FailureCategory.NOT_WEBUI


# =====================================================================================================================
# 1-3, 9-10: cascade containment, mixed queue, priority order
# =====================================================================================================================


def test_confirmed_outage_does_not_cascade_through_twenty_five_image_jobs(make_stack):
    def behavior(job):
        return {"success": True} if job.job_id == "img-00" else failed(**CONNECTION)

    stack = make_stack(behavior, up=False)
    stack.submit(*(image(f"img-{i:02d}") for i in range(25)))
    stack.start()
    wait_for(lambda: stack.status("img-00") is JobStatus.COMPLETED)
    wait_for(lambda: stack.queue.is_webui_held())
    settle()

    statuses = stack.statuses()
    assert statuses["img-00"] == "completed"
    assert sum(1 for s in statuses.values() if s == "failed") == 0
    assert sum(1 for s in statuses.values() if s == "queued") == 24
    assert stack.calls == ["img-00", "img-01"]  # exactly one job observed the outage
    assert stack.queued_order() == [f"img-{i:02d}" for i in range(1, 25)]  # original FIFO order preserved


@pytest.mark.parametrize("shape", ["structured", "raised", "ready_gate"])
def test_structured_and_raised_failures_are_both_classified(make_stack, shape):
    def behavior(job):
        if shape == "structured":
            return failed(**CONNECTION)
        if shape == "raised":
            return raising()
        return {"success": False, "error": "WebUI not ready", "metadata": {"execution_path": "ready_gate"}}

    stack = make_stack(behavior, up=False)
    stack.submit(image("a"), image("b"))
    stack.start()
    wait_for(lambda: stack.queue.is_webui_held())
    settle()

    assert stack.status("a") is JobStatus.QUEUED  # not dispatched: restored with its identity
    assert stack.status("b") is JobStatus.QUEUED
    assert stack.calls == ["a"]
    snapshot = stack.coordinator.snapshot()
    assert snapshot["held_webui_jobs"] == 2 and snapshot["first_failure_category"] in {
        "pre_dispatch_unavailable",
        "readiness_failure",
    }


def test_mixed_queue_independent_video_continues_while_webui_work_stays_queued(make_stack):
    def behavior(job):
        return failed(**CONNECTION) if job.job_id.startswith("img") else {"success": True}

    stack = make_stack(behavior, up=False)
    stack.submit(image("img-A"), svd("svd-B"), comfy("cfy-C"), image("img-D"), svd("svd-E"))
    stack.start()
    wait_for(lambda: all(stack.status(j) is JobStatus.COMPLETED for j in ("svd-B", "cfy-C", "svd-E")))
    settle()

    assert stack.status("img-A") is JobStatus.QUEUED and stack.status("img-D") is JobStatus.QUEUED
    assert stack.calls.count("img-D") == 0  # held before it could dispatch
    assert stack.queue.is_paused() is False  # a backend-scoped hold, never the user's pause


def test_startup_gate_holds_webui_work_but_not_independent_video(make_stack):
    stack = make_stack(up=False, startup_gate=True)
    stack.submit(image("img-A"), svd("svd-B"), comfy("cfy-C"), image("img-D"))
    stack.start()
    wait_for(lambda: all(stack.status(j) is JobStatus.COMPLETED for j in ("svd-B", "cfy-C")))
    settle()
    assert [stack.status(j).value for j in ("img-A", "img-D")] == ["queued", "queued"]
    assert stack.coordinator.snapshot()["status"] == WebUIHealth.UNVERIFIED.value


def test_held_higher_priority_images_do_not_block_video_and_order_resumes_after_release(make_stack):
    stack = make_stack(up=False, startup_gate=True)
    stack.submit(
        image("img-low", JobPriority.LOW),
        image("img-n1"),
        image("img-high", JobPriority.HIGH),
        svd("svd-1"),
        image("img-n2"),
    )
    stack.start()
    wait_for(lambda: stack.status("svd-1") is JobStatus.COMPLETED)
    settle()
    assert stack.queued_order() == ["img-high", "img-n1", "img-n2", "img-low"]  # priority, then FIFO

    stack.backend.up = True
    wait_for(lambda: all(done(stack.status(j)) for j in ("img-high", "img-n1", "img-n2", "img-low")))
    executed_images = [c for c in stack.calls if c.startswith("img")]
    assert executed_images == ["img-high", "img-n1", "img-n2", "img-low"]


# =====================================================================================================================
# 4-5: manual dispatch and idle behavior
# =====================================================================================================================


def test_run_next_cannot_bypass_the_hold_and_claims_eligible_work(make_stack):
    stack = make_stack(up=False, startup_gate=True)
    stack.submit(image("img-1"), svd("svd-1"))

    assert stack.runner.run_next_once() is True  # eligible video is claimed, not the higher-ranked held image
    wait_for(lambda: stack.status("svd-1") is JobStatus.COMPLETED)
    wait_for(lambda: not stack.runner.is_running())

    assert stack.runner.run_next_once() is False  # only held work remains
    assert stack.status("img-1") is JobStatus.QUEUED
    assert stack.calls == ["svd-1"]
    # A direct transition attempt on a held job is refused under the same queue lock.
    assert stack.queue.mark_running("img-1") is None
    assert stack.status("img-1") is JobStatus.QUEUED


def test_a_hold_applied_between_selection_and_transition_cannot_dispatch_held_work(make_stack):
    stack = make_stack(up=True)
    stack.submit(image("img-1"))
    job = stack.queue.get_job("img-1")
    stack.queue.hold_webui_dispatch(reason="test")  # the hold lands after the caller picked the job
    assert stack.queue.mark_running(job.job_id) is None  # run_once()'s transition honors it atomically
    assert stack.runner.run_once(job) is None
    assert stack.status("img-1") is JobStatus.QUEUED and stack.calls == []


def test_only_held_work_does_not_spin_fail_or_corrupt_state(make_stack):
    stack = make_stack(up=False, startup_gate=True)
    stack.submit(*(image(f"img-{i}") for i in range(5)))
    claims = {"n": 0}
    real = stack.queue.claim_next_job

    def counting():
        claims["n"] += 1
        return real()

    stack.queue.claim_next_job = counting  # type: ignore[method-assign]
    stack.start()
    settle(0.6)

    assert claims["n"] <= 60  # held-only waits use the longer interval, not the 5 ms poll
    assert all(s == "queued" for s in stack.statuses().values())
    assert stack.calls == []
    assert stack.runner.is_running()  # waiting efficiently, still responsive


# =====================================================================================================================
# 6-8: recovery
# =====================================================================================================================


def test_successful_owned_recovery_is_one_cycle_and_resumes_held_work(make_stack):
    backend = Backend(up=False)
    manager = FakeManager(backend, owns=True, recovers=True)

    def behavior(job):
        return failed(**CONNECTION) if not backend.up else {"success": True}

    stack = make_stack(behavior, manager=manager)
    stack.submit(*(image(f"img-{i}") for i in range(4)))
    stack.start()
    wait_for(lambda: all(stack.status(f"img-{i}") is JobStatus.COMPLETED for i in range(4)))

    assert manager.restarts == 1  # one owned restart cycle for the incident
    assert (manager.stops, manager.starts) == (0, 0)  # only the manager's own restart authority acted
    snapshot = stack.coordinator.snapshot()
    assert snapshot["status"] == "healthy" and snapshot["last_recovery_result"] == "succeeded"
    assert snapshot["recovery_attempts"] == 1
    # The triggering job never reached the backend, so it was restored and executed once normally afterwards.
    assert stack.calls.count("img-0") == 2 and all(stack.calls.count(f"img-{i}") == 1 for i in (1, 2, 3))


def test_failed_recovery_keeps_the_hold_visible_and_independent_work_flows(make_stack):
    backend = Backend(up=False)
    manager = FakeManager(backend, owns=True, recovers=False)

    def behavior(job):
        return failed(**CONNECTION) if job.job_id.startswith("img") else {"success": True}

    stack = make_stack(behavior, manager=manager)
    stack.submit(image("img-1"), svd("svd-1"), image("img-2"), comfy("cfy-1"))
    stack.start()
    wait_for(lambda: all(stack.status(j) is JobStatus.COMPLETED for j in ("svd-1", "cfy-1")))
    settle()

    assert manager.restarts == 1  # bounded: not retried per job
    assert stack.status("img-1") is JobStatus.QUEUED and stack.status("img-2") is JobStatus.QUEUED
    snapshot = stack.coordinator.snapshot()
    assert snapshot["status"] == WebUIHealth.ACTION_REQUIRED.value
    assert snapshot["last_recovery_result"] == "failed"
    assert "operator action" in snapshot["message"] and snapshot["held_jobs_remain_queued"] is True
    assert snapshot["held_webui_jobs"] == 2


def test_recovery_budget_is_one_owned_cycle_per_incident(make_stack):
    backend = Backend(up=False)
    manager = FakeManager(backend, owns=True, recovers=False)
    stack = make_stack(manager=manager)
    first, second = image("img-1"), image("img-2")
    stack.submit(first, second)

    stack.coordinator.recover(stack.coordinator.assess(first, result=failed(**CONNECTION)))
    again = stack.coordinator.assess(second, result=failed(**CONNECTION))  # same unresolved incident
    stack.coordinator.recover(again)

    assert manager.restarts == 1  # more failing jobs in one incident never multiply restart cycles
    snapshot = stack.coordinator.snapshot()
    assert snapshot["recovery_attempts"] == 1 and snapshot["last_recovery_result"] == "budget_exhausted"
    assert snapshot["incident_id"] == again.incident_id


def test_external_runtime_is_never_stopped_started_restarted_or_adopted(make_stack):
    backend = Backend(up=False)
    manager = FakeManager(backend, owns=False)
    stack = make_stack(lambda job: failed(**CONNECTION), manager=manager)
    stack.submit(image("img-1"), image("img-2"))
    stack.start()
    wait_for(lambda: stack.queue.is_webui_held())
    settle()

    assert (manager.restarts, manager.stops, manager.starts) == (0, 0, 0)
    assert stack.coordinator.snapshot()["status"] == WebUIHealth.ACTION_REQUIRED.value
    assert stack.status("img-1") is JobStatus.QUEUED and stack.status("img-2") is JobStatus.QUEUED

    backend.up = True  # the operator brought the external runtime back: a fresh proof releases the hold
    wait_for(lambda: not stack.queue.is_webui_held())
    assert (manager.restarts, manager.stops, manager.starts) == (0, 0, 0)


# =====================================================================================================================
# 11-14: replay safety and ordinary failures
# =====================================================================================================================


@pytest.mark.parametrize("backend_up", [True, False], ids=["backend-healthy", "backend-down"])
def test_http_500_is_never_replayed(make_stack, backend_up):
    backend = Backend(up=backend_up)
    manager = FakeManager(backend, owns=True, recovers=True)
    stack = make_stack(lambda job: failed(http_status=500), manager=manager)
    stack.submit(image("img-1"), image("img-2"))
    stack.start()
    wait_for(lambda: done(stack.status("img-1")))
    settle()

    assert stack.status("img-1") is JobStatus.FAILED
    assert stack.calls.count("img-1") == 1  # exactly one generation attempt for the job
    assert (stack.queue.get_job("img-1").execution_metadata.return_to_queue_count) == 0


def test_outcome_unknown_stays_terminal_with_its_evidence_and_is_not_requeued(make_stack):
    backend = Backend(up=False)
    manager = FakeManager(backend, owns=True, recovers=True)
    unknown = failed(error_code=GenerateErrorCode.OUTCOME_UNKNOWN.value, request_may_have_executed=True)
    stack = make_stack(lambda job: unknown, manager=manager)
    stack.submit(image("img-1"))
    stack.start()
    wait_for(lambda: done(stack.status("img-1")))
    settle()

    job = stack.queue.get_job("img-1")
    assert job.status is JobStatus.FAILED
    assert job.result["metadata"]["failure_evidence"]["error_code"] == "outcome_unknown"
    assert stack.calls == ["img-1"]  # recovery of the backend is never permission to rerun the generation


@pytest.mark.parametrize(
    "fields",
    [
        {"error_code": GenerateErrorCode.INVALID_SAMPLER.value},
        {"error_code": GenerateErrorCode.INVALID_MODEL.value},
        {"error_code": GenerateErrorCode.PAYLOAD_VALIDATION.value},
        {"error_code": GenerateErrorCode.UNKNOWN.value, "http_status": 422},
        {"http_status": 400},
    ],
    ids=["sampler", "model", "payload", "unprocessable", "bad-request"],
)
def test_ordinary_failures_never_probe_hold_or_restart(make_stack, fields):
    backend = Backend(up=False)
    manager = FakeManager(backend, owns=True)
    stack = make_stack(lambda job: failed(**fields), manager=manager)
    stack.submit(image("img-1"), image("img-2"))
    stack.start()
    wait_for(lambda: done(stack.status("img-1")) and done(stack.status("img-2")))

    assert (manager.restarts, backend.probes) == (0, 0)
    assert stack.queue.is_webui_held() is False
    assert [stack.status(j) for j in ("img-1", "img-2")] == [JobStatus.FAILED, JobStatus.FAILED]


def test_cuda_out_of_memory_raised_is_an_ordinary_failure(make_stack):
    backend = Backend(up=False)
    manager = FakeManager(backend, owns=True)
    exc = RuntimeError("CUDA out of memory")
    stack = make_stack(lambda job: exc, manager=manager)
    stack.submit(image("img-1"))
    stack.start()
    wait_for(lambda: done(stack.status("img-1")))
    assert (manager.restarts, backend.probes) == (0, 0) and stack.queue.is_webui_held() is False


def test_svd_and_comfy_failures_do_not_trigger_webui_recovery(make_stack):
    backend = Backend(up=False)
    manager = FakeManager(backend, owns=True)
    stack = make_stack(lambda job: failed(**CONNECTION), manager=manager)  # even connection-typed evidence
    stack.submit(svd("svd-1"), comfy("cfy-1"))
    stack.start()
    wait_for(lambda: done(stack.status("svd-1")) and done(stack.status("cfy-1")))

    assert (manager.restarts, backend.probes) == (0, 0)
    assert stack.queue.is_webui_held() is False


def test_ambiguous_dependency_cannot_bypass_a_required_hold(make_stack):
    stack = make_stack(up=False, startup_gate=True)
    stack.submit(
        unresolved("workflow-no-backend"),
        make_queue_job("train", stage_chain=[make_stage_config("train_lora")]),
        image("other-backend", backend_options={"image": {"backend_id": "experimental_diffusers"}}),
        svd("svd-ok"),
    )
    stack.start()
    wait_for(lambda: stack.status("svd-ok") is JobStatus.COMPLETED)
    settle()
    assert stack.calls == ["svd-ok"]
    summary = stack.queue.dispatch_summary()
    assert summary["held_webui"] == 3 and summary["unresolved"] == 3


# =====================================================================================================================
# 16-18: races, ready events, shutdown
# =====================================================================================================================


def test_concurrent_recovery_callers_start_one_owned_restart(make_stack):
    backend = Backend(up=False)
    manager = FakeManager(backend, owns=True, recovers=True)
    manager.gate = threading.Event()
    stack = make_stack(manager=manager)
    job = image("img-1")
    stack.submit(job)
    decision = stack.coordinator.assess(job, result=failed(**CONNECTION))
    assert decision.outage_confirmed

    threads = [threading.Thread(target=lambda: stack.coordinator.recover(decision)) for _ in range(4)]
    threads[0].start()
    wait_for(lambda: manager.restarts == 1)
    for thread in threads[1:]:
        thread.start()
    settle(0.3)
    observed = manager.restarts
    manager.gate.set()
    for thread in threads:
        thread.join(DEADLINE)

    assert observed == 1 and manager.restarts == 1


def test_manager_restart_is_serialized_with_launch_and_ensure_running(monkeypatch):
    from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager

    monkeypatch.setattr(
        "src.utils.single_instance.SingleInstanceLock.is_gui_running", staticmethod(lambda *a, **k: True)
    )
    manager = WebUIProcessManager(
        WebUIProcessConfig(command=["x"], base_url=URL, runtime_identity="forge_webui")
    )
    monkeypatch.setattr(WebUIProcessManager, "owns_process", property(lambda self: True))
    inside = {"n": 0, "max": 0}
    entered, release = threading.Event(), threading.Event()
    guard = threading.Lock()

    def slow_stop(*a, **k):
        with guard:
            inside["n"] += 1
            inside["max"] = max(inside["max"], inside["n"])
        entered.set()
        release.wait(DEADLINE)
        with guard:
            inside["n"] -= 1
        return True

    monkeypatch.setattr(manager, "stop_webui", slow_stop)
    monkeypatch.setattr(manager, "start", lambda: (_ for _ in ()).throw(RuntimeError("no launch")))
    threads = [
        threading.Thread(target=lambda: manager.restart_webui(max_attempts=1)),
        threading.Thread(target=lambda: manager.restart_webui(max_attempts=1)),
    ]
    threads[0].start()
    assert entered.wait(DEADLINE)
    threads[1].start()
    settle(0.3)
    release.set()
    for thread in threads:
        thread.join(DEADLINE)

    assert inside["max"] == 1  # runner/executor/Launch recovery cannot overlap process actions


def test_a_ready_event_alone_does_not_release_without_a_fresh_proof(make_stack):
    backend = Backend(up=False)
    stack = make_stack(up=False, startup_gate=True)
    stack.backend = backend
    stack.coordinator._probe = backend.probe
    assert stack.queue.is_webui_held()
    stack.coordinator._on_manager_ready(SimpleNamespace(epoch=1))  # status says ready, the runtime does not
    assert stack.queue.is_webui_held() is True
    backend.up = True
    stack.coordinator._on_manager_ready(SimpleNamespace(epoch=2))  # now the proof holds
    assert stack.queue.is_webui_held() is False


def test_a_ready_event_during_recovery_neither_duplicates_it_nor_releases_stale(make_stack):
    backend = Backend(up=False)
    manager = FakeManager(backend, owns=True, recovers=True)
    manager.gate = threading.Event()
    stack = make_stack(manager=manager)
    job = image("img-1")
    stack.submit(job)
    decision = stack.coordinator.assess(job, result=failed(**CONNECTION))
    thread = threading.Thread(target=lambda: stack.coordinator.recover(decision))
    thread.start()
    wait_for(lambda: manager.restarts == 1)
    backend.up = True  # the manager would also emit READY here; the in-flight recovery owns the release
    assert stack.coordinator.maybe_release(force=True) is False
    assert stack.queue.is_webui_held() is True
    manager.gate.set()
    thread.join(DEADLINE)

    assert manager.restarts == 1 and stack.queue.is_webui_held() is False


def test_no_recovery_or_claim_after_the_shutdown_fence(make_stack):
    backend = Backend(up=False)
    manager = FakeManager(backend, owns=True, recovers=True)
    stack = make_stack(manager=manager)
    job = image("img-1")
    stack.submit(job)
    stack.queue.fence_dispatch()

    decision = stack.coordinator.assess(job, result=failed(**CONNECTION))
    stack.coordinator.recover(decision)

    assert decision.outage_confirmed is False and manager.restarts == 0
    assert stack.queue.claim_next_job() is None and stack.status("img-1") is JobStatus.QUEUED


# =====================================================================================================================
# 19-23: user control, restore, manipulation, persistence
# =====================================================================================================================


def test_user_pause_still_blocks_everything_and_is_never_changed_by_the_hold(make_stack):
    stack = make_stack(up=False, startup_gate=True)
    stack.submit(image("img-1"), svd("svd-1"))
    stack.queue.pause()
    assert stack.queue.claim_next_job() is None  # paused: even independent video
    stack.backend.up = True
    stack.coordinator.maybe_release(force=True)
    assert stack.queue.is_webui_held() is False
    assert stack.queue.is_paused() is True  # releasing a hold never resumes the user's pause
    assert stack.queue.claim_next_job() is None
    stack.queue.resume()
    assert stack.queue.claim_next_job().job_id == "img-1"


def test_recovery_never_enables_auto_run_or_starts_the_worker(tmp_path):
    queue = JobQueue(repository=JobRepository(tmp_path / "q.db"))
    backend = Backend(up=False)
    manager = FakeManager(backend, owns=True, recovers=True)
    coordinator = WebUIOutageCoordinator(
        queue, probe=backend.probe, manager_getter=lambda: manager, release_interval_s=0.0
    )
    runner = SingleNodeJobRunner(queue, lambda job: failed(**CONNECTION), poll_interval=0.005)
    service = JobService(queue, runner=runner)
    bind_webui_outage_containment(service, coordinator=coordinator)
    assert service.auto_run_enabled is False
    service.enqueue(image("img-1"))
    job = queue.get_job("img-1")

    decision = coordinator.assess(job, result=failed(**CONNECTION))
    coordinator.recover(decision)

    assert manager.restarts == 1 and queue.is_webui_held() is False
    assert service.auto_run_enabled is False  # the user's preference is untouched
    assert runner.is_running() is False  # nothing silently started the worker
    assert queue.get_job("img-1").status is JobStatus.QUEUED


def test_restart_restore_regates_webui_work_before_dispatch(tmp_path, make_stack):
    first = JobRepository(tmp_path / "persist.db")
    queue = JobQueue(repository=first)
    for job in (image("img-1"), svd("svd-1"), image("img-2")):
        queue.submit(job)

    reopened = JobRepository(tmp_path / "persist.db")
    stack = make_stack(up=False, startup_gate=True, repository=reopened)
    assert sorted(job.job_id for job in stack.queue.list_jobs()) == ["img-1", "img-2", "svd-1"]
    stack.start()
    wait_for(lambda: stack.status("svd-1") is JobStatus.COMPLETED)
    settle()
    assert stack.calls == ["svd-1"]  # image work waits for a fresh readiness proof after the restart
    stack.backend.up = True
    wait_for(lambda: all(stack.status(j) is JobStatus.COMPLETED for j in ("img-1", "img-2")))
    assert stack.calls == ["svd-1", "img-1", "img-2"]


def test_queue_manipulation_keeps_its_semantics_under_a_hold(make_stack):
    stack = make_stack(up=False, startup_gate=True)
    stack.submit(image("a"), image("b"), image("c"), svd("v"))
    assert stack.queue.move_to_back("a") is True
    assert stack.queued_order()[-1] in {"a", "v"}
    assert stack.queue.move_to_front("c") is True
    assert stack.queued_order()[0] == "c"
    removed = stack.queue.remove("b")
    assert removed is not None and stack.status("b") is JobStatus.CANCELLED
    assert stack.queue.mark_cancelled("a", "operator") is not None
    assert stack.status("a") is JobStatus.CANCELLED
    assert stack.queue.is_job_held("c") is True and stack.queue.is_job_held("v") is False


def test_requeue_preserves_identity_lineage_order_and_snapshot(make_stack):
    stack = make_stack(lambda job: failed(**CONNECTION) if job.job_id == "img-1" else {"success": True}, up=False)
    first, second = image("img-1"), image("img-2")
    stack.submit(first, second)
    fingerprint = [stack.repository.get_job_model(j).snapshot for j in ("img-1", "img-2")]
    stack.start()
    wait_for(lambda: stack.queue.is_webui_held())
    settle()

    job = stack.queue.get_job("img-1")
    assert job.status is JobStatus.QUEUED and job.job_id == "img-1"
    assert job.execution_metadata.return_to_queue_count == 1
    assert job.execution_metadata.last_control_action == "outage_requeue_undispatched"
    assert stack.queued_order() == ["img-1", "img-2"]  # original position, not the back of the queue
    assert [stack.repository.get_job_model(j).snapshot for j in ("img-1", "img-2")] == fingerprint
    assert len({j.job_id for j in stack.queue.list_jobs()}) == 2


def test_an_undispatched_job_is_requeued_at_most_a_bounded_number_of_times(make_stack):
    stack = make_stack(lambda job: failed(**CONNECTION), up=False)
    stack.submit(image("img-1"))
    job = stack.queue.get_job("img-1")
    for _ in range(3):
        stack.queue.claim_next_job()
        decision = stack.coordinator.assess(job, result=failed(**CONNECTION))
        if decision.requeue:
            stack.queue.return_undispatched_to_queue("img-1", reason="webui_outage")
            stack.queue.release_webui_dispatch()
    assert job.execution_metadata.return_to_queue_count == 2  # then the real failure is published


# =====================================================================================================================
# 24: projection
# =====================================================================================================================


def test_status_projection_is_deterministic_and_content_free(make_stack):
    stack = make_stack(up=False, startup_gate=True)
    stack.submit(image("a"), image("b"), svd("v"), comfy("c"), unresolved("u"))
    snapshot = stack.coordinator.snapshot()

    assert snapshot["status"] == "unverified"
    assert snapshot["held_webui_jobs"] == 3  # two images + the unresolved workflow
    assert snapshot["independent_jobs_eligible"] == 2
    assert snapshot["held_jobs_remain_queued"] is True
    assert "queued" in snapshot["message"]
    flat = repr(snapshot)
    assert "prompt" not in flat.lower() and "C:\\" not in flat and "/Users/" not in flat


def test_job_service_diagnostics_expose_hold_counts_and_incident(tmp_path):
    queue = JobQueue(repository=JobRepository(tmp_path / "q.db"))
    backend = Backend(up=False)
    coordinator = WebUIOutageCoordinator(queue, probe=backend.probe, manager_getter=lambda: None)
    service = JobService(queue, runner=SingleNodeJobRunner(queue, lambda job: {"success": True}))
    bind_webui_outage_containment(service, coordinator=coordinator)
    coordinator.enable_startup_gate()
    service.enqueue(image("img-1"))
    service.enqueue(svd("svd-1"))

    outage = service.get_diagnostics_snapshot()["webui_outage"]
    assert outage["held_webui_jobs"] == 1 and outage["independent_jobs_eligible"] == 1
    assert outage["status"] == "unverified" and outage["incident_id"].startswith("startup-")


def test_incident_records_are_machine_readable_and_bounded(make_stack):
    backend = Backend(up=False)
    manager = FakeManager(backend, owns=True, recovers=False)
    stack = make_stack(manager=manager)
    job = image("img-1")
    stack.submit(job)
    decision = stack.coordinator.assess(job, result=failed(**CONNECTION))
    stack.coordinator.recover(decision)

    events = [item["event"] for item in stack.coordinator.snapshot()["recent_incidents"]]
    assert events == ["outage_confirmed", "recovery_started", "recovery_failed"]
    started = stack.coordinator.snapshot()["recent_incidents"][1]
    assert started["owned"] is True and started["pid"] == 4242 and started["endpoint"] == URL
    assert "output_tail" not in started  # tails go to the log record, never into the default projection


# =====================================================================================================================
# Raised-exception evidence round trip
# =====================================================================================================================


def test_generate_error_exception_evidence_round_trip():
    from src.pipeline.executor import PipelineStageError

    error = GenerateError(
        code=GenerateErrorCode.OUTCOME_UNKNOWN,
        message="may have executed",
        stage="txt2img",
        details={"request_may_have_executed": True},
    )
    assessment = assess_exception(PipelineStageError(error))
    assert assessment.category is FailureCategory.OUTCOME_UNKNOWN and assessment.safe_to_requeue is False


def test_operator_readiness_projects_the_hold_through_the_existing_webui_record(make_stack):
    from src.services.operator_readiness_service import OperatorReadinessService

    stack = make_stack(up=False, startup_gate=True)
    stack.submit(image("a"), svd("v"))
    service = OperatorReadinessService(webui_outage_provider=stack.coordinator.snapshot)

    record = service._webui_record()

    assert record.id == "webui" and record.state.value == "action_required"
    joined = " ".join(record.blocking_reasons)
    assert "1 WebUI job(s) held" in joined and "1 independent video job(s) still eligible" in joined
    assert any("Launch or Retry" in action for action in record.operator_actions)

    stack.backend.up = True
    stack.coordinator.maybe_release(force=True)
    healthy = OperatorReadinessService(webui_outage_provider=stack.coordinator.snapshot)
    assert healthy._webui_outage() is None  # a healthy runtime falls back to the connection authority's record
