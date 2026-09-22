from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.runtime_state import CancellationError
from src.image_backends import (
    ImageBackendCapabilities,
    ImageBackendRegistry,
    ImageExecutionResult,
)
from src.pipeline.pipeline_runner import PipelineRunner
from src.utils.logger import StructuredLogger
from src.video.video_backend_registry import VideoBackendRegistry
from src.video.video_backend_types import VideoBackendCapabilities, VideoExecutionResult
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config


class _Recorder:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.events: list[tuple[str, str | None]] = []
        self.closed: str | None = None

    def start(self) -> None:
        self.events.append(("started", None))

    def enter_stage(self, stage: str, *, backend_id: str | None = None) -> None:
        self.events.append((f"enter:{stage}", backend_id))

    def leave_stage(self, stage: str) -> None:
        self.events.append((f"leave:{stage}", None))

    def update_execution_context(
        self,
        *,
        backend_id: str | None = None,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
    ) -> None:
        self.events.append((f"resolved:{backend_id}", workflow_id or workflow_version))

    def record_event(self, event: str, **_kwargs: Any) -> None:
        self.events.append((event, None))

    def close(self, *, outcome: str) -> None:
        self.closed = outcome


def test_pipeline_runner_uses_survivor_telemetry_as_an_observer(monkeypatch, tmp_path) -> None:
    class DummyPipeline:
        def __init__(self, api_client, structured_logger, status_callback=None):
            self.api_client = api_client
            self.logger = structured_logger
            self.status_callback = status_callback

        def run_txt2img_stage(self, _prompt, _negative, _payload, run_dir, **kwargs):
            return {"path": str(run_dir / kwargs["image_name"]), "images": []}

    recorders: list[_Recorder] = []

    def recorder_factory(**kwargs: Any) -> _Recorder:
        recorder = _Recorder(**kwargs)
        recorders.append(recorder)
        return recorder

    monkeypatch.setattr("src.pipeline.executor.Pipeline", DummyPipeline)
    runner = PipelineRunner(
        api_client=SimpleNamespace(),
        structured_logger=StructuredLogger(output_dir=str(tmp_path)),
        runs_base_dir=str(tmp_path / "runs"),
        survivor_telemetry_factory=recorder_factory,
    )
    def execute_image(**kwargs: Any) -> dict[str, Any]:
        kwargs["survivor_telemetry"].record_event("generation_dispatched")
        path = str(kwargs["run_dir"] / kwargs["image_name"])
        return {"path": path, "all_paths": [path]}

    monkeypatch.setattr(runner, "_execute_image_backend", execute_image)

    result = runner.run_njr(
        make_pipeline_njr(stage_chain=[make_stage_config()]),
        cancel_token=SimpleNamespace(is_cancelled=lambda: False),
    )

    assert result.success
    assert len(recorders) == 1
    recorder = recorders[0]
    assert recorder.kwargs["job_id"]
    assert recorder.kwargs["workflow"] == ["txt2img"]
    assert recorder.events == [
        ("started", None),
        ("enter:txt2img", "a1111_webui"),
        ("generation_dispatched", None),
        ("publication_boundary", None),
        ("leave:txt2img", None),
    ]
    assert recorder.closed == "runner_finished"


def test_pipeline_runner_records_truthful_cancelled_terminal_outcome(monkeypatch, tmp_path) -> None:
    class DummyPipeline:
        def __init__(self, api_client, structured_logger, status_callback=None):
            self.api_client = api_client
            self.logger = structured_logger
            self.status_callback = status_callback

    recorders: list[_Recorder] = []

    def recorder_factory(**kwargs: Any) -> _Recorder:
        recorder = _Recorder(**kwargs)
        recorders.append(recorder)
        return recorder

    monkeypatch.setattr("src.pipeline.executor.Pipeline", DummyPipeline)
    runner = PipelineRunner(
        api_client=SimpleNamespace(),
        structured_logger=StructuredLogger(output_dir=str(tmp_path)),
        runs_base_dir=str(tmp_path / "runs"),
        survivor_telemetry_factory=recorder_factory,
    )

    def cancel_image(**_kwargs: Any) -> None:
        raise CancellationError("operator cancelled")

    monkeypatch.setattr(runner, "_execute_image_backend", cancel_image)
    with pytest.raises(CancellationError):
        runner.run_njr(
            make_pipeline_njr(stage_chain=[make_stage_config()]),
            cancel_token=SimpleNamespace(is_cancelled=lambda: False),
        )

    assert recorders[0].closed == "cancelled"
    assert ("publication_boundary", None) not in recorders[0].events


def test_image_telemetry_dispatches_selected_a1111_backend(tmp_path) -> None:
    class FakeImageBackend:
        backend_id = "a1111_webui"
        capabilities = ImageBackendCapabilities(
            backend_id=backend_id,
            stage_types=("txt2img",),
        )

        def execute(self, _pipeline: Any, request: Any) -> ImageExecutionResult:
            output = request.output_dir / "image.png"
            return ImageExecutionResult.from_stage_result(
                backend_id=request.backend_id,
                stage_name=request.stage_name,
                result={"path": str(output), "all_paths": [str(output)]},
            )

    registry = ImageBackendRegistry()
    registry.register(FakeImageBackend())
    runner = PipelineRunner(
        SimpleNamespace(),
        StructuredLogger(output_dir=str(tmp_path)),
        image_backend_registry=registry,
        runs_base_dir=str(tmp_path / "runs"),
    )
    runner._pipeline = SimpleNamespace()
    recorder = _Recorder()
    runner._execute_image_backend(
        backend_id="a1111_webui",
        stage_name="txt2img",
        njr=make_pipeline_njr(stage_chain=[make_stage_config()]),
        stage_config={},
        run_dir=tmp_path,
        input_image_path=None,
        image_name="image",
        prompt="prompt",
        negative_prompt="",
        cancel_token=None,
        selected_model=None,
        selected_vae=None,
        survivor_telemetry=recorder,
    )

    assert ("generation_dispatched", None) in recorder.events


@pytest.mark.parametrize(
    ("stage_name", "backend_id", "extra", "expected_workflow"),
    [
        (
            "video_workflow",
            "comfy",
            {
                "video_execution": {
                    "backend_id": "comfy",
                    "task": "image_to_video",
                    "controls": ["source_image"],
                    "workflow_id": "wan22_ti2v_5b_i2v_v1",
                    "workflow_version": "1.0.0",
                }
            },
            ("wan22_ti2v_5b_i2v_v1", "1.0.0"),
        ),
        ("svd_native", "svd_native", {}, (None, None)),
    ],
)
def test_video_telemetry_uses_resolver_backend_and_workflow(
    stage_name: str,
    backend_id: str,
    extra: dict[str, Any],
    expected_workflow: tuple[str | None, str | None],
    tmp_path,
) -> None:
    class FakeVideoBackend:
        def __init__(self) -> None:
            self.backend_id = backend_id
            self.capabilities = VideoBackendCapabilities(
                backend_id=backend_id,
                stage_types=(stage_name,),
                controls=("source_image",),
                required_controls=("source_image",),
            )

        def execute(self, _pipeline: Any, request: Any) -> VideoExecutionResult:
            output = tmp_path / f"{stage_name}.mp4"
            return VideoExecutionResult.from_stage_result(
                backend_id=request.backend_id,
                stage_name=request.stage_name,
                result={"path": str(output), "output_paths": [str(output)]},
            )

    registry = VideoBackendRegistry()
    registry.register(FakeVideoBackend())
    runner = PipelineRunner(
        SimpleNamespace(),
        StructuredLogger(output_dir=str(tmp_path)),
        video_backend_registry=registry,
        runs_base_dir=str(tmp_path / "runs"),
    )
    record = make_pipeline_njr(
        job_id=f"video-{stage_name}",
        stage_chain=[make_stage_config(stage_name, extra=extra)],
        input_image_paths=[str(tmp_path / "seed.png")],
    )
    recorder = _Recorder()
    recorder.enter_stage(stage_name, backend_id="a1111_webui")
    runner._execute_video_stage(
        stage_name=stage_name,
        njr=record,
        current_stage_paths=[str(tmp_path / "seed.png")],
        prompt="prompt",
        negative_prompt="",
        run_dir=tmp_path,
        cancel_token=None,
        variants=[],
        metadata={},
        survivor_telemetry=recorder,
    )

    assert (f"resolved:{backend_id}", expected_workflow[0] or expected_workflow[1]) in recorder.events
    assert ("generation_dispatched", None) in recorder.events
