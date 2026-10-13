"""PR-QUEUE-GPU-180: the queue's GPU dispatch quarantine (eligibility, atomicity, persistence).

Real ``JobQueue`` / SQLite ``JobRepository`` / ``SingleNodeJobRunner``; no coordinator, host or backend involved.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from src.queue import backend_dependency
from src.queue.job_model import JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from tests.queue.test_webui_outage_containment_171 import comfy, image, svd, unresolved

INCIDENT = {
    "schema": "stablenew.gpu-dispatch-quarantine.v1",
    "incident_id": "gpu-test0001",
    "evidence_class": "confirmed_device_loss",
}


@pytest.fixture
def repository(tmp_path: Path):
    repo = JobRepository(tmp_path / "queue.db")
    yield repo
    try:
        repo.close()
    except Exception:
        pass


def queued_ids(queue: JobQueue) -> list[str]:
    return [job.job_id for job in queue.list_active_jobs_ordered() if job.status is JobStatus.QUEUED]


def test_quarantine_holds_every_gpu_job_without_reordering_or_mutating(repository):
    queue = JobQueue(repository=repository)
    jobs = [
        image("a"),
        svd("b"),
        comfy("c"),
        unresolved("d"),
        image("e", priority=JobPriority.HIGH),
    ]
    for job in jobs:
        queue.submit(job)
    order = queued_ids(queue)
    assert queue.quarantine_gpu_dispatch(INCIDENT) is True
    assert queue.is_gpu_quarantined()
    assert queue.claim_next_job() is None
    assert queue.get_next_job() is None
    assert all(queue.mark_running(job.job_id) is None for job in jobs)
    assert all(queue.is_job_held(job.job_id) for job in jobs)
    # Nothing moved: identity, status and original priority/FIFO order are intact.
    assert queued_ids(queue) == order == ["e", "a", "b", "c", "d"]
    assert {job.job_id: repository.get_job(job.job_id).status for job in jobs} == dict.fromkeys(
        (job.job_id for job in jobs), JobStatus.QUEUED
    )
    summary = queue.dispatch_summary()
    assert summary["queued"] == 5 and summary["held_gpu_loss"] == 5
    assert summary["eligible"] == 0 and summary["independent"] == 0 and summary["held_webui"] == 0
    assert summary["gpu_quarantine"]["incident_id"] == INCIDENT["incident_id"]


def test_release_restores_priority_then_fifo_order(repository):
    queue = JobQueue(repository=repository)
    for job in (image("a"), image("b", priority=JobPriority.HIGH), svd("c"), image("d")):
        queue.submit(job)
    queue.quarantine_gpu_dispatch(INCIDENT)
    assert queue.release_gpu_quarantine("some-other-incident") is False  # a stale approval releases nothing
    assert queue.is_gpu_quarantined()
    assert queue.release_gpu_quarantine(INCIDENT["incident_id"]) is True
    assert queue.release_gpu_quarantine(INCIDENT["incident_id"]) is False
    claimed = []
    while (job := queue.claim_next_job()) is not None:
        claimed.append(job.job_id)
    assert claimed == ["b", "a", "c", "d"]


def test_quarantine_is_first_incident_wins_and_requires_an_identity(repository):
    queue = JobQueue(repository=repository)
    assert queue.quarantine_gpu_dispatch(INCIDENT) is True
    assert queue.quarantine_gpu_dispatch({**INCIDENT, "incident_id": "gpu-second"}) is False
    assert queue.gpu_quarantine_info()["incident_id"] == INCIDENT["incident_id"]
    with pytest.raises(ValueError):
        queue.quarantine_gpu_dispatch({"evidence_class": "confirmed_device_loss"})


def test_quarantine_survives_restart_and_is_independent_of_the_user_pause(tmp_path):
    path = tmp_path / "restart.db"
    first = JobRepository(path)
    queue = JobQueue(repository=first)
    for job in (image("a"), svd("b"), comfy("c")):
        queue.submit(job)
    queue.quarantine_gpu_dispatch(INCIDENT)
    assert queue.is_paused() is False  # not the whole-queue pause
    first.close()

    second = JobRepository(path)
    try:
        restored = JobQueue(repository=second)
        assert restored.is_gpu_quarantined() and restored.is_paused() is False
        assert restored.gpu_quarantine_info()["incident_id"] == INCIDENT["incident_id"]
        assert queued_ids(restored) == ["a", "b", "c"]  # same SQLite identities, same order
        assert restored.claim_next_job() is None
        # The user's own pause is a separate persisted setting: releasing the quarantine never resumes it.
        restored.pause()
        assert restored.release_gpu_quarantine(INCIDENT["incident_id"]) is True
        assert restored.is_paused() is True and restored.claim_next_job() is None
        restored.resume()
        assert restored.claim_next_job().job_id == "a"
    finally:
        second.close()

    third = JobRepository(path)
    try:
        assert JobQueue(repository=third).is_gpu_quarantined() is False  # the release was durable
    finally:
        third.close()


def test_user_pause_does_not_clear_or_masquerade_as_the_quarantine(repository):
    queue = JobQueue(repository=repository)
    queue.submit(image("a"))
    queue.pause()
    queue.resume()
    assert not queue.is_gpu_quarantined()
    queue.quarantine_gpu_dispatch(INCIDENT)
    queue.pause()
    queue.resume()
    assert queue.is_gpu_quarantined() and queue.claim_next_job() is None


def test_unpersistable_incident_is_still_enforced_in_memory(repository, monkeypatch):
    queue = JobQueue(repository=repository)
    queue.submit(image("a"))

    def refuse(key, value):
        raise OSError("disk full")

    monkeypatch.setattr(repository, "set_setting", refuse)
    assert queue.quarantine_gpu_dispatch(INCIDENT) is True  # safety first: effective before it is durable
    assert queue.claim_next_job() is None
    assert queue.gpu_quarantine_info()["persisted"] is False
    assert queue.release_gpu_quarantine(INCIDENT["incident_id"]) is False  # cannot durably release either
    assert queue.is_gpu_quarantined()


def test_webui_hold_and_gpu_quarantine_are_independent(repository):
    queue = JobQueue(repository=repository)
    queue.submit(image("a"))
    queue.submit(svd("b"))
    queue.hold_webui_dispatch(reason="webui_down", incident_id="webui-1")
    queue.quarantine_gpu_dispatch(INCIDENT)
    summary = queue.dispatch_summary()
    assert summary["held_webui"] == 1 and summary["held_gpu_loss"] == 2 and summary["eligible"] == 0
    # A healthy WebUI releasing its own hold can never release the GPU quarantine...
    assert queue.release_webui_dispatch() is True
    assert queue.is_gpu_quarantined() and queue.claim_next_job() is None
    # ...and the GPU release does not release a WebUI hold that is still in force.
    queue.hold_webui_dispatch(reason="webui_down", incident_id="webui-2")
    assert queue.release_gpu_quarantine() is True
    assert queue.is_webui_held()
    assert queue.claim_next_job().job_id == "b"  # independent video flows once only the WebUI hold remains
    assert queue.claim_next_job() is None


def test_shutdown_fence_and_quarantine_compose(repository):
    queue = JobQueue(repository=repository)
    queue.submit(image("a"))
    queue.quarantine_gpu_dispatch(INCIDENT)
    queue.fence_dispatch()
    assert queue.release_gpu_quarantine() is True
    assert queue.claim_next_job() is None  # the fence still refuses


def test_proven_gpu_free_work_alone_continues(repository, monkeypatch):
    monkeypatch.setattr(backend_dependency, "_GPU_FREE_STAGES", frozenset({"txt2img"}))
    queue = JobQueue(repository=repository)
    queue.submit(svd("held-svd"))
    queue.submit(image("free"))
    queue.quarantine_gpu_dispatch(INCIDENT)
    assert queue.dispatch_summary()["held_gpu_loss"] == 1
    assert queue.claim_next_job().job_id == "free"
    assert queue.claim_next_job() is None


def test_runner_worker_and_manual_run_next_both_refuse_atomically(repository):
    queue = JobQueue(repository=repository)
    runs: list[str] = []
    runner = SingleNodeJobRunner(
        queue, lambda job: runs.append(job.job_id) or {"success": True}, poll_interval=0.005, held_poll_interval=0.01
    )
    for job in (image("a"), svd("b")):
        queue.submit(job)
    queue.quarantine_gpu_dispatch(INCIDENT)
    assert runner.run_next_once() is False  # manual Run Next
    assert runner.run_once(queue.get_job("a")) is None  # direct Run Now path
    runner.start()  # auto-run
    try:
        import time

        time.sleep(0.15)
    finally:
        assert runner.stop(timeout=3)
    assert runs == [] and queued_ids(queue) == ["a", "b"]
    queue.release_gpu_quarantine()
    assert runner.run_next_once() is True
    assert runner.stop(timeout=3)
    assert runs == ["a"]


def test_state_listeners_hear_quarantine_changes(repository):
    queue = JobQueue(repository=repository)
    listener = Mock()
    queue.register_state_listener(listener)
    queue.quarantine_gpu_dispatch(INCIDENT)
    queue.release_gpu_quarantine()
    assert listener.call_count == 2


def test_concurrent_apply_and_release_keep_durable_and_memory_state_identical(repository):
    import threading

    from src.queue.job_queue import GPU_QUARANTINE_SETTING

    queue = JobQueue(repository=repository)
    queue.submit(image("a"))
    barrier = threading.Barrier(3)

    def applier(tag: str) -> None:
        barrier.wait()
        for index in range(150):
            queue.quarantine_gpu_dispatch({"incident_id": f"gpu-{tag}-{index}", "evidence_class": "confirmed_device_loss"})

    def releaser() -> None:
        barrier.wait()
        for _ in range(300):
            queue.release_gpu_quarantine()

    threads = [
        threading.Thread(target=applier, args=("x",)),
        threading.Thread(target=applier, args=("y",)),
        threading.Thread(target=releaser),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    stored = repository.get_setting(GPU_QUARANTINE_SETTING, None)
    info = queue.gpu_quarantine_info()
    assert (stored is None) == (info is None)
    if info is not None:
        assert stored["incident_id"] == info["incident_id"]
        assert queue.claim_next_job() is None
    else:
        assert queue.claim_next_job().job_id == "a"


def test_quarantine_info_is_a_defensive_copy(repository):
    queue = JobQueue(repository=repository)
    queue.quarantine_gpu_dispatch({**INCIDENT, "trigger": {"job_id": "a"}})
    leaked = queue.gpu_quarantine_info()
    leaked["trigger"]["job_id"] = "tampered"
    leaked["incident_id"] = "tampered"
    assert queue.gpu_quarantine_info()["trigger"]["job_id"] == "a"
    assert queue.gpu_quarantine_info()["incident_id"] == INCIDENT["incident_id"]
    assert queue.dispatch_summary()["gpu_quarantine"]["trigger"]["job_id"] == "a"
