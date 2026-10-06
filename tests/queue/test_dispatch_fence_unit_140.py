"""PR-RUNTIME-SHUTDOWN-140: unit coverage of the queue dispatch fence and the runner's quiescence result."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from tests.helpers.njr_factory import make_queue_job

DEADLINE = 10.0


def _queue(tmp_path: Path, *ids: str) -> tuple[JobQueue, JobRepository]:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    for job_id in ids:
        queue.submit(make_queue_job(job_id))
    return queue, repository


# --- JobQueue fence ------------------------------------------------------------------------------


def test_a_fenced_queue_refuses_every_new_running_transition_and_keeps_jobs_queued(tmp_path: Path) -> None:
    queue, repository = _queue(tmp_path, "A", "B")

    queue.fence_dispatch()

    assert queue.is_dispatch_fenced() is True
    assert queue.claim_next_job() is None
    assert queue.get_next_job() is None
    assert queue.mark_running("A") is None
    assert [repository.get_job_model(j).status for j in ("A", "B")] == [JobStatus.QUEUED, JobStatus.QUEUED]
    repository.close()


def test_the_fence_never_blocks_the_job_that_already_owns_running(tmp_path: Path) -> None:
    queue, repository = _queue(tmp_path, "A", "B")
    claimed = queue.claim_next_job()
    assert claimed is not None and claimed.job_id == "A"

    queue.fence_dispatch()

    published = queue.publish_result("A", status=JobStatus.COMPLETED, result={"success": True}, stage_checkpoints=[])
    assert published is not None and repository.get_job_model("A").status is JobStatus.COMPLETED
    assert repository.get_job_model("B").status is JobStatus.QUEUED
    repository.close()


def test_return_to_queue_and_cancellation_of_the_running_job_still_work_when_fenced(tmp_path: Path) -> None:
    queue, repository = _queue(tmp_path, "A", "B")
    queue.claim_next_job()
    queue.fence_dispatch()

    queue.cancel_running_job(return_to_queue=True)

    assert repository.get_job_model("A").status is JobStatus.QUEUED  # durable: resumes on the next start
    assert queue.claim_next_job() is None
    repository.close()


def test_the_fence_is_process_lifetime_state_not_a_persisted_setting(tmp_path: Path) -> None:
    queue, repository = _queue(tmp_path, "A")
    queue.fence_dispatch()
    assert repository.get_setting("queue_paused", False) is False
    assert queue.is_paused() is False
    repository.close()

    restarted_repository = JobRepository(tmp_path / "jobs.sqlite3")
    restarted = JobQueue(repository=restarted_repository)
    try:
        assert restarted.is_dispatch_fenced() is False
        claimed = restarted.claim_next_job()
        assert claimed is not None and claimed.job_id == "A"  # the existing startup policy still drains it
    finally:
        restarted_repository.close()


def test_once_the_fence_returns_no_claim_can_succeed_even_against_concurrent_claimers(tmp_path: Path) -> None:
    ids = tuple(f"J{i:03d}" for i in range(120))
    queue, repository = _queue(tmp_path, *ids)
    start = threading.Barrier(5)
    fenced = threading.Event()
    claimed_after_fence: list[str] = []
    claimed_total: list[str] = []
    guard = threading.Lock()

    def claimer() -> None:
        start.wait(DEADLINE)
        while True:
            was_fenced = fenced.is_set()  # read BEFORE the claim: a claim that begins after the fence returned
            job = queue.claim_next_job()
            if job is None:
                return
            with guard:
                claimed_total.append(job.job_id)
                if was_fenced:
                    claimed_after_fence.append(job.job_id)

    threads = [threading.Thread(target=claimer) for _ in range(4)]
    for thread in threads:
        thread.start()
    start.wait(DEADLINE)
    queue.fence_dispatch()
    fenced.set()
    for thread in threads:
        thread.join(DEADLINE)

    assert claimed_after_fence == [], "a claim began after fence_dispatch() returned and still succeeded"
    running = [j for j in ids if repository.get_job_model(j).status is JobStatus.RUNNING]
    assert sorted(running) == sorted(claimed_total)  # every RUNNING row was claimed before the fence
    assert len(claimed_total) < len(ids) or queue.is_dispatch_fenced()
    repository.close()


# --- runner quiescence ---------------------------------------------------------------------------


def _runner(tmp_path: Path) -> tuple[SingleNodeJobRunner, JobQueue, JobRepository]:
    queue, repository = _queue(tmp_path)
    return SingleNodeJobRunner(queue, lambda job: {"success": True}, poll_interval=0.005), queue, repository


def test_an_idle_runner_is_quiescent_and_stop_reports_it(tmp_path: Path) -> None:
    runner, _queue_, repository = _runner(tmp_path)

    assert runner.is_quiescent() is True
    assert runner.stop() is True
    runner.start()
    assert runner.is_quiescent() is False
    assert runner.stop(timeout=DEADLINE) is True
    assert runner.is_quiescent() is True
    repository.close()


def test_quiescence_considers_every_launched_worker_not_only_the_latest(tmp_path: Path) -> None:
    runner, _queue_, repository = _runner(tmp_path)
    release = threading.Event()
    straggler = threading.Thread(target=release.wait, args=(DEADLINE,), daemon=True)
    straggler.start()
    runner._workers.append(straggler)  # a retired worker still unwinding while a replacement exists
    runner._worker = None

    assert runner.is_quiescent() is False
    assert runner.stop(timeout=0.1) is False  # a timed-out join is not quiescence
    release.set()
    straggler.join(DEADLINE)
    assert runner.is_quiescent() is True
    assert runner.stop(timeout=0.1) is True
    repository.close()


def test_begin_shutdown_makes_start_and_run_next_once_inert(tmp_path: Path) -> None:
    runner, queue, repository = _runner(tmp_path)
    queue.submit(make_queue_job("A"))

    runner.begin_shutdown()
    runner.begin_shutdown()  # idempotent
    runner.start()
    runner.request_continuous_dispatch()

    assert runner.run_next_once() is False
    assert runner._worker is None and runner.is_quiescent() is True
    assert repository.get_job_model("A").status is JobStatus.QUEUED
    repository.close()


def test_begin_shutdown_is_not_delayed_by_a_worker_inside_the_dispatch_policy_callback(tmp_path: Path) -> None:
    """The worker holds the runner lifecycle lock while it evaluates the policy; the fence must not wait for it."""

    runner, queue, repository = _runner(tmp_path)
    queue.submit(make_queue_job("A"))
    in_policy, proceed = threading.Event(), threading.Event()

    def blocking_policy() -> bool:
        in_policy.set()
        proceed.wait(DEADLINE)
        return True

    runner.set_continuous_dispatch_allowed(blocking_policy)
    runner.start()
    assert in_policy.wait(DEADLINE)

    done = threading.Event()
    fencer = threading.Thread(target=lambda: (runner.begin_shutdown(), done.set()), daemon=True)
    started = time.monotonic()
    fencer.start()
    assert done.wait(2.0), "begin_shutdown() blocked behind the dispatch-policy callback"
    assert time.monotonic() - started < 2.0

    proceed.set()
    assert runner.stop(timeout=DEADLINE) is True
    assert repository.get_job_model("A").status is JobStatus.QUEUED  # the pinned worker's claim was refused
    repository.close()
