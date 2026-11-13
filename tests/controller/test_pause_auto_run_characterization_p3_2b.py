"""P3-2B / OD-5 characterization: who owns pause and auto-run today, what persists, and what differs.

Characterization only. Nothing here asserts a desired design: each test pins what the code does on ``main`` so that a
later ownership decision (OD-5) changes a named test on purpose instead of silently. No ownership, default or restart
behaviour is changed by the package that adds this file.

Facts pinned:

* ``JobExecutionController`` defaults ``auto_run_enabled`` to ``True``; ``JobService`` defaults it to ``False``.
* ``auto_run_enabled`` persists only through ``JobExecutionController`` (repository setting ``auto_run_enabled``);
  ``JobService.set_auto_run_enabled`` is in-memory only and writes no setting.
* Pause persists as the repository setting ``queue_paused`` whichever object pauses: ``JobQueue.pause`` writes it, so
  both ``JobService.pause`` and ``JobExecutionController.set_queue_paused`` survive a restart.
* ``JobService.pause`` does not update ``JobExecutionController``'s own cached ``is_queue_paused`` flag; the
  ``PipelineController`` pause handlers update both, ``AppController.on_pause_queue`` updates only the service.
* Restart: ``JobExecutionController`` restores ``auto_run_enabled`` from settings (default ``True`` when absent) and
  ``is_queue_paused`` from the queue; it flags a deferred autostart only for restored QUEUED jobs with auto-run on and
  the queue not paused. A fresh ``JobService`` starts with auto-run off until ``AppController`` copies the controller's
  flag onto it (``ApplicationRuntimeCoordinator.sync_queue_state``).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.controller.app_controller_services.application_runtime_coordinator import (
    ApplicationRuntimeCoordinator,
)
from src.controller.job_execution_controller import JobExecutionController
from src.controller.job_service import JobService
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.helpers.njr_factory import make_queue_job

_ABSENT = object()


def _controller(repository: JobRepository) -> JobExecutionController:
    return JobExecutionController(repository=repository, runner=MagicMock(), restore_state=True)


def _service(repository: JobRepository) -> JobService:
    queue = JobQueue(repository=repository)
    return JobService(job_queue=queue, runner=MagicMock(), history_store=repository)


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "jobs.sqlite3"


# -- defaults --------------------------------------------------------------------------------------------------


def test_defaults_differ_between_the_execution_controller_and_the_service() -> None:
    repository = JobRepository(":memory:")
    try:
        controller = _controller(repository)
        service = _service(repository)
        assert controller.auto_run_enabled is True
        assert controller.is_queue_paused is False
        assert service.auto_run_enabled is False
        assert service.job_queue.is_paused() is False
    finally:
        repository.close()


# -- what persists ---------------------------------------------------------------------------------------------


def test_controller_persists_auto_run_and_pause_as_repository_settings() -> None:
    repository = JobRepository(":memory:")
    try:
        controller = _controller(repository)
        controller.set_auto_run_enabled(False)
        controller.set_queue_paused(True)
        assert repository.get_setting("auto_run_enabled", _ABSENT) is False
        assert repository.get_setting("queue_paused", _ABSENT) is True
    finally:
        repository.close()


def test_service_auto_run_is_in_memory_only_but_service_pause_is_persisted() -> None:
    repository = JobRepository(":memory:")
    try:
        service = _service(repository)
        service.set_auto_run_enabled(True)
        service.set_auto_run_enabled(False)
        # No auto-run setting is ever written through the service.
        assert repository.get_setting("auto_run_enabled", _ABSENT) is _ABSENT
        service.pause()
        assert repository.get_setting("queue_paused", _ABSENT) is True
        service.resume()
        assert repository.get_setting("queue_paused", _ABSENT) is False
    finally:
        repository.close()


def test_service_pause_does_not_update_the_controllers_cached_pause_flag() -> None:
    repository = JobRepository(":memory:")
    try:
        queue = JobQueue(repository=repository)
        controller = JobExecutionController(
            repository=repository, queue=queue, runner=MagicMock(), restore_state=True
        )
        service = JobService(job_queue=queue, runner=MagicMock(), history_store=repository)
        service.pause()
        assert queue.is_paused() is True
        assert (
            controller.is_queue_paused is False
        )  # the controller caches its own flag; only set_queue_paused updates it
        controller.set_queue_paused(True)
        assert controller.is_queue_paused is True
    finally:
        repository.close()


# -- restart ---------------------------------------------------------------------------------------------------


def test_restart_restores_controller_flags_from_settings(repo_path: Path) -> None:
    first = JobRepository(repo_path)
    try:
        controller = _controller(first)
        controller.set_auto_run_enabled(False)
        controller.set_queue_paused(True)
    finally:
        first.close()

    second = JobRepository(repo_path)
    try:
        restarted = _controller(second)
        assert restarted.auto_run_enabled is False
        assert restarted.is_queue_paused is True
        assert restarted.get_queue().is_paused() is True
    finally:
        second.close()


def test_restart_defaults_auto_run_on_when_no_setting_was_ever_written(repo_path: Path) -> None:
    first = JobRepository(repo_path)
    try:
        _service(first).set_auto_run_enabled(
            False
        )  # in-memory on the service; nothing is persisted
    finally:
        first.close()

    second = JobRepository(repo_path)
    try:
        assert second.get_setting("auto_run_enabled", _ABSENT) is _ABSENT
        assert _controller(second).auto_run_enabled is True
        assert _service(second).auto_run_enabled is False
    finally:
        second.close()


def test_a_pause_made_through_the_service_alone_survives_restart(repo_path: Path) -> None:
    first = JobRepository(repo_path)
    try:
        _service(first).pause()
    finally:
        first.close()

    second = JobRepository(repo_path)
    try:
        restarted = _controller(second)
        assert (
            restarted.is_queue_paused is True
        )  # restored from the queue, which read the persisted setting
        assert _service(second).job_queue.is_paused() is True
    finally:
        second.close()


@pytest.mark.parametrize(
    ("auto_run", "paused", "expect_deferred_autostart"),
    [
        (True, False, True),
        (True, True, False),
        (False, False, False),
        (False, True, False),
    ],
)
def test_deferred_autostart_is_flagged_only_for_queued_jobs_with_auto_run_on_and_not_paused(
    repo_path: Path, auto_run: bool, paused: bool, expect_deferred_autostart: bool
) -> None:
    first = JobRepository(repo_path)
    try:
        controller = _controller(first)
        controller.get_queue().submit(make_queue_job("job-restored"))
        controller.set_auto_run_enabled(auto_run)
        controller.set_queue_paused(paused)
    finally:
        first.close()

    second = JobRepository(repo_path)
    try:
        restarted = _controller(second)
        assert [job.job_id for job in restarted.get_queue().list_jobs()] == ["job-restored"]
        assert restarted._deferred_autostart is expect_deferred_autostart
    finally:
        second.close()


def test_no_queued_jobs_means_no_deferred_autostart_even_with_auto_run_on(repo_path: Path) -> None:
    repository = JobRepository(repo_path)
    try:
        controller = _controller(repository)
        assert controller.auto_run_enabled is True
        assert controller._deferred_autostart is False
    finally:
        repository.close()


def test_sync_queue_state_copies_the_controllers_flags_onto_the_service_and_app_state() -> None:
    repository = JobRepository(":memory:")
    try:
        controller = _controller(repository)
        controller.set_auto_run_enabled(True)
        controller.set_queue_paused(True)
        service = _service(repository)
        assert (
            service.auto_run_enabled is False
        )  # fresh service default, before AppController syncs it
        app_state = MagicMock()
        ApplicationRuntimeCoordinator(
            job_controller=controller, webui_connection_controller=None
        ).sync_queue_state(app_state=app_state, job_service=service)
        assert service.auto_run_enabled is True
        app_state.set_auto_run_queue.assert_called_once_with(True)
        app_state.set_is_queue_paused.assert_called_once_with(True)
    finally:
        repository.close()
