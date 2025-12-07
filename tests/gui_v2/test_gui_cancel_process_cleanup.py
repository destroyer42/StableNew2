"""GUI tests confirming AppController stop delegates to JobService cancellation."""

from __future__ import annotations

from src.controller.app_controller import AppController, CancelToken, LifecycleState
from src.controller.job_service import JobService
from src.queue.job_model import Job
from src.queue.job_queue import JobQueue


class DummyRunner:
    def __init__(self) -> None:
        self.current_job = None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def is_running(self) -> bool:
        return False

    def run_once(self, job: Job) -> dict[str, object]:
        self.current_job = job
        return {}

    def cancel_current(self) -> None:
        self.current_job = None


class SpyJobService(JobService):
    def __init__(self, job_queue: JobQueue, runner: DummyRunner) -> None:
        super().__init__(job_queue, runner)
        self.cancel_calls = 0

    def cancel_current(self) -> None:
        self.cancel_calls += 1
        super().cancel_current()


def test_stop_delegates_to_job_service_cancel() -> None:
    job_queue = JobQueue()
    runner = DummyRunner()
    service = SpyJobService(job_queue, runner)
    controller = AppController(None, job_service=service)
    controller.state.lifecycle = LifecycleState.RUNNING
    controller._cancel_token = CancelToken()

    controller.on_stop_clicked()

    assert service.cancel_calls == 1


def test_cancel_job_v2_delegates_to_job_service() -> None:
    job_queue = JobQueue()
    runner = DummyRunner()
    service = SpyJobService(job_queue, runner)
    controller = AppController(None, job_service=service)

    controller.on_cancel_job_v2()

    assert service.cancel_calls == 1


def test_cancel_job_and_return_v2_delegates_to_job_service() -> None:
    job_queue = JobQueue()
    runner = DummyRunner()
    service = SpyJobService(job_queue, runner)
    controller = AppController(None, job_service=service)

    controller.on_cancel_job_and_return_v2()

    assert service.cancel_calls == 1
