"""PR-RUNTIME-SHUTDOWN-140: the shutdown coordinator's decisions and the JobService shutdown boundary (no threads)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.controller import job_service_shutdown
from src.controller.app_controller_services import shutdown_coordinator as coordinator
from src.controller.job_service import JobService
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository


class FakeStore:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeService:
    """A service double with the production capabilities; ``quiescent`` is what it reports."""

    def __init__(self, *, quiescent: bool, stop_returns: bool | None = None) -> None:
        self.history_store = FakeStore()
        self.quiescent = quiescent
        self.stop_returns = stop_returns
        self.stop_calls: list[float | None] = []
        self.fenced = 0

    def begin_shutdown(self) -> None:
        self.fenced += 1

    def is_quiescent(self) -> bool:
        return self.quiescent

    def stop(self, timeout: float | None = None):
        self.stop_calls.append(timeout)
        return self.stop_returns


# --- coordinator ---------------------------------------------------------------------------------


def test_fencing_calls_the_service_fence_and_never_raises() -> None:
    service = FakeService(quiescent=True)
    assert coordinator.fence_queue_admission(service) is True and service.fenced == 1
    assert coordinator.fence_queue_admission(None) is False
    assert coordinator.fence_queue_admission(SimpleNamespace()) is False  # no capability: nothing to fence

    broken = SimpleNamespace(begin_shutdown=MagicMock(side_effect=RuntimeError("boom")))
    assert coordinator.fence_queue_admission(broken) is False


def test_quiescence_trusts_the_stop_result_and_falls_back_to_the_inspectable_state() -> None:
    assert coordinator.quiesce_job_service(FakeService(quiescent=False, stop_returns=True)) is True
    assert coordinator.quiesce_job_service(FakeService(quiescent=True, stop_returns=False)) is False
    assert coordinator.quiesce_job_service(FakeService(quiescent=True, stop_returns=None)) is True
    assert coordinator.quiesce_job_service(FakeService(quiescent=False, stop_returns=None)) is False


def test_quiescence_passes_the_bounded_timeout_and_survives_a_failing_stop(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    monkeypatch.setattr(coordinator, "QUEUE_QUIESCE_TIMEOUT_SECONDS", 3.5)
    service = FakeService(quiescent=True, stop_returns=True)
    assert coordinator.quiesce_job_service(service) is True
    assert service.stop_calls == [3.5]

    failing = SimpleNamespace(stop=MagicMock(side_effect=RuntimeError("stop failed")), is_quiescent=lambda: False)
    with caplog.at_level(logging.ERROR):
        assert coordinator.quiesce_job_service(failing) is False  # unknown outcome is never read as quiescence
    assert "did not quiesce" in caplog.text


def test_a_service_without_queue_inspection_is_not_blocked_from_closing() -> None:
    legacy = SimpleNamespace(history_store=FakeStore(), stop=lambda: None)

    assert coordinator.quiesce_job_service(legacy) is True
    assert coordinator.close_repository_when_quiescent(legacy) is True
    assert legacy.history_store.close_calls == 1


def test_the_repository_closes_when_quiescent_and_not_otherwise(caplog) -> None:
    quiet = FakeService(quiescent=True)
    with caplog.at_level(logging.INFO):
        assert coordinator.close_repository_when_quiescent(quiet) is True
    assert quiet.history_store.close_calls == 1 and "Job repository closed" in caplog.text

    caplog.clear()
    busy = FakeService(quiescent=False, stop_returns=False)
    with caplog.at_level(logging.INFO):
        assert coordinator.close_repository_when_quiescent(busy) is False
    assert busy.history_store.close_calls == 0
    assert "NOT closed" in caplog.text and "Job repository closed" not in caplog.text
    assert busy.stop_calls == [coordinator.REPOSITORY_FINAL_CHECK_SECONDS]  # one short final bounded check


def test_a_worker_that_quiesces_during_the_final_check_allows_the_close() -> None:
    late = FakeService(quiescent=False, stop_returns=True)

    assert coordinator.close_repository_when_quiescent(late) is True
    assert late.history_store.close_calls == 1


def test_a_failing_close_is_reported_not_raised(caplog) -> None:
    store = SimpleNamespace(close=MagicMock(side_effect=RuntimeError("disk")))
    service = SimpleNamespace(history_store=store, is_quiescent=lambda: True)

    with caplog.at_level(logging.ERROR):
        assert coordinator.close_repository_when_quiescent(service) is False
    assert "Error closing job repository" in caplog.text


# --- JobService boundary -------------------------------------------------------------------------


def _service(tmp_path, runner=None):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    return JobService(queue, runner=runner, require_normalized_records=True), queue, repository


def test_a_never_started_service_stops_without_touching_the_runner(tmp_path) -> None:
    runner = MagicMock()
    runner.is_quiescent.return_value = True
    service, _queue, repository = _service(tmp_path, runner)

    assert service.stop() is True
    runner.stop.assert_not_called()
    repository.close()


def test_stop_calls_a_legacy_runner_without_a_timeout_and_reports_its_state(tmp_path) -> None:
    class LegacyRunner:
        def __init__(self) -> None:
            self.stops = 0
            self.alive = True

        def start(self) -> None: ...
        def stop(self) -> None:
            self.stops += 1
            self.alive = False

        def is_running(self) -> bool:
            return self.alive

        def run_once(self, job): ...
        def cancel_current(self, *, return_to_queue: bool = False) -> None: ...

    runner = LegacyRunner()
    service, _queue, repository = _service(tmp_path, runner)
    service._worker_started = True

    assert service.stop(timeout=0.5) is True  # no is_quiescent: falls back to is_running()
    assert runner.stops == 1
    repository.close()


def test_begin_shutdown_fences_the_queue_even_for_a_runner_without_a_fence(tmp_path) -> None:
    class BareRunner:
        def start(self) -> None: ...
        def stop(self) -> None: ...
        def is_running(self) -> bool:
            return False

        def run_once(self, job): ...
        def cancel_current(self, *, return_to_queue: bool = False) -> None: ...

    service, queue, repository = _service(tmp_path, BareRunner())

    service.begin_shutdown()
    service.begin_shutdown()

    assert queue.is_dispatch_fenced() is True
    assert job_service_shutdown.is_shutting_down(service) is True
    assert service.run_next_now() is False
    repository.close()


def test_stop_always_reaches_a_live_one_shot_worker_even_if_the_service_never_marked_it_started(tmp_path) -> None:
    runner = MagicMock()
    runner.is_quiescent.side_effect = [False, True, True]  # alive, then quiescent after stop
    service, _queue, repository = _service(tmp_path, runner)
    assert service._worker_started is False

    assert service.stop() is True

    runner.stop.assert_called_once()
    repository.close()
