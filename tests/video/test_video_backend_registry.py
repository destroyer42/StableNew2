from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from src.video import (
    AnimateDiffVideoBackend,
    SVDNativeVideoBackend,
    VideoBackendCapabilities,
    VideoBackendRegistry,
    VideoExecutionRequest,
    build_default_video_backend_registry,
)


def test_default_video_backend_registry_registers_builtin_backends() -> None:
    registry = build_default_video_backend_registry()

    assert registry.list_backend_ids() == ["animatediff", "svd_native"]
    assert registry.list_stage_types() == ["animatediff", "svd_native"]
    assert registry.get_for_stage("animatediff").backend_id == "animatediff"
    assert registry.get_for_stage("svd_native").backend_id == "svd_native"


def test_video_backend_registry_rejects_duplicate_stage_claims() -> None:
    class _FirstBackend:
        backend_id = "first"
        capabilities = VideoBackendCapabilities(backend_id="first", stage_types=("animatediff",))

    class _SecondBackend:
        backend_id = "second"
        capabilities = VideoBackendCapabilities(backend_id="second", stage_types=("animatediff",))

    registry = VideoBackendRegistry()
    registry.register(_FirstBackend())

    try:
        registry.register(_SecondBackend())
    except ValueError as exc:
        assert "animatediff" in str(exc)
    else:
        raise AssertionError("Expected duplicate stage registration to fail")


def test_animatediff_backend_normalizes_executor_result(tmp_path: Path) -> None:
    pipeline = Mock()
    pipeline.run_animatediff_stage.return_value = {
        "video_path": str(tmp_path / "clip.mp4"),
        "output_paths": [str(tmp_path / "clip.mp4")],
        "frame_paths": [str(tmp_path / "frame_0001.png")],
        "manifest_path": str(tmp_path / "clip.json"),
        "artifact": {
            "schema": "stablenew.artifact.v2.6",
            "stage": "animatediff",
            "artifact_type": "video",
            "primary_path": str(tmp_path / "clip.mp4"),
            "output_paths": [str(tmp_path / "clip.mp4")],
            "manifest_path": str(tmp_path / "clip.json"),
            "input_image_path": str(tmp_path / "seed.png"),
        },
    }
    backend = AnimateDiffVideoBackend()

    result = backend.execute(
        pipeline,
        VideoExecutionRequest(
            backend_id="animatediff",
            stage_name="animatediff",
            stage_config={"enabled": True},
            output_dir=tmp_path,
            input_image_path=tmp_path / "seed.png",
            image_name="clip",
            prompt="animate this",
            negative_prompt="",
        ),
    )

    assert result is not None
    assert result.backend_id == "animatediff"
    assert result.primary_path == str(tmp_path / "clip.mp4")
    assert result.output_paths == [str(tmp_path / "clip.mp4")]
    variant_payload = result.to_variant_payload()
    assert variant_payload["video_backend_id"] == "animatediff"
    assert variant_payload["artifact"]["primary_path"] == str(tmp_path / "clip.mp4")


def test_svd_native_backend_normalizes_executor_result(tmp_path: Path) -> None:
    pipeline = Mock()
    pipeline.run_svd_native_stage.return_value = {
        "path": str(tmp_path / "svd.mp4"),
        "video_path": str(tmp_path / "svd.mp4"),
        "output_paths": [str(tmp_path / "svd.mp4")],
        "thumbnail_path": str(tmp_path / "preview.png"),
        "manifest_path": str(tmp_path / "svd.json"),
        "artifact": {
            "schema": "stablenew.artifact.v2.6",
            "stage": "svd_native",
            "artifact_type": "video",
            "primary_path": str(tmp_path / "svd.mp4"),
            "output_paths": [str(tmp_path / "svd.mp4")],
            "manifest_path": str(tmp_path / "svd.json"),
            "thumbnail_path": str(tmp_path / "preview.png"),
            "input_image_path": str(tmp_path / "seed.png"),
        },
    }
    backend = SVDNativeVideoBackend()

    result = backend.execute(
        pipeline,
        VideoExecutionRequest(
            backend_id="svd_native",
            stage_name="svd_native",
            stage_config={},
            output_dir=tmp_path,
            input_image_path=tmp_path / "seed.png",
            job_id="job-123",
        ),
    )

    assert result is not None
    assert result.backend_id == "svd_native"
    assert result.primary_path == str(tmp_path / "svd.mp4")
    assert result.manifest_path == str(tmp_path / "svd.json")
    variant_payload = result.to_variant_payload()
    assert variant_payload["video_backend_id"] == "svd_native"
    assert variant_payload["thumbnail_path"] == str(tmp_path / "preview.png")
