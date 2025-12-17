"""Tests verifying JobService integrates with process containers."""

from __future__ import annotations

from src.controller import job_service as job_service_module
from src.controller.job_service import JobService
from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.utils.process_container_v2 import ProcessContainerConfig


class DummyRunner:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def is_running(self) -> bool:
        return False

    def run_once(self, job: Job) -> dict[str, object]:
        return {}

    def cancel_current(self) -> None:
        pass


class DummyWatchdog:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class FakeContainer:
    def __init__(self) -> None:
        self.added: list[int] = []
        self.killed = False
        self.teardown_called = False

    def add_pid(self, pid: int) -> None:
        self.added.append(pid)

    def kill_all(self) -> None:
        self.killed = True

    def teardown(self) -> None:
        self.teardown_called = True


def test_job_service_containers_receive_pids_and_kill(monkeypatch) -> None:
    job_queue = JobQueue()
    runner = DummyRunner()
    container = FakeContainer()
    config = ProcessContainerConfig(enabled=True)
    service = JobService(
        job_queue,
        runner,
        process_container_config=config,
        container_factory=lambda job_id, cfg: container,
    )
    job = Job(job_id="job-container")
    job_queue.submit(job)

    monkeypatch.setattr(job_service_module, "JobWatchdog", DummyWatchdog)

    service.register_external_process(job.job_id, 42)
    assert container.added == [42]

    job_queue.mark_running(job.job_id)
    service._handle_job_status_change(job, JobStatus.COMPLETED)

    assert container.killed
    assert container.teardown_called
