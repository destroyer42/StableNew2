from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.controller.app_controller import AppController
from src.controller.svd_controller import SVDController
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.job_requests_v2 import PipelineRunRequest
from src.pipeline.pipeline_runner import PipelineRunner
from src.state.output_routing import OUTPUT_ROUTE_TESTING
from src.utils import StructuredLogger
from src.video.video_backend_registry import VideoBackendRegistry
from src.video.video_backend_types import (
    VideoBackendCapabilities,
    VideoExecutionRequest,
    VideoExecutionResult,
)


_TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aRX0AAAAASUVORK5CYII="
)


class _RecordingJobService:
    def __init__(self) -> None:
        self.njrs: list[NormalizedJobRecord] = []
        self.request: PipelineRunRequest | None = None

    def enqueue_njrs(self, njrs, request: PipelineRunRequest):
        self.njrs = list(njrs)
        self.request = request
        return ["job-video-golden-path"]


@pytest.mark.integration
@pytest.mark.golden_path
@pytest.mark.gp6
def test_gp6_svd_native_path_creates_video_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.pipeline.pipeline_runner.write_run_metadata", lambda **_kwargs: None)

    source_path = tmp_path / "seed.png"
    source_path.write_bytes(base64.b64decode(_TINY_PNG_BASE64))

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    video_path = tmp_path / "svd.mp4"
    preview_path = tmp_path / "preview.png"
    manifest_path = tmp_path / "svd.json"
    video_path.write_bytes(b"mp4")
    preview_path.write_bytes(base64.b64decode(_TINY_PNG_BASE64))
    manifest_path.write_text("{}", encoding="utf-8")

    job_service = _RecordingJobService()
    app_controller = AppController.__new__(AppController)
    app_controller.output_dir = str(output_dir)
    app_controller.job_service = job_service
    app_controller._append_log = lambda *_args, **_kwargs: None

    svd_service = Mock()
    svd_service.is_available.return_value = (True, None)
    app_controller._svd_controller = SVDController(app_controller=app_controller, svd_service=svd_service)

    job_id = app_controller.submit_svd_job(
        source_image_path=source_path,
        form_data={
            "preprocess": {
                "target_width": 1024,
                "target_height": 576,
                "resize_mode": "center_crop",
            },
            "inference": {
                "model_id": "stabilityai/stable-video-diffusion-img2vid-xt",
                "num_frames": 25,
                "fps": 7,
                "motion_bucket_id": 48,
                "noise_aug_strength": 0.01,
                "num_inference_steps": 36,
                "decode_chunk_size": 4,
                "local_files_only": True,
            },
            "pipeline": {"output_route": OUTPUT_ROUTE_TESTING},
            "output": {
                "output_format": "mp4",
                "save_frames": False,
                "save_preview_image": True,
            },
            "postprocess": {
                "face_restore": {"enabled": False, "method": "CodeFormer", "fidelity_weight": 0.7},
                "interpolation": {"enabled": False, "multiplier": 2},
                "upscale": {"enabled": False, "scale": 2.0},
            },
        },
    )

    assert job_id == "job-video-golden-path"
    assert job_service.request is not None
    assert job_service.request.prompt_pack_id == "svd_native"

    njr = job_service.njrs[0]
    runner = PipelineRunner(
        Mock(),
        StructuredLogger(output_dir=tmp_path / "logs"),
        runs_base_dir=str(tmp_path / "runs"),
    )
    pipeline = Mock()
    pipeline.run_svd_native_stage.return_value = {
        "path": str(video_path),
        "video_path": str(video_path),
        "output_paths": [str(video_path)],
        "frame_paths": [],
        "manifest_path": str(manifest_path),
        "thumbnail_path": str(preview_path),
        "source_image_path": str(source_path),
        "frame_count": 25,
        "fps": 7,
        "artifact": {
            "schema": "stablenew.artifact.v2.6",
            "stage": "svd_native",
            "artifact_type": "video",
            "primary_path": str(video_path),
            "output_paths": [str(video_path)],
            "manifest_path": str(manifest_path),
            "thumbnail_path": str(preview_path),
            "input_image_path": str(source_path),
        },
    }
    runner._pipeline = pipeline

    result = runner.run_njr(njr, cancel_token=None)

    assert result.success is True
    assert result.metadata["svd_native_artifact"]["count"] == 1
    assert result.metadata["svd_native_artifact"]["primary_path"] == str(video_path)
    assert Path(result.metadata["svd_native_artifact"]["video_paths"][0]).exists()
    assert result.metadata["video_artifacts"]["svd_native"]["backend_id"] == "svd_native"
    assert result.metadata["video_primary_artifact"]["stage"] == "svd_native"
    assert result.variants[0]["video_backend_id"] == "svd_native"


@pytest.mark.integration
@pytest.mark.golden_path
@pytest.mark.gp6
def test_gp6_video_workflow_path_creates_video_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.pipeline.pipeline_runner.write_run_metadata", lambda **_kwargs: None)

    start_path = tmp_path / "start.png"
    end_path = tmp_path / "end.png"
    preview_frame = tmp_path / "preview.png"
    output_video = tmp_path / "workflow.mp4"
    manifest_path = tmp_path / "workflow.json"
    start_path.write_bytes(base64.b64decode(_TINY_PNG_BASE64))
    end_path.write_bytes(base64.b64decode(_TINY_PNG_BASE64))
    preview_frame.write_bytes(base64.b64decode(_TINY_PNG_BASE64))
    output_video.write_bytes(b"mp4")
    manifest_path.write_text("{}", encoding="utf-8")

    class _WorkflowBackend:
        backend_id = "dummy_workflow"
        capabilities = VideoBackendCapabilities(
            backend_id="dummy_workflow",
            stage_types=("video_workflow",),
            requires_input_image=True,
            supports_prompt_text=True,
            supports_negative_prompt=True,
            supports_multiple_anchors=True,
        )

        def execute(self, pipeline, request: VideoExecutionRequest):
            assert request.workflow_id == "ltx_multiframe_anchor_v1"
            assert request.end_anchor_path == end_path
            return VideoExecutionResult.from_stage_result(
                backend_id="dummy_workflow",
                stage_name="video_workflow",
                result={
                    "path": str(output_video),
                    "video_path": str(output_video),
                    "output_paths": [str(output_video)],
                    "manifest_path": str(manifest_path),
                    "thumbnail_path": str(preview_frame),
                    "frame_paths": [str(preview_frame)],
                    "source_image_path": str(start_path),
                    "workflow_id": request.workflow_id,
                    "artifact": {
                        "schema": "stablenew.artifact.v2.6",
                        "stage": "video_workflow",
                        "artifact_type": "video",
                        "primary_path": str(output_video),
                        "output_paths": [str(output_video)],
                        "manifest_path": str(manifest_path),
                        "input_image_path": str(start_path),
                    },
                },
                backend_metadata={"workflow_id": request.workflow_id},
                replay_manifest_fragment={"workflow_id": request.workflow_id},
            )

    registry = VideoBackendRegistry()
    registry.register(_WorkflowBackend())

    runner = PipelineRunner(
        Mock(),
        StructuredLogger(output_dir=tmp_path / "logs"),
        runs_base_dir=str(tmp_path / "runs"),
        video_backend_registry=registry,
    )
    runner._pipeline = Mock()

    record = NormalizedJobRecord(
        job_id="gp6-video-workflow-001",
        config={},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        positive_prompt="cinematic tracking shot through a canyon",
        negative_prompt="blurry",
        stage_chain=[
            StageConfig(
                stage_type="video_workflow",
                enabled=True,
                extra={
                    "workflow_id": "ltx_multiframe_anchor_v1",
                    "workflow_version": "1.0.0",
                    "backend_id": "dummy_workflow",
                    "end_anchor_path": str(end_path),
                },
            )
        ],
        input_image_paths=[str(start_path)],
        start_stage="video_workflow",
    )

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is True
    assert result.metadata["video_artifacts"]["video_workflow"]["backend_id"] == "dummy_workflow"
    assert result.metadata["video_primary_artifact"]["stage"] == "video_workflow"
    assert result.metadata["video_workflow_artifact"]["primary_path"] == str(output_video)
    assert result.metadata["video_workflow_artifact"]["frame_paths"] == [str(preview_frame)]
    assert result.metadata["replay_descriptor"]["backends"][0]["workflow_id"] == "ltx_multiframe_anchor_v1"
    assert result.variants[0]["video_backend_id"] == "dummy_workflow"
    assert Path(result.metadata["video_workflow_artifact"]["primary_path"]).exists()