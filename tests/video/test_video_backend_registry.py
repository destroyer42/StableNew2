from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from src.video import (
    AnimateDiffVideoBackend,
    ComfyWorkflowVideoBackend,
    SVDNativeVideoBackend,
    VideoBackendCapabilities,
    VideoBackendRegistry,
    VideoExecutionRequest,
    build_default_video_backend_registry,
)


def test_default_video_backend_registry_registers_builtin_backends() -> None:
    registry = build_default_video_backend_registry()

    assert registry.list_backend_ids() == ["animatediff", "comfy", "svd_native"]
    assert registry.list_stage_types() == ["animatediff", "svd_native", "video_workflow"]
    assert registry.get_for_stage("animatediff").backend_id == "animatediff"
    assert registry.get_for_stage("svd_native").backend_id == "svd_native"
    assert registry.get_for_stage("video_workflow").backend_id == "comfy"


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
        "secondary_motion": {
            "summary": {
                "schema": "stablenew.secondary-motion-summary.v1",
                "status": "applied",
                "policy_id": "animatediff_motion_v1",
            }
        },
        "secondary_motion_summary": {
            "schema": "stablenew.secondary-motion-summary.v1",
            "status": "applied",
            "policy_id": "animatediff_motion_v1",
        },
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
    assert variant_payload["video_replay_manifest"]["secondary_motion_summary"]["status"] == "applied"


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


def test_comfy_workflow_backend_normalizes_executor_result(tmp_path: Path, monkeypatch) -> None:
    start_anchor = tmp_path / "start.png"
    end_anchor = tmp_path / "end.png"
    output_video = tmp_path / "clip.mp4"
    promoted_video = tmp_path / "clip_secondary_motion.mp4"
    preview_frame = tmp_path / "preview.png"
    motion_frame = tmp_path / "motion_frame.png"
    for path, payload in (
        (start_anchor, b"png"),
        (end_anchor, b"png"),
        (output_video, b"mp4"),
        (promoted_video, b"mp4"),
        (preview_frame, b"png"),
        (motion_frame, b"png"),
    ):
        path.write_bytes(payload)

    client = Mock()
    client.get_object_info.return_value = {
        "StableNewLTXAnchorBridge": {"input": {}},
        "models": {"checkpoints": ["ltx_video.safetensors"]},
    }
    client.queue_prompt.return_value = {"prompt_id": "prompt-123"}
    client.get_history.return_value = {
        "prompt-123": {
            "outputs": {
                "4": {
                    "videos": [{"filename": str(output_video)}],
                    "images": [{"filename": str(preview_frame)}],
                }
            },
            "status": {"completed": True},
        }
    }
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.wait_for_comfy_ready",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.apply_secondary_motion_to_video",
        lambda **_kwargs: {
            "primary_path": str(promoted_video),
            "output_paths": [str(promoted_video)],
            "video_path": str(promoted_video),
            "video_paths": [str(promoted_video)],
            "frame_paths": [str(motion_frame)],
            "thumbnail_path": str(motion_frame),
            "secondary_motion": {
                "summary": {
                    "schema": "stablenew.secondary-motion-summary.v1",
                    "status": "applied",
                    "policy_id": "workflow_motion_v1",
                }
            },
            "secondary_motion_summary": {
                "schema": "stablenew.secondary-motion-summary.v1",
                "status": "applied",
                "policy_id": "workflow_motion_v1",
                "application_path": "video_reencode_worker",
            },
            "source_video_path": str(output_video),
        },
    )
    backend = ComfyWorkflowVideoBackend(client=client, history_poll_interval=0.01, history_timeout=1.0)

    result = backend.execute(
        Mock(),
        VideoExecutionRequest(
            backend_id="comfy",
            stage_name="video_workflow",
            stage_config={
                "enabled": True,
                "workflow_id": "ltx_multiframe_anchor_v1",
                "secondary_motion": {
                    "enabled": True,
                    "intent": {"enabled": True, "mode": "apply", "intent": "micro_sway"},
                    "policy": {"enabled": True, "policy_id": "workflow_motion_v1"},
                },
            },
            output_dir=tmp_path,
            input_image_path=start_anchor,
            end_anchor_path=end_anchor,
            image_name="clip",
            prompt="animate this",
            negative_prompt="",
            job_id="job-123",
        ),
    )

    assert result is not None
    assert result.backend_id == "comfy"
    assert result.primary_path == str(promoted_video)
    assert result.manifest_path is not None
    variant_payload = result.to_variant_payload()
    assert variant_payload["video_backend_id"] == "comfy"
    assert variant_payload["artifact"]["primary_path"] == str(promoted_video)
    assert variant_payload["video_replay_manifest"]["secondary_motion_summary"]["status"] == "applied"
    assert variant_payload["video_replay_manifest"]["secondary_motion_source_video_path"] == str(output_video)
