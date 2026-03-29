from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.controller.svd_controller import SVDController
from src.pipeline.job_requests_v2 import PipelineRunRequest
from src.pipeline.pipeline_runner import PipelineRunner
from src.state.output_routing import OUTPUT_ROUTE_TESTING


class _RecordingJobService:
    def __init__(self) -> None:
        self.njrs = []
        self.request: PipelineRunRequest | None = None

    def enqueue_njrs(self, njrs, request: PipelineRunRequest):
        self.njrs = list(njrs)
        self.request = request
        return ["job-svd-integration"]


def test_svd_submission_round_trips_from_controller_into_pipeline_runner(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    video_path = tmp_path / "svd.mp4"
    preview_path = tmp_path / "preview.png"
    manifest_path = tmp_path / "svd.json"
    video_path.write_bytes(b"mp4")
    preview_path.write_bytes(b"png")
    manifest_path.write_text(
        json.dumps(
            {
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
                "source_image_path": str(source_path),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    job_service = _RecordingJobService()
    app_controller = SimpleNamespace(output_dir=str(output_dir), job_service=job_service)
    controller = SVDController(app_controller=app_controller, svd_service=Mock())

    config = controller.build_default_config()
    job_id = controller.submit_svd_job(
        source_image_path=source_path,
        config=config,
        output_route=OUTPUT_ROUTE_TESTING,
    )

    assert job_id == "job-svd-integration"
    assert job_service.request is not None

    njr = job_service.njrs[0]
    assert njr.start_stage == "svd_native"
    assert njr.input_image_paths == [str(source_path)]
    assert njr.config["pipeline"]["output_route"] == OUTPUT_ROUTE_TESTING
    assert njr.stage_chain[0].stage_type == "svd_native"
    assert njr.stage_chain[0].sampler_name == "native"
    assert njr.stage_chain[0].extra["inference"]["model_id"] == config.inference.model_id
    assert njr.stage_chain[0].extra["inference"]["motion_bucket_id"] == config.inference.motion_bucket_id
    assert job_service.request.prompt_pack_id == "svd_native"
    assert job_service.request.requested_job_label == "SVD Img2Vid"
    assert job_service.request.explicit_output_dir == str(output_dir)

    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    pipeline = Mock()
    pipeline.run_svd_native_stage.return_value = {
        "path": str(video_path),
        "video_path": str(video_path),
        "output_paths": [str(video_path)],
        "frame_paths": [],
        "manifest_path": str(manifest_path),
        "thumbnail_path": str(preview_path),
        "source_image_path": str(source_path),
        "frame_count": config.inference.num_frames,
        "fps": config.inference.fps,
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

    pipeline.run_svd_native_stage.assert_called_once()
    assert result.success is True
    assert manifest_path.exists()
    assert result.metadata["svd_native_artifact"]["count"] == 1
    assert result.metadata["svd_native_artifact"]["primary_path"] == str(video_path)
    assert result.metadata["video_artifacts"]["svd_native"]["backend_id"] == "svd_native"
    assert result.metadata["video_primary_artifact"]["stage"] == "svd_native"
    assert result.variants[0]["video_backend_id"] == "svd_native"
    assert njr.output_paths == [str(video_path)]
    assert njr.thumbnail_path == str(preview_path)