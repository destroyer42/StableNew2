from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from src.pipeline.executor import Pipeline


def test_run_svd_native_stage_returns_artifact_metadata(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "source.png"
    input_path.write_bytes(b"seed")
    output_path = tmp_path / "clip.mp4"
    manifest_path = tmp_path / "manifests" / "clip.json"
    preview_path = tmp_path / "preview.png"

    class _FakePreprocess:
        source_path = input_path
        prepared_path = tmp_path / "_svd_temp" / "prepared.png"
        original_width = 768
        original_height = 1280
        target_width = 1024
        target_height = 576
        resize_mode = "letterbox"
        was_resized = True
        was_padded = True
        was_cropped = False

    class _FakeResult:
        source_image_path = input_path
        video_path = output_path
        gif_path = None
        frame_paths = []
        thumbnail_path = preview_path
        metadata_path = manifest_path
        frame_count = 25
        fps = 7
        seed = 123
        model_id = "stabilityai/stable-video-diffusion-img2vid-xt"
        preprocess = _FakePreprocess()
        postprocess = {
            "applied": ["secondary_motion", "face_restore", "upscale"],
            "secondary_motion": {
                "summary": {"status": "applied", "policy_id": "svd_secondary_motion_v1"}
            },
        }

    class _FakeRunner:
        def __init__(self, *, output_root, status_callback=None):
            self.output_root = output_root
            self.status_callback = status_callback

        def run(self, *, source_image_path, config, job_id):
            assert Path(source_image_path) == input_path
            assert job_id == "job-123"
            assert Path(self.output_root) == tmp_path
            assert config.inference.model_id == "stabilityai/stable-video-diffusion-img2vid-xt"
            return _FakeResult()

    monkeypatch.setattr("src.video.svd_runner.SVDRunner", _FakeRunner)

    pipeline = Pipeline(Mock(), Mock())

    result = pipeline.run_svd_native_stage(
        input_image_path=input_path,
        stage_config={},
        output_dir=tmp_path,
        job_id="job-123",
    )

    assert result is not None
    assert result["video_path"] == str(output_path)
    assert result["manifest_path"] == str(manifest_path)
    assert result["thumbnail_path"] == str(preview_path)
    assert result["preprocess"]["target_width"] == 1024
    assert result["postprocess"]["applied"] == ["secondary_motion", "face_restore", "upscale"]
    assert result["frame_count"] == 25
    assert result["artifact"]["primary_path"] == str(output_path)
    assert result["artifact"]["manifest_path"] == str(manifest_path)
    assert result["secondary_motion"]["summary"]["status"] == "applied"
    assert result["secondary_motion_summary"]["status"] == "applied"


def test_run_svd_native_stage_requires_input_image(tmp_path: Path) -> None:
    pipeline = Pipeline(Mock(), Mock())

    result = pipeline.run_svd_native_stage(
        input_image_path=None,
        stage_config={},
        output_dir=tmp_path,
        job_id="job-123",
    )

    assert result is None


def test_run_svd_native_stage_emits_runtime_stage_detail_updates(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "source.png"
    input_path.write_bytes(b"seed")

    class _FakePreprocess:
        source_path = input_path
        prepared_path = tmp_path / "_svd_temp" / "prepared.png"
        original_width = 768
        original_height = 1280
        target_width = 1024
        target_height = 576
        resize_mode = "letterbox"
        was_resized = True
        was_padded = True
        was_cropped = False

    class _FakeResult:
        source_image_path = input_path
        video_path = None
        gif_path = None
        frame_paths = [tmp_path / "frame_001.png"]
        thumbnail_path = None
        metadata_path = tmp_path / "manifest.json"
        frame_count = 25
        fps = 7
        seed = 123
        model_id = "stabilityai/stable-video-diffusion-img2vid-xt"
        preprocess = _FakePreprocess()
        postprocess = {"applied": ["interpolation"]}

    class _FakeRunner:
        def __init__(self, *, output_root, status_callback=None):
            self.output_root = output_root
            self.status_callback = status_callback

        def run(self, *, source_image_path, config, job_id):
            assert Path(source_image_path) == input_path
            assert Path(self.output_root) == tmp_path
            assert job_id == "job-123"
            assert self.status_callback is not None
            self.status_callback(
                {
                    "stage_detail": "postprocess: interpolation",
                    "progress": 0.75,
                    "current_step": 1,
                    "total_steps": 1,
                }
            )
            return _FakeResult()

    monkeypatch.setattr("src.video.svd_runner.SVDRunner", _FakeRunner)

    updates: list[dict[str, object]] = []
    pipeline = Pipeline(Mock(), Mock(), status_callback=updates.append)
    pipeline._current_job_id = "job-123"
    pipeline._current_stage_chain = ["svd_native"]
    pipeline._current_stage_index = 0

    result = pipeline.run_svd_native_stage(
        input_image_path=input_path,
        stage_config={},
        output_dir=tmp_path,
        job_id="job-123",
    )

    assert result is not None
    matching_update = next(update for update in updates if update.get("stage_detail") == "postprocess: interpolation")
    assert matching_update["current_stage"] == "svd_native"
    assert matching_update["progress"] == 0.75
