from types import SimpleNamespace

# Need WebUIConnectionState for stubbing the ensure_connected result
from src.controller.pipeline_controller import PipelineController
from src.controller.webui_connection_controller import WebUIConnectionState
from src.queue.job_model import JobStatus


class FakeJobExecutionController:
    def __init__(self) -> None:
        self.submitted = []
        self.cancelled = []
        self.callbacks: dict[str, callable] = {}

    def submit_pipeline_run(self, payload_callable):
        job_id = f"job-{len(self.submitted) + 1}"
        self.submitted.append(payload_callable)
        return job_id

    def cancel_job(self, job_id: str) -> None:
        self.cancelled.append(job_id)

    def set_status_callback(self, key: str, callback: callable) -> None:
        self.callbacks[key] = callback


def _setup_controller(
    monkeypatch, queue_enabled: bool
) -> tuple[PipelineController, FakeJobExecutionController]:
    fake_job_ctrl = FakeJobExecutionController()
    monkeypatch.setattr(
        "src.controller.pipeline_controller.is_queue_execution_enabled", lambda: queue_enabled
    )
    controller = PipelineController()
    controller._job_controller = fake_job_ctrl
    controller._job_controller.set_status_callback("pipeline_ctrl", controller._on_queue_status)
    controller._job_controller.set_status_callback("pipeline", controller._on_job_status)
    controller._queue_execution_enabled = queue_enabled
    controller._webui_connection.ensure_connected = (
        lambda autostart=True: WebUIConnectionState.READY
    )
    return controller, fake_job_ctrl


def test_queue_mode_disabled_still_uses_job_controller(monkeypatch):
    controller, fake = _setup_controller(monkeypatch, queue_enabled=False)
    started = controller.start_pipeline(lambda: {"ok": True})
    assert started is True
    assert fake.submitted, "JobExecutionController should be used even when queue mode is disabled"


def test_queue_mode_enabled_submits_and_handles_status(monkeypatch):
    controller, fake = _setup_controller(monkeypatch, queue_enabled=True)
    started = controller.start_pipeline(lambda: {"ok": False})
    assert started is True
    assert controller._active_job_id == "job-1"

    Job = SimpleNamespace(job_id="job-1")
    fake.callbacks["pipeline_ctrl"](Job, JobStatus.QUEUED)
    fake.callbacks["pipeline_ctrl"](Job, JobStatus.RUNNING)
    fake.callbacks["pipeline_ctrl"](Job, JobStatus.COMPLETED)
    assert controller._active_job_id is None


def test_stop_pipeline_delegates_to_job_controller(monkeypatch):
    controller, fake = _setup_controller(monkeypatch, queue_enabled=True)
    controller._active_job_id = "job-42"
    controller.stop_pipeline()
    assert fake.cancelled == ["job-42"]
