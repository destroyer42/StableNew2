from __future__ import annotations

import logging
from pathlib import Path

import pytest
from PIL import Image

from src.video.svd_config import SVDConfig
from src.video.svd_models import SVDPreprocessResult, SVDResult
from src.video.svd_runner import SVDRunner


def test_svd_runner_logs_run_summary(tmp_path: Path, monkeypatch, caplog) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")
    prepared_path = tmp_path / "_svd_temp" / "job-1" / "prepared.png"
    output_video = tmp_path / "svd_source.mp4"
    preview_path = tmp_path / "svd_source_preview.png"
    manifest_path = tmp_path / "svd_source.json"

    preprocess = SVDPreprocessResult(
        source_path=source_path,
        prepared_path=prepared_path,
        original_width=640,
        original_height=360,
        target_width=1024,
        target_height=576,
        resize_mode="letterbox",
        was_resized=True,
        was_padded=True,
        was_cropped=False,
    )

    monkeypatch.setattr("src.video.svd_runner.prepare_svd_input", lambda **_kwargs: preprocess)
    monkeypatch.setattr(
        "src.video.svd_runner.SVDPostprocessRunner.process_frames",
        lambda self, **kwargs: (kwargs["frames"], {"applied": ["interpolation"]}),
    )
    monkeypatch.setattr(
        "src.video.svd_runner.export_video_mp4",
        lambda **_kwargs: output_video,
    )
    monkeypatch.setattr(
        "src.video.svd_runner.write_svd_run_manifest",
        lambda **_kwargs: manifest_path,
    )

    class _FakeService:
        def generate_frames(self, **_kwargs):
            return [Image.new("RGB", (32, 32), "white")]

        def _release_runtime_memory(self) -> None:
            return None

    caplog.set_level(logging.INFO)
    runner = SVDRunner(service=_FakeService(), output_root=tmp_path)

    result = runner.run(source_image_path=source_path, config=SVDConfig(), job_id="job-1")

    assert isinstance(result, SVDResult)
    assert "[SVD] start job=job-1" in caplog.text
    assert "[SVD] preprocess prepared=prepared.png" in caplog.text
    assert "[SVD] inference completed frame_count=1" in caplog.text
    assert "[SVD] postprocess completed frame_count=1 applied=['interpolation']" in caplog.text
    assert "[SVD] complete video=svd_source.mp4" in caplog.text


def test_svd_runner_emits_live_stage_status_details(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")
    prepared_path = tmp_path / "_svd_temp" / "job-1" / "prepared.png"

    preprocess = SVDPreprocessResult(
        source_path=source_path,
        prepared_path=prepared_path,
        original_width=640,
        original_height=360,
        target_width=1024,
        target_height=576,
        resize_mode="letterbox",
        was_resized=True,
        was_padded=True,
        was_cropped=False,
    )

    monkeypatch.setattr("src.video.svd_runner.prepare_svd_input", lambda **_kwargs: preprocess)
    monkeypatch.setattr(
        "src.video.svd_runner.export_video_mp4",
        lambda **_kwargs: tmp_path / "svd_source.mp4",
    )
    monkeypatch.setattr(
        "src.video.svd_runner.write_svd_run_manifest",
        lambda **_kwargs: tmp_path / "svd_source.json",
    )

    def _fake_process_frames(self, **kwargs):
        callback = getattr(self, "_status_callback", None)
        if callback is not None:
            callback(
                {
                    "stage_detail": "postprocess: interpolation",
                    "progress": 0.5,
                    "current_step": 1,
                    "total_steps": 1,
                }
            )
        return kwargs["frames"], {"applied": ["interpolation"]}

    monkeypatch.setattr("src.video.svd_runner.SVDPostprocessRunner.process_frames", _fake_process_frames)

    class _FakeService:
        def generate_frames(self, **_kwargs):
            return [Image.new("RGB", (32, 32), "white")]

        def _release_runtime_memory(self) -> None:
            return None

    updates: list[dict[str, object]] = []
    runner = SVDRunner(service=_FakeService(), output_root=tmp_path, status_callback=updates.append)

    runner.run(
        source_image_path=source_path,
        config=SVDConfig.from_dict({"postprocess": {"interpolation": {"enabled": True, "executable_path": "C:/tmp/rife.exe"}}}),
        job_id="job-1",
    )

    details = [str(update.get("stage_detail")) for update in updates]
    assert details[:3] == ["preprocess", "inference", "postprocess"]
    assert "postprocess: interpolation" in details
    assert details[-2:] == ["export", "complete"]
    postprocess_update = next(update for update in updates if update.get("stage_detail") == "postprocess: interpolation")
    assert postprocess_update["progress"] == pytest.approx(0.725)
