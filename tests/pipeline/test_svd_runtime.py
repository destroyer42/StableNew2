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
        postprocess = {"applied": ["face_restore", "upscale"]}

    class _FakeRunner:
        def __init__(self, *, output_root):
            self.output_root = output_root

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
    assert result["postprocess"]["applied"] == ["face_restore", "upscale"]
    assert result["frame_count"] == 25


def test_run_svd_native_stage_requires_input_image(tmp_path: Path) -> None:
    pipeline = Pipeline(Mock(), Mock())

    result = pipeline.run_svd_native_stage(
        input_image_path=None,
        stage_config={},
        output_dir=tmp_path,
        job_id="job-123",
    )

    assert result is None
