"""PR-VID-120: explicit neutral video intent through the ordinary queue path, fake backends only.

Intent/config -> immutable NJR -> JobService -> SQLite queue -> PipelineRunner.run_njr ->
selected fake video backend -> artifact/history, plus replay lineage.  No GPU, no model.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.gui.app_state_v2 import AppStateV2
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.reprocess_builder import ReprocessJobBuilder
from src.pipeline.result_contract_v26 import collect_canonical_artifacts
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.config import ConfigManager
from src.utils.logger import StructuredLogger
from src.video.video_backend_registry import VideoBackendRegistry
from src.video.video_backend_types import (
    CONTROL_PROMPT_TEXT,
    CONTROL_SOURCE_IMAGE,
    VIDEO_TASK_IMAGE_TO_VIDEO,
    VideoBackendCapabilities,
    VideoExecutionResult,
)


class _FakeVideoBackend:
    def __init__(self, backend_id: str, controls: tuple[str, ...], output_dir: Path) -> None:
        self.backend_id = backend_id
        self.capabilities = VideoBackendCapabilities(
            backend_id=backend_id,
            tasks=(VIDEO_TASK_IMAGE_TO_VIDEO,),
            controls=controls,
            required_controls=(CONTROL_SOURCE_IMAGE,),
        )
        self.requests: list = []
        self._output_dir = output_dir

    def execute(self, pipeline, request):
        self.requests.append(request)
        video = self._output_dir / f"{self.backend_id}-{len(self.requests)}.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"fake-mp4")
        return VideoExecutionResult.from_stage_result(
            backend_id=self.backend_id,
            stage_name=request.stage_name,
            result={
                "path": str(video),
                "video_path": str(video),
                "output_paths": [str(video)],
                "source_image_path": str(request.input_image_path),
            },
            backend_metadata={"task": request.task, "controls": list(request.requested_controls)},
        )


def _build_stack(tmp_path: Path, backends):
    registry = VideoBackendRegistry()
    for backend in backends:
        registry.register(backend)
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    ref: dict[str, PipelineController] = {}
    service = JobService(
        queue, run_callable=lambda job: ref["c"]._run_job(job), require_normalized_records=True
    )
    service.auto_run_enabled = False
    runner = PipelineRunner(
        SimpleNamespace(),
        StructuredLogger(output_dir=tmp_path / "logs"),
        runs_base_dir=str(tmp_path / "output"),
        video_backend_registry=registry,
    )
    controller = PipelineController(
        app_state=AppStateV2(),
        config_manager=ConfigManager(presets_dir=tmp_path / "presets"),
        job_service=service,
        pipeline_runner=runner,
    )
    ref["c"] = controller
    service.auto_run_enabled = False  # the controller re-enables it; runs are driven explicitly
    service.runner.stop()
    return repository, queue, service, controller


def _submit(service, tmp_path: Path, execution: dict) -> str:
    source = tmp_path / "source.png"
    Image.new("RGB", (16, 16), "navy").save(source)
    config = {
        "video_workflow": {
            "enabled": True,
            "prompt": "a person waves",
            "video_execution": execution,
        },
        "pipeline": {"video_workflow_enabled": True},
    }
    njr = ReprocessJobBuilder().build_reprocess_job(
        input_image_paths=[str(source)],
        stages=["video_workflow"],
        config=config,
        output_dir=str(tmp_path / "output"),
        prompt="a person waves",
        negative_prompt="",
        pack_name="Neutral Video",
        source="video_workflow",
    )
    return service.submit_njrs([njr], SubmissionPolicy())[0]


def test_explicit_neutral_video_intent_survives_queue_runner_artifact_and_replay(
    tmp_path: Path,
) -> None:
    chosen = _FakeVideoBackend(
        "fake_prompt", (CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT), tmp_path / "out"
    )
    other = _FakeVideoBackend("fake_other", (CONTROL_SOURCE_IMAGE,), tmp_path / "out")
    repository, queue, service, controller = _build_stack(tmp_path, [other, chosen])
    execution = {
        "backend_id": "fake_prompt",
        "task": VIDEO_TASK_IMAGE_TO_VIDEO,
        "controls": [CONTROL_PROMPT_TEXT],
    }
    job_id = _submit(service, tmp_path, execution)

    queued = queue.get_job(job_id)
    record = queued._normalized_record
    stage_extra = record.stage_chain[0].to_dict()
    assert stage_extra["extra"]["video_execution"] == execution  # intent lives in the stage config
    reloaded = repository.get_job_model(job_id)  # SQLite reload keeps the explicit intent
    assert reloaded is not None and reloaded.status is JobStatus.QUEUED
    assert reloaded._normalized_record.stage_chain[0].to_dict() == stage_extra

    service.runner.run_once(queued)
    done = repository.get_job(job_id)
    assert done is not None and done.status is JobStatus.COMPLETED
    assert other.requests == [] and len(chosen.requests) == 1  # explicit id, not order/task
    request = chosen.requests[0]
    assert request.task == VIDEO_TASK_IMAGE_TO_VIDEO
    assert set(request.requested_controls) == {CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT}
    assert request.context_metadata["video_contract"]["legacy_stage_routing"] is False
    [artifact] = collect_canonical_artifacts(done.result)
    assert artifact["stage"] == "video_workflow" and Path(artifact["primary_path"]).is_file()
    assert queue.get_job(job_id)._normalized_record is record  # NJR object never mutated

    assert controller.replay_job_from_history(job_id) == 1
    [replay] = queue.list_jobs(JobStatus.QUEUED)
    replay_record = replay._normalized_record
    assert replay_record.job_id != job_id and replay_record.source.parent_job_id == job_id
    assert replay_record.stage_chain[0].to_dict() == stage_extra  # same explicit intent
    service.runner.run_once(replay)
    assert repository.get_job(replay_record.job_id).status is JobStatus.COMPLETED
    assert len(chosen.requests) == 2 and other.requests == []
    service.runner.stop()
    repository.close()


def test_unsupported_control_fails_the_job_before_the_backend_is_called(tmp_path: Path) -> None:
    narrow = _FakeVideoBackend("fake_narrow", (CONTROL_SOURCE_IMAGE,), tmp_path / "out")
    repository, queue, service, _controller = _build_stack(tmp_path, [narrow])
    job_id = _submit(
        service,
        tmp_path,
        {
            "backend_id": "fake_narrow",
            "task": VIDEO_TASK_IMAGE_TO_VIDEO,
            "controls": [CONTROL_PROMPT_TEXT],
        },
    )
    service.runner.run_once(queue.get_job(job_id))
    failed = repository.get_job(job_id)
    assert failed is not None and failed.status is JobStatus.FAILED
    assert narrow.requests == []  # never dispatched, control never silently dropped
    assert "prompt_text" in str(failed.error_message or failed.result)
    service.runner.stop()
    repository.close()
