from types import SimpleNamespace

# Need WebUIConnectionState for stubbing the ensure_connected result
from src.controller.pipeline_controller import PipelineController
from src.controller.webui_connection_controller import WebUIConnectionState
from src.pipeline.pipeline_runner import PipelineRunResult
from src.queue.job_model import JobStatus
from tests.helpers.njr_factory import make_pipeline_njr, make_queue_job


class FakeJobExecutionController:
    def __init__(self) -> None:
        self.cancelled = []
        self.callbacks: dict[str, callable] = {}

    def cancel_job(self, job_id: str) -> None:
        self.cancelled.append(job_id)

    def set_status_callback(self, key: str, callback: callable) -> None:
        self.callbacks[key] = callback


class FakeJobService:
    def __init__(self) -> None:
        self.submitted = []

    def submit_njrs(self, records, policy=None) -> list[str]:
        self.submitted.extend(records)
        return [record.job_id for record in records]


def _setup_controller(
    monkeypatch, queue_enabled: bool
) -> tuple[PipelineController, FakeJobExecutionController]:
    fake_job_ctrl = FakeJobExecutionController()
    fake_job_service = FakeJobService()
    monkeypatch.setattr(
        "src.controller.pipeline_controller.is_queue_execution_enabled", lambda: queue_enabled
    )
    controller = PipelineController()
    controller._job_controller = fake_job_ctrl
    controller._job_service = fake_job_service
    controller._job_controller.set_status_callback("pipeline_ctrl", controller._on_queue_status)
    controller._job_controller.set_status_callback("pipeline", controller._on_job_status)
    controller._queue_execution_enabled = queue_enabled
    controller._webui_connection.ensure_connected = (
        lambda autostart=True: WebUIConnectionState.READY
    )
    preview_record = make_pipeline_njr(
        job_id="preview-job",
        config={"prompt": "castle"},
        seed=123,
        prompt_pack_id="test-pack",
        prompt_pack_name="Test Pack",
        positive_prompt="castle",
    )
    controller.get_preview_jobs = lambda: [preview_record]  # type: ignore[method-assign]
    return controller, fake_job_ctrl


def test_queue_mode_disabled_flag_still_submits_through_job_service(monkeypatch):
    controller, fake = _setup_controller(monkeypatch, queue_enabled=False)
    started = controller.start_pipeline()
    assert started is True
    assert controller._job_service.submitted, (
        "JobService should receive canonical queue submissions"
    )


def test_queue_mode_enabled_submits_and_handles_status(monkeypatch):
    controller, fake = _setup_controller(monkeypatch, queue_enabled=True)
    started = controller.start_pipeline()
    assert started is True
    assert len(controller._job_service.submitted) == 1
    controller._active_job_id = "job-1"

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


def test_queued_job_executes_njr_through_pipeline_runner_run_njr(monkeypatch):
    monkeypatch.setattr(
        "src.controller.pipeline_controller.is_queue_execution_enabled", lambda: True
    )

    class FakeRunner:
        def __init__(self) -> None:
            self.calls = []

        def run_njr(
            self,
            record,
            cancel_token=None,
            run_plan=None,
            log_fn=None,
            checkpoint_callback=None,
        ):
            self.calls.append(
                {
                    "job_id": record.job_id,
                    "checkpoint_callback": checkpoint_callback,
                }
            )
            return PipelineRunResult(
                run_id=record.job_id,
                success=True,
                error=None,
                variants=[{"path": "output/test.png"}],
                learning_records=[],
            )

    runner = FakeRunner()
    controller = PipelineController(pipeline_runner=runner)
    job = make_queue_job(
        "queue-replay-njr", config={"prompt": "castle"}, positive_prompt="castle", seed=123
    )

    # Queue worker callback: Job(NJR) -> ReplayEngine -> PipelineRunner.run_njr
    result = controller.get_job_execution_controller()._run_job_callback(job)

    assert [call["job_id"] for call in runner.calls] == ["queue-replay-njr"]
    assert callable(runner.calls[0]["checkpoint_callback"])
    assert result["success"] is True
    assert controller.get_last_run_result().run_id == "queue-replay-njr"


def test_pipeline_controller_run_njr_passes_checkpoint_callback(monkeypatch):
    monkeypatch.setattr(
        "src.controller.pipeline_controller.is_queue_execution_enabled", lambda: True
    )

    class FakeRunner:
        def __init__(self) -> None:
            self.calls = []

        def run_njr(
            self,
            record,
            cancel_token=None,
            run_plan=None,
            log_fn=None,
            checkpoint_callback=None,
        ):
            self.calls.append(checkpoint_callback)
            return PipelineRunResult(
                run_id=record.job_id,
                success=True,
                error=None,
                variants=[{"path": "output/test.png"}],
                learning_records=[],
            )

    runner = FakeRunner()
    controller = PipelineController(pipeline_runner=runner)
    record = make_pipeline_njr(
        job_id="queue-replay-njr",
        config={"prompt": "castle"},
        positive_prompt="castle",
        seed=123,
    )

    def callback(*_args, **_kwargs) -> None:
        return None

    result = controller.run_njr(record, checkpoint_callback=callback)

    assert runner.calls == [callback]
    assert result.success is True
    assert controller.get_last_run_result() is result
