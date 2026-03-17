from types import SimpleNamespace

# Need WebUIConnectionState for stubbing the ensure_connected result
from src.controller.pipeline_controller import PipelineController
from src.controller.webui_connection_controller import WebUIConnectionState
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.pipeline_runner import PipelineRunResult
from src.queue.job_model import JobStatus


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

    def submit_job_with_run_mode(self, job) -> None:
        self.submitted.append(job)


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
    preview_record = NormalizedJobRecord(
        job_id="preview-job",
        config={"prompt": "castle"},
        path_output_dir="output",
        filename_template="{seed}",
        seed=123,
        prompt_pack_id="test-pack",
        prompt_pack_name="Test Pack",
        positive_prompt="castle",
        stage_chain=[StageConfig(stage_type="txt2img", enabled=True)],
    )
    controller.get_preview_jobs = lambda: [preview_record]  # type: ignore[method-assign]
    return controller, fake_job_ctrl


def test_queue_mode_disabled_still_uses_job_controller(monkeypatch):
    controller, fake = _setup_controller(monkeypatch, queue_enabled=False)
    started = controller.start_pipeline(lambda: {"ok": True})
    assert started is True
    assert controller._job_service.submitted, "JobService should receive canonical queue submissions"


def test_queue_mode_enabled_submits_and_handles_status(monkeypatch):
    controller, fake = _setup_controller(monkeypatch, queue_enabled=True)
    started = controller.start_pipeline(lambda: {"ok": False})
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


def test_job_execution_controller_replay_uses_pipeline_runner(monkeypatch):
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
    record = NormalizedJobRecord(
        job_id="queue-replay-njr",
        config={"prompt": "castle"},
        path_output_dir="output",
        filename_template="{seed}",
        seed=123,
    )

    result = controller.get_job_execution_controller().run_njr(record)

    assert runner.calls == [{"job_id": "queue-replay-njr", "checkpoint_callback": None}]
    assert result.success is True
    assert controller.get_last_run_result() is result


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
    record = NormalizedJobRecord(
        job_id="queue-replay-njr",
        config={"prompt": "castle"},
        path_output_dir="output",
        filename_template="{seed}",
        seed=123,
    )

    callback = lambda *_args, **_kwargs: None
    result = controller.run_njr(record, checkpoint_callback=callback)

    assert runner.calls == [callback]
    assert result.success is True
    assert controller.get_last_run_result() is result
