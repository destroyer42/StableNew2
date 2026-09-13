from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from src.controller.runtime_state import CancellationError, CancelToken
from src.video.svd_config import SVDConfig
from src.video.svd_errors import SVDExportError
from src.video.svd_models import SVDPreprocessResult, SVDResult
from src.video.svd_portable_provenance import PortableVideoProvenanceError
from src.video.svd_registry import build_svd_artifact_stem, build_svd_history_record
from src.video.svd_runner import SVDRunner


@pytest.fixture(autouse=True)
def _stub_portable_mp4_provenance(monkeypatch):
    """Keep legacy runner tests hermetic; portable details have focused coverage."""

    monkeypatch.setattr(
        SVDRunner,
        "_embed_portable_svd_provenance",
        lambda _self, **_kwargs: {
            "schema": "stablenew.video-provenance.v2.6",
            "encoding": "raw",
            "payload_sha256": "a" * 64,
            "source_image_sha256": "b" * 64,
            "source_provenance_status": "missing",
            "video_media_content_sha256": "c" * 64,
        },
    )


def test_svd_runner_logs_run_summary(tmp_path: Path, monkeypatch, caplog) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")
    prepared_path = tmp_path / "_svd_temp" / "job-1" / "prepared.png"
    output_video = tmp_path / "svd_source.mp4"
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
    write_container_metadata = Mock(return_value=True)
    monkeypatch.setattr(
        "src.video.svd_runner.write_video_container_metadata",
        write_container_metadata,
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
    write_container_metadata.assert_not_called()


@pytest.mark.parametrize(
    ("output_format", "multiplier", "output_frame_count", "expected_fps"),
    [("mp4", None, 14, 7), ("mp4", 2, 28, 14), ("mp4", 4, 56, 28), ("gif", 2, 28, 14)],
)
def test_svd_runner_exports_effective_duration_preserving_fps(
    tmp_path: Path,
    monkeypatch,
    output_format: str,
    multiplier: int | None,
    output_frame_count: int,
    expected_fps: int,
) -> None:
    source_path = tmp_path / "source.png"
    Image.new("RGB", (16, 16), "white").save(source_path)
    prepared = SVDPreprocessResult(
        source_path=source_path,
        prepared_path=tmp_path / "prepared.png",
        original_width=16,
        original_height=16,
        target_width=1024,
        target_height=576,
        resize_mode="letterbox",
        was_resized=True,
        was_padded=True,
        was_cropped=False,
    )
    config_payload: dict[str, object] = {
        "inference": {"num_frames": 14, "fps": 7},
        "output": {"output_format": output_format},
    }
    if multiplier is not None:
        executable = tmp_path / "rife-ncnn-vulkan.exe"
        executable.write_bytes(b"exe")
        config_payload["postprocess"] = {
            "interpolation": {
                "enabled": True,
                "multiplier": multiplier,
                "executable_path": str(executable),
            }
        }
    config = SVDConfig.from_dict(config_payload)
    captured: dict[str, object] = {}
    output_video = tmp_path / f"output.{output_format}"
    manifest_path = tmp_path / "manifest.json"

    monkeypatch.setattr("src.video.svd_runner.prepare_svd_input", lambda **_kwargs: prepared)

    def _postprocess(_self, **_kwargs):
        metadata = None
        if multiplier is not None:
            metadata = {
                "applied": ["interpolation"],
                "interpolation": {
                    "input_frame_count": 14,
                    "input_fps": 7,
                    "output_frame_count": output_frame_count,
                    "output_fps": expected_fps,
                },
            }
        return [Image.new("RGB", (16, 16), "white") for _ in range(output_frame_count)], metadata

    monkeypatch.setattr("src.video.svd_runner.SVDPostprocessRunner.process_frames", _postprocess)
    def _export(**kwargs):
        captured["export_fps"] = kwargs["fps"]
        return output_video

    monkeypatch.setattr("src.video.svd_runner.export_video_mp4", _export)
    monkeypatch.setattr("src.video.svd_runner.export_video_gif", _export)

    def _write_manifest(**kwargs):
        captured["result"] = kwargs["result"]
        return manifest_path

    monkeypatch.setattr("src.video.svd_runner.write_svd_run_manifest", _write_manifest)
    write_container_metadata = Mock(return_value=True)
    monkeypatch.setattr("src.video.svd_runner.write_video_container_metadata", write_container_metadata)

    class _FakeService:
        def prepare_runtime(self, **_kwargs) -> None:
            return None

        def generate_frames(self, **_kwargs):
            return [Image.new("RGB", (16, 16), "white") for _ in range(14)]

        def _release_runtime_memory(self) -> None:
            return None

    result = SVDRunner(service=_FakeService(), output_root=tmp_path).run(
        source_image_path=source_path,
        config=config,
        job_id="duration-fps",
    )

    assert captured["export_fps"] == expected_fps
    assert result.frame_count == output_frame_count
    assert result.fps == expected_fps
    assert captured["result"].fps == expected_fps
    if output_format == "gif":
        container_payload = write_container_metadata.call_args.args[1]
        assert container_payload["fps"] == expected_fps
        assert container_payload["config"]["inference"]["fps"] == 7
    else:
        write_container_metadata.assert_not_called()


def test_svd_runner_rejects_unsupported_rife_multiplier_before_model_prepare(tmp_path: Path) -> None:
    calls: list[str] = []

    class _FakeService:
        def prepare_runtime(self, **_kwargs) -> None:
            calls.append("prepare_runtime")

        def generate_frames(self, **_kwargs):
            calls.append("generate_frames")
            return []

        def _release_runtime_memory(self) -> None:
            return None

    config = SVDConfig.from_dict(
        {"postprocess": {"interpolation": {"enabled": True, "multiplier": 3}}}
    )

    with pytest.raises(Exception, match="only 2x or 4x"):
        SVDRunner(service=_FakeService(), output_root=tmp_path).run(
            source_image_path=tmp_path / "unused.png",
            config=config,
            job_id="reject-before-inference",
        )

    assert calls == []


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
    monkeypatch.setattr(
        "src.video.svd_runner.write_video_container_metadata",
        lambda *_args, **_kwargs: True,
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

    executable = tmp_path / "rife-ncnn-vulkan.exe"
    executable.write_bytes(b"exe")
    runner.run(
        source_image_path=source_path,
        config=SVDConfig.from_dict({"postprocess": {"interpolation": {"enabled": True, "executable_path": str(executable)}}}),
        job_id="job-1",
    )

    details = [str(update.get("stage_detail")) for update in updates]
    assert details[:4] == ["preflight", "loading_model", "preprocess", "inference"]
    assert "postprocess: interpolation" in details
    assert details[-2:] == ["encoding", "complete"]
    postprocess_update = next(update for update in updates if update.get("stage_detail") == "postprocess: interpolation")
    assert postprocess_update["progress"] == pytest.approx(0.725)


def test_svd_runner_stamps_secondary_motion_summary_into_container_metadata(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")
    prepared_path = tmp_path / "_svd_temp" / "job-1" / "prepared.png"
    output_video = tmp_path / "svd_source.mp4"
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

    secondary_motion_block = {
        "schema": "stablenew.secondary-motion-provenance.v1",
        "intent": {"enabled": True, "mode": "apply", "intent": "micro_sway"},
        "policy": {"enabled": True, "policy_id": "svd_secondary_motion_v1", "backend_mode": "apply_shared_postprocess_candidate"},
        "apply_result": {"status": "applied", "application_path": "frame_directory_worker", "metrics": {"frames_in": 1, "frames_out": 1}},
        "summary": {
            "schema": "stablenew.secondary-motion-summary.v1",
            "enabled": True,
            "status": "applied",
            "policy_id": "svd_secondary_motion_v1",
            "application_path": "frame_directory_worker",
            "intent": {"mode": "apply", "intent": "micro_sway"},
            "backend_mode": "apply_shared_postprocess_candidate",
            "skip_reason": "",
            "metrics": {"frames_in": 1, "frames_out": 1},
        },
    }

    monkeypatch.setattr("src.video.svd_runner.prepare_svd_input", lambda **_kwargs: preprocess)
    monkeypatch.setattr(
        "src.video.svd_runner.SVDPostprocessRunner.process_frames",
        lambda self, **kwargs: (kwargs["frames"], {"applied": ["secondary_motion"], "secondary_motion": secondary_motion_block}),
    )
    monkeypatch.setattr("src.video.svd_runner.export_video_mp4", lambda **_kwargs: output_video)
    monkeypatch.setattr("src.video.svd_runner.write_svd_run_manifest", lambda **_kwargs: manifest_path)
    write_container_metadata = Mock(return_value=True)
    monkeypatch.setattr("src.video.svd_runner.write_video_container_metadata", write_container_metadata)

    class _FakeService:
        def generate_frames(self, **_kwargs):
            return [Image.new("RGB", (32, 32), "white")]

        def _release_runtime_memory(self) -> None:
            return None

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        SVDRunner,
        "_embed_portable_svd_provenance",
        lambda _self, **kwargs: captured.update(kwargs["public_metadata"])
        or {
            "schema": "stablenew.video-provenance.v2.6",
            "encoding": "raw",
            "payload_sha256": "a" * 64,
            "source_image_sha256": "b" * 64,
            "source_provenance_status": "missing",
            "video_media_content_sha256": "c" * 64,
        },
    )
    runner = SVDRunner(service=_FakeService(), output_root=tmp_path)

    runner.run(source_image_path=source_path, config=SVDConfig(), job_id="job-1")

    payload = captured
    assert payload["secondary_motion"]["summary"]["status"] == "applied"
    assert payload["secondary_motion_summary"]["status"] == "applied"
    assert payload["secondary_motion_summary"]["application_path"] == "frame_directory_worker"


def test_svd_runner_fails_and_cleans_outputs_when_required_provenance_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path, active, run_job = _patch_fake_svd_run(tmp_path, monkeypatch)
    active["job_id"] = "provenance-failure"
    monkeypatch.setattr(
        SVDRunner,
        "_embed_portable_svd_provenance",
        lambda _self, **_kwargs: (_ for _ in ()).throw(
            PortableVideoProvenanceError("intentional test failure")
        ),
    )

    with pytest.raises(SVDExportError, match="portable provenance export failed"):
        run_job("provenance-failure", SVDConfig())

    assert not (_expected_job_paths(tmp_path, source_path, "provenance-failure") & set(tmp_path.glob("**/*")))


def _patch_fake_svd_run(tmp_path: Path, monkeypatch):
    source_path = tmp_path / "same-source.png"
    Image.new("RGB", (32, 32), "white").save(source_path)
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
    active: dict[str, object] = {"job_id": ""}
    monkeypatch.setattr("src.video.svd_runner.prepare_svd_input", lambda **_kwargs: prepared)
    monkeypatch.setattr(
        "src.video.svd_runner.SVDPostprocessRunner.process_frames",
        lambda self, **kwargs: (kwargs["frames"], {"applied": []}),
    )

    def _export(*, output_path, **_kwargs):
        output = Path(output_path)
        output.write_bytes(str(active["job_id"]).encode("utf-8"))
        if active.get("fail_export"):
            raise RuntimeError("job export failed")
        return output

    monkeypatch.setattr("src.video.svd_runner.export_video_mp4", _export)
    monkeypatch.setattr("src.video.svd_runner.export_video_gif", _export)
    monkeypatch.setattr("src.video.svd_runner.write_video_container_metadata", lambda *_args: True)

    class FakeService:
        def generate_frames(self, **_kwargs):
            return [Image.new("RGB", (8, 8), "yellow")]

        def _release_runtime_memory(self) -> None:
            return None

    def _run(job_id: str, config: SVDConfig, *, cancel_token=None):
        active["job_id"] = job_id
        return SVDRunner(service=FakeService(), output_root=tmp_path).run(
            source_image_path=source_path,
            config=config,
            job_id=job_id,
            cancel_token=cancel_token,
        )

    return source_path, active, _run


def _result_paths(result: SVDResult) -> set[Path]:
    return {
        path
        for path in (
            result.video_path,
            result.gif_path,
            *result.frame_paths,
            result.thumbnail_path,
            result.metadata_path,
        )
        if path is not None
    }


def _expected_job_paths(tmp_path: Path, source_path: Path, job_id: str) -> set[Path]:
    stem = build_svd_artifact_stem(source_image_path=source_path, job_id=job_id)
    return {
        tmp_path / f"{stem}.mp4",
        tmp_path / f"{stem}.gif",
        tmp_path / f"{stem}_frames",
        tmp_path / f"{stem}_preview.png",
        tmp_path / "manifests" / f"{stem}.json",
    }


def test_svd_job_stem_replaces_source_only_collision(tmp_path: Path) -> None:
    source = tmp_path / "same-source.png"

    old_job_a = f"svd_{source.stem}"
    old_job_b = f"svd_{source.stem}"

    assert old_job_a == old_job_b
    assert build_svd_artifact_stem(source_image_path=source, job_id="job-a") != build_svd_artifact_stem(
        source_image_path=source,
        job_id="job-b",
    )


@pytest.mark.parametrize("output_format", ["mp4", "gif", "frames"])
def test_svd_jobs_have_unique_outputs_and_scoped_history(tmp_path: Path, monkeypatch, output_format: str) -> None:
    source_path, _active, run_job = _patch_fake_svd_run(tmp_path, monkeypatch)
    config = SVDConfig.from_dict(
        {"output": {"output_format": output_format, "save_preview_image": True}}
    )

    result_a = run_job("job-a", config)
    result_a_bytes = {path: path.read_bytes() for path in _result_paths(result_a) if path.is_file()}
    result_b = run_job("job-b", config)

    paths_a = _result_paths(result_a)
    paths_b = _result_paths(result_b)
    assert paths_a.isdisjoint(paths_b)
    assert result_a.metadata_path != result_b.metadata_path
    assert all(path.exists() for path in paths_a | paths_b)
    assert all(path.read_bytes() == data for path, data in result_a_bytes.items())

    for result in (result_a, result_b):
        payload = json.loads(result.metadata_path.read_text(encoding="utf-8"))
        assert payload["manifest_paths"] == [str(result.metadata_path)]
        assert set(payload["output_paths"]) == {
            str(path)
            for path in (
                [result.video_path] if result.video_path else [result.gif_path] if result.gif_path else result.frame_paths
            )
        }
        history = build_svd_history_record(config=config, result=result)
        assert history["manifest_paths"] == [str(result.metadata_path)]
        assert str(result.metadata_path) not in {
            str(path) for path in paths_a | paths_b if path != result.metadata_path
        }


def test_svd_job_b_failure_preserves_job_a_artifacts(tmp_path: Path, monkeypatch) -> None:
    source_path, active, run_job = _patch_fake_svd_run(tmp_path, monkeypatch)
    config = SVDConfig.from_dict({"output": {"output_format": "mp4", "save_preview_image": True}})
    result_a = run_job("job-a", config)
    paths_a = _result_paths(result_a)
    snapshot = {path: path.read_bytes() for path in paths_a if path.is_file()}
    active["fail_export"] = True

    with pytest.raises(SVDExportError, match="job export failed"):
        run_job("job-b", config)

    assert all(path.exists() and path.read_bytes() == data for path, data in snapshot.items())
    assert all(not path.exists() for path in _expected_job_paths(tmp_path, source_path, "job-b"))


def test_svd_job_b_cancellation_after_manifest_preserves_job_a_artifacts(tmp_path: Path, monkeypatch) -> None:
    source_path, active, run_job = _patch_fake_svd_run(tmp_path, monkeypatch)
    config = SVDConfig.from_dict({"output": {"output_format": "gif", "save_preview_image": True}})
    result_a = run_job("job-a", config)
    paths_a = _result_paths(result_a)
    snapshot = {path: path.read_bytes() for path in paths_a if path.is_file()}
    token = CancelToken()

    from src.video import svd_runner as svd_runner_module

    original_manifest_writer = svd_runner_module.write_svd_run_manifest

    def _cancel_after_manifest(**kwargs):
        path = original_manifest_writer(**kwargs)
        token.cancel()
        return path

    monkeypatch.setattr("src.video.svd_runner.write_svd_run_manifest", _cancel_after_manifest)
    with pytest.raises(CancellationError):
        run_job("job-b", config, cancel_token=token)

    assert all(path.exists() and path.read_bytes() == data for path, data in snapshot.items())
    assert all(not path.exists() for path in _expected_job_paths(tmp_path, source_path, "job-b"))
