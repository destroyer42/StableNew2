"""A background write that failed, or is still pending, must not leave the job repository open at close.

Real ``AppController.shutdown_app`` over a real queue stack and the real process-wide ``PersistenceWorker``; only
the job callable, the WebUI manager and the blocked write are fakes.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.controller.app_controller_services import shutdown_coordinator as shutdown
from src.queue.job_model import JobStatus
from src.services import persistence_worker
from tests.controller.test_shutdown_quiescence_140 import Harness, _start_active_job


@pytest.fixture
def writer(monkeypatch: pytest.MonkeyPatch) -> Iterator[persistence_worker.PersistenceWorker]:
    monkeypatch.setattr(persistence_worker, "_global_worker", None)
    worker = persistence_worker.get_persistence_worker()
    yield worker
    worker.stop(timeout=5)


def _failing_task(tmp_path: Path, job_id: str) -> persistence_worker.PersistenceTask:
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("a file where the run folder should be", encoding="utf-8")
    data = {"file_path": str(blocker / "run_metadata.json"), "payload": {}, "job_id": job_id}
    return persistence_worker.PersistenceTask("run_metadata", data)


def _record_state_saves(built: Harness) -> list[str]:
    execution = built.controller.pipeline_controller._job_controller
    original = execution.persist_queue_state

    def save() -> None:
        built.repository.events.append("queue-state.save")
        original()

    execution.persist_queue_state = save  # type: ignore[method-assign]
    return built.repository.events


def test_one_failed_write_does_not_stop_the_close_from_saving_and_closing(
    tmp_path: Path, writer, caplog: pytest.LogCaptureFixture
) -> None:
    assert writer.enqueue(_failing_task(tmp_path, "earlier-job"))
    writer._queue.join()
    built = Harness(tmp_path)
    try:
        events = _record_state_saves(built)
        _start_active_job(built)

        with caplog.at_level(logging.ERROR):
            built.controller.shutdown_app("failed-write")

        outcome = built.controller._shutdown_outcome
        assert built.status("A") is JobStatus.QUEUED  # re-queued for the next start
        assert built.repository.close_calls == 1
        assert events.index("queue-state.save") < events.index("repository.close")
        assert outcome.repository == "closed" and outcome.persistence_drained
        assert any(
            "earlier-job" in record.getMessage() and record.levelno >= logging.ERROR
            for record in caplog.records
            if "failed earlier" in record.getMessage()
        )
    finally:
        built.cleanup()


def test_a_write_still_pending_at_close_does_not_keep_the_repository_open(
    tmp_path: Path, writer, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = threading.Event(), threading.Event()

    def stuck(_data) -> None:
        started.set()
        release.wait(10)

    monkeypatch.setattr(writer, "_write_manifest", stuck)
    monkeypatch.setattr(shutdown, "SHUTDOWN_BUDGET_SECONDS", 1.0)
    built = Harness(tmp_path)
    try:
        events = _record_state_saves(built)
        _start_active_job(built)
        assert writer.enqueue(persistence_worker.PersistenceTask("manifest", {}))
        assert started.wait(5)

        built.controller.shutdown_app("stuck-write")

        outcome = built.controller._shutdown_outcome
        assert built.status("A") is JobStatus.QUEUED
        assert outcome.repository == "closed" and built.repository.close_calls == 1
        assert (
            "queue-state.save" in events and "webui.stop" in events
        )  # the stuck write starves neither
        assert not outcome.persistence_drained and not outcome.completed
        assert "PersistenceWorker" in outcome.remaining_workers
        assert outcome.elapsed_seconds < 5
    finally:
        release.set()
        built.cleanup()


def test_a_runtime_release_that_outlasts_the_budget_does_not_keep_the_repository_open(
    tmp_path: Path, writer, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()
    monkeypatch.setattr(shutdown, "SHUTDOWN_BUDGET_SECONDS", 0.5)
    built = Harness(tmp_path)
    monkeypatch.setattr(built.webui, "stop_webui", lambda *_a, **_k: release.wait(10))
    try:
        events = _record_state_saves(built)
        _start_active_job(built)

        built.controller.shutdown_app("stuck-webui")

        outcome = built.controller._shutdown_outcome
        assert outcome.repository == "closed" and built.repository.close_calls == 1
        assert "queue-state.save" in events
        assert "webui-release" in outcome.failures and not outcome.completed
        assert outcome.elapsed_seconds < 5
    finally:
        release.set()
        built.cleanup()


def test_run_metadata_writes_carry_their_job_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.learning.run_metadata import write_run_metadata

    tasks: list = []
    monkeypatch.setattr(
        persistence_worker,
        "get_persistence_worker",
        lambda: type("Spy", (), {"enqueue": lambda _s, task, critical=False: tasks.append(task)})(),
    )

    write_run_metadata("run-folder", {}, base_dir=tmp_path, job_id="job-7")

    assert tasks[0].data["job_id"] == "job-7"
    assert "job_id" not in tasks[0].data["payload"]  # the file's content is unchanged


def test_a_failing_queue_state_save_still_closes_the_repository(
    tmp_path: Path, writer, caplog: pytest.LogCaptureFixture
) -> None:
    built = Harness(tmp_path, job_ids=())
    execution = built.controller.pipeline_controller._job_controller

    def broken() -> None:
        raise OSError("disk full")

    execution.persist_queue_state = broken  # type: ignore[method-assign]
    try:
        built.controller.shutdown_app("failed-state-save")

        outcome = built.controller._shutdown_outcome
        assert outcome.repository == "closed" and built.repository.close_calls == 1
        assert "queue-state" in outcome.failures and not outcome.completed
        assert "disk full" in caplog.text
    finally:
        built.cleanup()
