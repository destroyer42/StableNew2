from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.controller.runtime_state import CancellationError, CancelToken
from src.video.svd_config import SVDConfig, SVDInferenceConfig
from src.video.svd_errors import SVDExportError, SVDOutOfMemoryError
from src.video.svd_models import SVDPreprocessResult
from src.video.svd_registry import build_svd_artifact_stem
from src.video.svd_runner import SVDRunner
from src.video.svd_service import SVDService


def _prepared_image(tmp_path: Path) -> Path:
    path = tmp_path / "prepared.png"
    Image.new("RGB", (32, 32), "white").save(path)
    return path


def _service_with_pipeline(monkeypatch, pipeline):
    service = SVDService()
    monkeypatch.setattr(service, "is_available", lambda: (True, None))
    monkeypatch.setattr(service, "_get_pipeline", lambda _config: pipeline)
    monkeypatch.setattr(service, "_release_runtime_memory", lambda: None)
    monkeypatch.setattr(
        "src.video.svd_service.importlib.import_module",
        lambda name: SimpleNamespace() if name == "torch" else None,
    )
    return service


def test_callback_capable_pipeline_reports_real_denoising_steps(monkeypatch, tmp_path: Path) -> None:
    class FakePipeline:
        def __init__(self) -> None:
            self.callback = None

        def __call__(self, _image, *, callback_on_step_end=None, **_kwargs):
            self.callback = callback_on_step_end
            for step in range(25):
                callback_on_step_end(self, step, None, {"latents": object()})
            return SimpleNamespace(frames=[Image.new("RGB", (8, 8), "navy")])

    pipeline = FakePipeline()
    service = _service_with_pipeline(monkeypatch, pipeline)
    updates: list[dict[str, object]] = []

    frames = service.generate_frames(
        prepared_image_path=_prepared_image(tmp_path),
        config=SVDInferenceConfig(num_frames=14, num_inference_steps=25),
        status_callback=updates.append,
    )

    inference = [update for update in updates if update.get("stage_detail") == "inference"]
    assert pipeline.callback is not None
    assert [update["current_step"] for update in inference] == list(range(1, 26))
    assert {update["total_steps"] for update in inference} == {25}
    assert len(frames) == 1
    for frame in frames:
        frame.close()


def test_callback_unavailable_pipeline_does_not_fabricate_denoising_progress(monkeypatch, tmp_path: Path) -> None:
    class FakePipeline:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        def __call__(self, _image, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(frames=[Image.new("RGB", (8, 8), "teal")])

    pipeline = FakePipeline()
    service = _service_with_pipeline(monkeypatch, pipeline)
    updates: list[dict[str, object]] = []

    frames = service.generate_frames(
        prepared_image_path=_prepared_image(tmp_path),
        config=SVDInferenceConfig(),
        status_callback=updates.append,
    )

    assert "callback_on_step_end" not in pipeline.kwargs
    assert not [update for update in updates if update.get("stage_detail") == "inference"]
    for frame in frames:
        frame.close()


def test_callback_cancellation_propagates_without_inference_failure(monkeypatch, tmp_path: Path) -> None:
    token = CancelToken()

    class FakePipeline:
        def __call__(self, _image, *, callback_on_step_end=None, **_kwargs):
            for step in range(25):
                if step == 12:
                    token.cancel()
                callback_on_step_end(self, step, None, {})
            raise AssertionError("denoising continued after cancellation")

    service = _service_with_pipeline(monkeypatch, FakePipeline())

    with pytest.raises(CancellationError):
        service.generate_frames(
            prepared_image_path=_prepared_image(tmp_path),
            config=SVDInferenceConfig(),
            cancel_token=token,
        )


def test_cuda_oom_is_typed_and_does_not_hide_effective_config(monkeypatch, tmp_path: Path) -> None:
    class FakeOOM(RuntimeError):
        pass

    class FakePipeline:
        def __call__(self, *_args, **_kwargs):
            raise FakeOOM("allocator exhausted")

    service = _service_with_pipeline(monkeypatch, FakePipeline())
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(OutOfMemoryError=FakeOOM))
    monkeypatch.setattr(
        "src.video.svd_service.importlib.import_module",
        lambda name: fake_torch if name == "torch" else None,
    )

    with pytest.raises(SVDOutOfMemoryError, match="Native SVD exhausted GPU memory") as exc_info:
        service.generate_frames(
            prepared_image_path=_prepared_image(tmp_path),
            config=SVDInferenceConfig(num_frames=14, num_inference_steps=25),
        )

    assert "num_inference_steps=25" in str(exc_info.value)
    assert "did not automatically rerun" in str(exc_info.value)


def test_runner_cancellation_before_export_produces_no_success_output(tmp_path: Path, monkeypatch) -> None:
    source_path = _prepared_image(tmp_path)
    prepared = SVDPreprocessResult(
        source_path=source_path,
        prepared_path=source_path,
        original_width=32,
        original_height=32,
        target_width=1024,
        target_height=576,
        resize_mode="letterbox",
        was_resized=True,
        was_padded=True,
        was_cropped=False,
    )
    monkeypatch.setattr("src.video.svd_runner.prepare_svd_input", lambda **_kwargs: prepared)
    monkeypatch.setattr(
        "src.video.svd_runner.export_video_mp4",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("export must not run")),
    )

    class FakeService:
        def prepare_runtime(self, **_kwargs):
            return None

        def generate_frames(self, *, cancel_token=None, **_kwargs):
            assert cancel_token is not None
            cancel_token.cancel()
            cancel_token.check_cancelled()

        def _release_runtime_memory(self) -> None:
            return None

    token = CancelToken()
    runner = SVDRunner(service=FakeService(), output_root=tmp_path)

    with pytest.raises(CancellationError):
        runner.run(source_image_path=source_path, config=SVDConfig(), job_id="job-cancel", cancel_token=token)

    stem = build_svd_artifact_stem(source_image_path=source_path, job_id="job-cancel")
    assert not (tmp_path / f"{stem}.mp4").exists()
    assert not (tmp_path / "manifests" / f"{stem}.json").exists()


def test_runner_projects_callback_steps_as_inference_progress(tmp_path: Path, monkeypatch) -> None:
    source_path = _prepared_image(tmp_path)
    prepared = SVDPreprocessResult(
        source_path=source_path,
        prepared_path=source_path,
        original_width=32,
        original_height=32,
        target_width=1024,
        target_height=576,
        resize_mode="letterbox",
        was_resized=True,
        was_padded=True,
        was_cropped=False,
    )
    monkeypatch.setattr("src.video.svd_runner.prepare_svd_input", lambda **_kwargs: prepared)
    monkeypatch.setattr(
        "src.video.svd_runner.SVDPostprocessRunner.process_frames",
        lambda self, **kwargs: (kwargs["frames"], {"applied": []}),
    )
    monkeypatch.setattr(
        "src.video.svd_runner.export_video_mp4",
        lambda **_kwargs: tmp_path / "svd_prepared.mp4",
    )
    monkeypatch.setattr(
        "src.video.svd_runner.write_svd_run_manifest",
        lambda **_kwargs: tmp_path / "manifests" / "svd_prepared.json",
    )
    monkeypatch.setattr("src.video.svd_runner.write_video_container_metadata", lambda *_args: True)

    class FakeService:
        def prepare_runtime(self, **_kwargs):
            return None

        def generate_frames(self, *, status_callback=None, **_kwargs):
            assert status_callback is not None
            for step in range(1, 26):
                status_callback(
                    {
                        "stage_detail": "inference",
                        "progress": step / 25,
                        "current_step": step,
                        "total_steps": 25,
                    }
                )
            return [Image.new("RGB", (8, 8), "orange")]

        def _release_runtime_memory(self) -> None:
            return None

    updates: list[dict[str, object]] = []
    config = SVDConfig.from_dict({"inference": {"num_frames": 14, "num_inference_steps": 25}})
    SVDRunner(service=FakeService(), output_root=tmp_path, status_callback=updates.append).run(
        source_image_path=source_path,
        config=config,
        job_id="job-progress",
    )

    inference = [update for update in updates if update.get("stage_detail") == "inference"]
    assert [update["current_step"] for update in inference] == [0, *range(1, 26)]
    assert [update["total_steps"] for update in inference[1:]] == [25] * 25


def test_runner_removes_new_partial_export_on_failure(tmp_path: Path, monkeypatch) -> None:
    source_path = _prepared_image(tmp_path)
    prepared = SVDPreprocessResult(
        source_path=source_path,
        prepared_path=source_path,
        original_width=32,
        original_height=32,
        target_width=1024,
        target_height=576,
        resize_mode="letterbox",
        was_resized=True,
        was_padded=True,
        was_cropped=False,
    )
    monkeypatch.setattr("src.video.svd_runner.prepare_svd_input", lambda **_kwargs: prepared)
    monkeypatch.setattr(
        "src.video.svd_runner.SVDPostprocessRunner.process_frames",
        lambda self, **kwargs: (kwargs["frames"], {"applied": []}),
    )

    def _partial_export(*, output_path, **_kwargs):
        Path(output_path).write_bytes(b"partial")
        raise RuntimeError("encoder failed")

    monkeypatch.setattr("src.video.svd_runner.export_video_mp4", _partial_export)

    class FakeService:
        def prepare_runtime(self, **_kwargs):
            return None

        def generate_frames(self, **_kwargs):
            return [Image.new("RGB", (8, 8), "purple")]

        def _release_runtime_memory(self) -> None:
            return None

    runner = SVDRunner(service=FakeService(), output_root=tmp_path)

    with pytest.raises(SVDExportError, match="encoder failed"):
        runner.run(source_image_path=source_path, config=SVDConfig(), job_id="job-export")

    stem = build_svd_artifact_stem(source_image_path=source_path, job_id="job-export")
    assert not (tmp_path / f"{stem}.mp4").exists()
    assert not (tmp_path / "manifests" / f"{stem}.json").exists()


@pytest.mark.parametrize(
    ("output_format", "save_frames"),
    [
        ("mp4", False),
        ("gif", False),
        ("frames", False),
        ("mp4", True),
    ],
)
def test_cancellation_after_manifest_removes_exact_outputs(
    tmp_path: Path,
    monkeypatch,
    output_format: str,
    save_frames: bool,
) -> None:
    source_path = _prepared_image(tmp_path)
    prepared = SVDPreprocessResult(
        source_path=source_path,
        prepared_path=source_path,
        original_width=32,
        original_height=32,
        target_width=1024,
        target_height=576,
        resize_mode="letterbox",
        was_resized=True,
        was_padded=True,
        was_cropped=False,
    )
    monkeypatch.setattr("src.video.svd_runner.prepare_svd_input", lambda **_kwargs: prepared)
    monkeypatch.setattr(
        "src.video.svd_runner.SVDPostprocessRunner.process_frames",
        lambda self, **kwargs: (kwargs["frames"], {"applied": []}),
    )

    stem = build_svd_artifact_stem(source_image_path=source_path, job_id="job-after-manifest")
    output_path = tmp_path / (
        f"{stem}.mp4" if output_format == "mp4" else f"{stem}.gif" if output_format == "gif" else f"{stem}_frames"
    )
    if output_format == "mp4":
        monkeypatch.setattr("src.video.svd_runner.export_video_mp4", lambda **_kwargs: _write_and_return(output_path))
    elif output_format == "gif":
        monkeypatch.setattr("src.video.svd_runner.export_video_gif", lambda **_kwargs: _write_and_return(output_path))
    frame_dir = tmp_path / f"{stem}_frames"
    frame_path = frame_dir / "frame_000000.png"
    if save_frames:
        monkeypatch.setattr(
            "src.video.svd_runner.save_video_frames",
            lambda **_kwargs: _write_frame_and_return(frame_path),
        )

    manifest_path = tmp_path / "manifests" / f"{stem}.json"
    token = CancelToken()

    def _write_manifest(**_kwargs):
        _kwargs["before_write"](manifest_path)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("success", encoding="utf-8")
        token.cancel()
        return manifest_path

    monkeypatch.setattr("src.video.svd_runner.write_svd_run_manifest", _write_manifest)

    class FakeService:
        def prepare_runtime(self, **_kwargs):
            return None

        def generate_frames(self, **_kwargs):
            return [Image.new("RGB", (8, 8), "yellow")]

        def _release_runtime_memory(self) -> None:
            return None

    config = SVDConfig.from_dict(
        {"output": {"output_format": output_format, "save_frames": save_frames, "save_preview_image": False}}
    )
    with pytest.raises(CancellationError):
        SVDRunner(service=FakeService(), output_root=tmp_path).run(
            source_image_path=source_path,
            config=config,
            job_id="job-after-manifest",
            cancel_token=token,
        )

    assert not output_path.exists()
    assert not manifest_path.exists()
    assert not frame_dir.exists()


def _write_and_return(path: Path) -> Path:
    path.write_bytes(b"output")
    return path


def _write_frame_and_return(path: Path) -> list[Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"frame")
    return [path]


def test_container_metadata_failure_is_typed_and_cleans_manifest(tmp_path: Path, monkeypatch) -> None:
    source_path = _prepared_image(tmp_path)
    prepared = SVDPreprocessResult(
        source_path=source_path,
        prepared_path=source_path,
        original_width=32,
        original_height=32,
        target_width=1024,
        target_height=576,
        resize_mode="letterbox",
        was_resized=True,
        was_padded=True,
        was_cropped=False,
    )
    monkeypatch.setattr("src.video.svd_runner.prepare_svd_input", lambda **_kwargs: prepared)
    monkeypatch.setattr(
        "src.video.svd_runner.SVDPostprocessRunner.process_frames",
        lambda self, **kwargs: (kwargs["frames"], {"applied": []}),
    )
    stem = build_svd_artifact_stem(source_image_path=source_path, job_id="job-metadata")
    output_path = tmp_path / f"{stem}.mp4"
    manifest_path = tmp_path / "manifests" / f"{stem}.json"
    monkeypatch.setattr("src.video.svd_runner.export_video_mp4", lambda **_kwargs: _write_and_return(output_path))

    def _write_manifest(**_kwargs):
        _kwargs["before_write"](manifest_path)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("success", encoding="utf-8")
        return manifest_path

    monkeypatch.setattr("src.video.svd_runner.write_svd_run_manifest", _write_manifest)
    monkeypatch.setattr(
        "src.video.svd_runner.write_video_container_metadata",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("metadata encoder failed")),
    )

    class FakeService:
        def prepare_runtime(self, **_kwargs):
            return None

        def generate_frames(self, **_kwargs):
            return [Image.new("RGB", (8, 8), "yellow")]

        def _release_runtime_memory(self) -> None:
            return None

    with pytest.raises(SVDExportError, match="metadata encoder failed"):
        SVDRunner(service=FakeService(), output_root=tmp_path).run(
            source_image_path=source_path,
            config=SVDConfig(),
            job_id="job-metadata",
        )

    assert not output_path.exists()
    assert not manifest_path.exists()


def test_preexisting_outputs_survive_failed_run(tmp_path: Path, monkeypatch) -> None:
    source_path = _prepared_image(tmp_path)
    stem = build_svd_artifact_stem(source_image_path=source_path, job_id="job-preexisting")
    output_path = tmp_path / f"{stem}.gif"
    manifest_path = tmp_path / "manifests" / f"{stem}.json"
    output_path.write_bytes(b"old-output")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("old-manifest", encoding="utf-8")
    prepared = SVDPreprocessResult(
        source_path=source_path,
        prepared_path=source_path,
        original_width=32,
        original_height=32,
        target_width=1024,
        target_height=576,
        resize_mode="letterbox",
        was_resized=True,
        was_padded=True,
        was_cropped=False,
    )
    monkeypatch.setattr("src.video.svd_runner.prepare_svd_input", lambda **_kwargs: prepared)
    monkeypatch.setattr(
        "src.video.svd_runner.SVDPostprocessRunner.process_frames",
        lambda self, **kwargs: (kwargs["frames"], {"applied": []}),
    )
    monkeypatch.setattr("src.video.svd_runner.export_video_gif", lambda **_kwargs: output_path)
    token = CancelToken()

    def _existing_manifest(**_kwargs):
        token.cancel()
        return manifest_path

    monkeypatch.setattr("src.video.svd_runner.write_svd_run_manifest", _existing_manifest)

    class FakeService:
        def prepare_runtime(self, **_kwargs):
            return None

        def generate_frames(self, **_kwargs):
            return [Image.new("RGB", (8, 8), "yellow")]

        def _release_runtime_memory(self) -> None:
            return None

    with pytest.raises(CancellationError):
        SVDRunner(service=FakeService(), output_root=tmp_path).run(
            source_image_path=source_path,
            config=SVDConfig.from_dict(
                {"output": {"output_format": "gif", "save_preview_image": False}}
            ),
            job_id="job-preexisting",
            cancel_token=token,
        )

    assert output_path.read_bytes() == b"old-output"
    assert manifest_path.read_text(encoding="utf-8") == "old-manifest"
