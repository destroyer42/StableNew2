"""PR-RUNTIME-HANDOFF: the small seams the cold-start handoff stands on (deterministic, no runtime, no process)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.api.webui_process_manager import (
    WebUIProcessConfig,
    WebUIProcessManager,
    clear_global_webui_process_manager,
)
from src.controller.job_service import JobService
from src.controller.job_service_outage import arm_runtime_handoff
from src.queue.backend_dependency import BackendDependency, classify_job
from src.queue.job_model import JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.helpers.njr_factory import make_queue_job, make_stage_config

FORGE = {"image": {"backend_id": "forge_webui"}}


def _video(job_id: str, **kwargs):
    return make_queue_job(
        job_id,
        stage_chain=[make_stage_config("video_workflow")],
        config={"video_workflow": {"video_execution": {"backend_id": "comfy"}}},
        **kwargs,
    )


@pytest.mark.parametrize(
    ("job", "expected"),
    [
        (lambda: make_queue_job("f", backend_options=FORGE), "forge_webui"),
        (
            lambda: make_queue_job("a", backend_options={"image": {"backend_id": "a1111_webui"}}),
            "a1111_webui",
        ),
        (
            lambda: make_queue_job("legacy"),
            "a1111_webui",
        ),  # a record with no identity resolves as at execution
        (lambda: _video("c"), ""),
        (
            lambda: make_queue_job(
                "x", backend_options={"image": {"backend_id": "experimental_diffusers"}}
            ),
            "",
        ),
    ],
)
def test_the_dependency_assessment_carries_the_frozen_webui_backend_identity(job, expected):
    assessment = classify_job(job())
    assert assessment.webui_backend_id == expected
    if expected:
        assert assessment.dependency is BackendDependency.REQUIRES_WEBUI


def _queue() -> JobQueue:
    return JobQueue(repository=JobRepository(":memory:"))


def test_peek_returns_the_next_claim_in_priority_then_fifo_order_without_claiming():
    queue = _queue()
    queue.submit(make_queue_job("n1"))
    queue.submit(make_queue_job("low", priority=JobPriority.LOW))
    queue.submit(make_queue_job("high", priority=JobPriority.HIGH))
    queue.submit(make_queue_job("n2"))

    assert queue.peek_next_dispatch_candidate().job_id == "high"
    assert (
        queue.peek_next_dispatch_candidate().job_id == "high"
    )  # an observation: nothing was popped or claimed
    assert queue.get_job("high").status is JobStatus.QUEUED
    assert [queue.claim_next_job().job_id for _ in range(4)] == ["high", "n1", "n2", "low"]
    assert queue.peek_next_dispatch_candidate() is None


def test_peek_ignores_the_webui_hold_but_not_pause_fence_or_gpu_quarantine():
    queue = _queue()
    queue.submit(make_queue_job("img", backend_options=FORGE))
    queue.submit(_video("vid"))

    queue.hold_webui_dispatch(reason="test", incident_id="i")
    assert (
        queue.peek_next_dispatch_candidate().job_id == "img"
    )  # the hold is what the handoff must act on
    assert queue.claim_next_job().job_id == "vid"  # ... while the real claim still honors it

    queue.pause()
    assert queue.peek_next_dispatch_candidate() is None
    queue.resume()
    queue.quarantine_gpu_dispatch({"incident_id": "g"})
    assert queue.peek_next_dispatch_candidate() is None  # every stage here is GPU work
    queue.release_gpu_quarantine("g")
    queue.fence_dispatch()
    assert queue.peek_next_dispatch_candidate() is None


def test_the_manager_exposes_its_autostart_permission_read_only():
    clear_global_webui_process_manager()
    try:
        enabled = WebUIProcessManager(WebUIProcessConfig(command=["x"], autostart_enabled=True))
        assert enabled.autostart_enabled is True
        disabled = WebUIProcessManager(WebUIProcessConfig(command=["x"], autostart_enabled=False))
        assert disabled.autostart_enabled is False
        with pytest.raises(AttributeError):
            disabled.autostart_enabled = True  # type: ignore[misc]
    finally:
        clear_global_webui_process_manager()


def test_only_production_wiring_arms_the_handoff():
    service = JobService(_queue())  # how every injected/test service is built
    assert service.webui_outage.snapshot()["runtime_handoff"]["armed"] is False

    assert arm_runtime_handoff(service) is True
    assert service.webui_outage.snapshot()["runtime_handoff"]["armed"] is True
    assert arm_runtime_handoff(SimpleNamespace()) is False
