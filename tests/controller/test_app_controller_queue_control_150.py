"""PR-RUNTIME-QUEUE-150: the live AppController queue-control boundary uses the JobService lifecycle.

The Pipeline tab hands ``AppController`` to ``QueuePanelV2``. Its Pause/Resume/Send actions must reuse the one
canonical ``PipelineController`` -> ``JobService`` lifecycle (the same one the controller integration tests prove)
instead of mutating ``JobQueue`` directly, and Send Job must report a truthful boolean.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pytest

from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.gui.app_state_v2 import AppStateV2
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.config import ConfigManager
from tests.helpers.fake_pipeline_runner import FakePipelineRunner
from tests.helpers.njr_factory import make_queue_job

DEADLINE = 10.0


class _Window:
    root = None

    def __init__(self, app_state: AppStateV2) -> None:
        self.app_state = app_state

    @staticmethod
    def run_in_main_thread(callback: Callable[[], None]) -> None:
        callback()

    @staticmethod
    def run_in_main_thread_later(_delay_ms: int, callback: Callable[[], None]) -> None:
        callback()

    @staticmethod
    def connect_controller(_controller: object) -> None:
        return None


class _Stack:
    def __init__(self, tmp_path: Path, *, auto_run: bool) -> None:
        self.repository = JobRepository(tmp_path / "jobs.sqlite3")
        self.queue = JobQueue(repository=self.repository)
        self.executed: list[str] = []

        def execute(job):
            self.executed.append(job.job_id)
            return {"success": True, "variants": []}

        self.service = JobService(self.queue, run_callable=execute, require_normalized_records=True)
        self.lifecycle_calls: list[str] = []
        for name in ("pause", "resume"):
            self._record(name)
        self.app_state = AppStateV2()
        self.app_state.auto_run_queue = auto_run
        self.controller = AppController(
            main_window=None,
            threaded=False,
            pipeline_runner=FakePipelineRunner(),
            job_service=self.service,
            config_manager=ConfigManager(presets_dir=tmp_path / "presets"),
        )
        self.controller.load_packs = lambda: None  # type: ignore[method-assign]
        self.controller._update_status = lambda *_a, **_k: None  # type: ignore[method-assign]
        self.controller.set_main_window(_Window(self.app_state))
        self.service.auto_run_enabled = auto_run

    def _record(self, name: str) -> None:
        """Observe (not replace) the real JobService lifecycle method."""
        real = getattr(self.service, name)

        def observed() -> None:
            self.lifecycle_calls.append(name)
            real()

        setattr(self.service, name, observed)

    def enqueue(self, *job_ids: str) -> None:
        for job_id in job_ids:
            self.service.enqueue(make_queue_job(job_id))

    def queued_ids(self) -> list[str]:
        return [job.job_id for job in self.queue.list_jobs(JobStatus.QUEUED)]

    def durable_paused(self) -> bool:
        return bool(self.repository.get_setting("queue_paused", False))

    def wait_until(self, predicate: Callable[[], bool]) -> None:
        deadline = time.monotonic() + DEADLINE
        while time.monotonic() < deadline and not predicate():
            time.sleep(0.01)
        assert predicate(), "condition did not settle before the deadline"

    def close(self) -> None:
        self.service.stop()
        self.repository.close()


@pytest.fixture
def stack_factory(tmp_path):
    stacks: list[_Stack] = []

    def build(*, auto_run: bool) -> _Stack:
        stack = _Stack(tmp_path, auto_run=auto_run)
        stacks.append(stack)
        return stack

    yield build
    for stack in stacks:
        stack.close()


def test_pause_and_resume_use_the_jobservice_lifecycle_and_agree_everywhere(stack_factory) -> None:
    stack = stack_factory(auto_run=False)
    stack.enqueue("job-a")
    controller = stack.controller

    controller.on_pause_queue_v2()
    assert stack.lifecycle_calls == ["pause"]
    assert stack.durable_paused() is True
    assert stack.queue.is_paused() is True
    assert stack.app_state.is_queue_paused is True
    assert controller.pipeline_controller.get_job_execution_controller().is_queue_paused is True

    controller.on_resume_queue_v2()
    assert stack.lifecycle_calls == ["pause", "resume"]
    assert stack.durable_paused() is False
    assert stack.queue.is_paused() is False
    assert stack.app_state.is_queue_paused is False
    assert controller.pipeline_controller.get_job_execution_controller().is_queue_paused is False
    # Auto-run OFF: unpausing is not dispatching.
    assert stack.executed == []
    assert stack.queued_ids() == ["job-a"]
    assert stack.service.runner.is_running() is False


def test_resume_with_auto_run_on_restarts_the_worker(stack_factory) -> None:
    stack = stack_factory(auto_run=True)
    stack.controller.on_pause_queue_v2()
    stack.enqueue("job-a")
    assert stack.executed == []

    stack.controller.on_resume_queue_v2()

    stack.wait_until(lambda: stack.executed == ["job-a"])
    assert stack.durable_paused() is False
    assert stack.app_state.is_queue_paused is False


def test_send_job_is_refused_while_paused_and_reports_false(stack_factory) -> None:
    stack = stack_factory(auto_run=False)
    stack.enqueue("job-a", "job-b")
    stack.controller.on_pause_queue_v2()

    assert stack.controller.on_queue_send_job_v2() is False

    assert stack.executed == []
    assert stack.queued_ids() == ["job-a", "job-b"]


def test_send_job_after_resume_dispatches_exactly_the_top_job_and_reports_true(stack_factory) -> None:
    stack = stack_factory(auto_run=False)
    stack.enqueue("job-a", "job-b")
    controller = stack.controller
    controller.on_pause_queue_v2()
    controller.on_resume_queue_v2()

    assert controller.on_queue_send_job_v2() is True

    stack.wait_until(lambda: stack.repository.get_job("job-a").status is JobStatus.COMPLETED)
    stack.wait_until(lambda: not stack.service.runner.is_running())
    assert stack.executed == ["job-a"]
    assert stack.queued_ids() == ["job-b"]


def test_send_job_trusts_the_durable_queue_not_the_app_state_projection(stack_factory) -> None:
    """AppState is a projection: a stale ``is_queue_paused`` flag must neither allow nor block a real dispatch."""
    stack = stack_factory(auto_run=False)
    stack.enqueue("job-a")
    stack.queue.pause()  # genuinely paused, projection still says "not paused"
    assert stack.app_state.is_queue_paused is False
    assert stack.controller.on_queue_send_job_v2() is False
    assert stack.executed == []

    stack.queue.resume()
    stack.app_state.set_is_queue_paused(True)  # genuinely unpaused, projection stale "paused"
    assert stack.controller.on_queue_send_job_v2() is True
    stack.wait_until(lambda: stack.executed == ["job-a"])
