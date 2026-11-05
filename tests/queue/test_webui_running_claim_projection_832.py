"""GP832-F2: a RUNNING WebUI job and the outage / readiness projections must tell the same story.

Real ``JobQueue`` / SQLite ``JobRepository`` / ``SingleNodeJobRunner`` / ``WebUIOutageCoordinator``; only the generation
callable (which blocks the way the executor's readiness wait does), the readiness probe and the connection authority
are fakes. No test requires a real WebUI and no job is ever forced out of RUNNING by a projection.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.queue.job_model import JobStatus
from src.services.operator_readiness_service import OperatorReadinessService
from tests.queue.test_webui_outage_containment_171 import (
    CONNECTION,
    DEADLINE,
    Stack,
    failed,
    image,
    svd,
    wait_for,
)


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


def _readiness(stack: Stack, state: str = "disconnected") -> OperatorReadinessService:
    return OperatorReadinessService(
        webui_outage_provider=stack.coordinator.snapshot,
        webui_connection=SimpleNamespace(get_state=lambda: state, last_readiness_error=None),
    )


def test_claimed_job_waiting_on_an_unreachable_backend_is_running_and_projected_as_such(make_stack):
    """(b) The claim was legitimate (no hold existed); the lifecycle is untouched and the projections name the job."""

    release = threading.Event()
    calls: list[str] = []

    def behavior(job):
        calls.append(job.job_id)
        if len(calls) == 1:
            assert release.wait(
                DEADLINE
            )  # the executor's readiness wait: nothing has been dispatched yet
            return failed(**CONNECTION)
        return {"success": True}

    stack = make_stack(behavior, up=False)
    stack.submit(image("j1"))
    stack.start()
    wait_for(lambda: stack.statuses().get("j1") == "running")

    summary = stack.queue.dispatch_summary()
    assert summary["hold"] is None and summary["held"] == 0 and summary["running_webui"] == 1
    snapshot = stack.coordinator.snapshot()
    assert snapshot["running_webui_jobs"] == 1 and snapshot["held_webui_jobs"] == 0
    record = _readiness(stack)._webui_record()
    joined = " ".join(record.blocking_reasons)
    assert "1 WebUI job(s) already claimed are RUNNING while WebUI is not ready" in joined
    assert stack.statuses()["j1"] == "running" and calls == [
        "j1"
    ]  # never forced back to QUEUED by a projection

    release.set()  # typed NOT_DISPATCHED evidence: the existing coordinator restores it and applies the hold
    wait_for(lambda: stack.statuses().get("j1") == "queued")
    after = stack.queue.dispatch_summary()
    assert after["hold"] is not None and after["held_webui"] == 1 and after["running_webui"] == 0
    assert stack.coordinator.snapshot()["running_webui_jobs"] == 0

    stack.backend.up = True  # backend returns: one fresh proof releases the hold and the job runs exactly once more
    stack.coordinator.maybe_release(force=True)
    wait_for(lambda: stack.statuses().get("j1") == "completed")
    assert calls == ["j1", "j1"]


def test_hold_with_a_still_running_claimed_job_is_not_described_as_all_jobs_held(make_stack):
    """The window the finding describes: the outage is confirmed (hold applied) while the claimed job is RUNNING."""

    release = threading.Event()
    stack = make_stack(lambda job: (release.wait(DEADLINE), {"success": True})[1], up=False)
    stack.submit(image("j1"))
    stack.start()
    wait_for(lambda: stack.statuses().get("j1") == "running")
    running = stack.queue.get_job("j1")
    assert running is not None

    decision = stack.coordinator.assess(
        running, result=failed(**CONNECTION)
    )  # confirms the outage, applies the hold
    assert decision.outage_confirmed and stack.statuses()["j1"] == "running"

    snapshot = stack.coordinator.snapshot()
    assert snapshot["status"] != "healthy" and snapshot["held_webui_jobs"] == 0
    assert snapshot["running_webui_jobs"] == 1
    record = _readiness(stack)._webui_record()
    joined = " ".join(record.blocking_reasons)
    assert "0 WebUI job(s) held in the queue" in joined
    # The headline must not say jobs are held in the queue while the only job is running and none is held.
    assert "jobs are held in the queue" not in record.summary and "RUNNING" in record.summary
    assert (
        "1 WebUI job(s) were claimed before the outage was confirmed and are still RUNNING, not held"
        in joined
    )
    release.set()


def test_independent_running_video_work_is_not_reported_as_a_running_webui_job(make_stack):
    release = threading.Event()
    stack = make_stack(lambda job: (release.wait(DEADLINE), {"success": True})[1], up=False)
    stack.submit(svd("v1"))
    stack.start()
    wait_for(lambda: stack.statuses().get("v1") == "running")

    assert stack.queue.dispatch_summary()["running_webui"] == 0
    assert stack.coordinator.snapshot()["running_webui_jobs"] == 0
    assert "already claimed" not in " ".join(_readiness(stack)._webui_record().blocking_reasons)
    release.set()
    wait_for(
        lambda: stack.queue.get_job("v1") is None
        or stack.queue.get_job("v1").status is not JobStatus.RUNNING
    )
