from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from src.video import ComfyWorkflowVideoBackend, VideoExecutionRequest


def test_comfy_workflow_backend_executes_ltx_workflow_and_writes_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    start_anchor = tmp_path / "start.png"
    end_anchor = tmp_path / "end.png"
    output_video = tmp_path / "clip.mp4"
    preview_frame = tmp_path / "preview.png"
    for path, payload in (
        (start_anchor, b"png"),
        (end_anchor, b"png"),
        (output_video, b"mp4"),
        (preview_frame, b"png"),
    ):
        path.write_bytes(payload)

    client = Mock()
    client.get_object_info.return_value = {
        "ComfyUI-LTXVideo": {"nodes": ["LTXLoader"]},
        "models": {"checkpoints": ["ltx_video.safetensors"]},
        "ltx_video": True,
    }
    client.queue_prompt.return_value = {"prompt_id": "prompt-123"}
    client.get_history.side_effect = [
        {},
        {
            "prompt-123": {
                "outputs": {
                    "4": {
                        "videos": [{"filename": str(output_video)}],
                        "images": [{"filename": str(preview_frame)}],
                    }
                },
                "status": {"completed": True},
            }
        },
    ]
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.wait_for_comfy_ready",
        lambda *_args, **_kwargs: True,
    )

    backend = ComfyWorkflowVideoBackend(client=client, history_poll_interval=0.01, history_timeout=1.0)

    result = backend.execute(
        pipeline=Mock(),
        request=VideoExecutionRequest(
            backend_id="comfy",
            stage_name="video_workflow",
            stage_config={
                "enabled": True,
                "workflow_id": "ltx_multiframe_anchor_v1",
                "workflow_version": "1.0.0",
            },
            output_dir=tmp_path,
            input_image_path=start_anchor,
            end_anchor_path=end_anchor,
            image_name="clip",
            prompt="cinematic dolly shot",
            negative_prompt="blurry",
            motion_profile="gentle",
            job_id="job-123",
        ),
    )

    assert result is not None
    assert result.primary_path == str(output_video)
    assert result.manifest_path is not None
    assert Path(result.manifest_path).exists()
    assert result.backend_metadata["workflow_id"] == "ltx_multiframe_anchor_v1"
    assert result.backend_metadata["prompt_id"] == "prompt-123"
    queue_payload = client.queue_prompt.call_args.args[0]
    assert queue_payload["extra_data"]["workflow_id"] == "ltx_multiframe_anchor_v1"
    assert queue_payload["prompt"]["4"]["inputs"]["output_dir"] == str(tmp_path)
    variant_payload = result.to_variant_payload()
    assert variant_payload["video_backend_id"] == "comfy"
    assert variant_payload["manifest_path"] == result.manifest_path
    assert variant_payload["artifact"]["primary_path"] == str(output_video)


def test_comfy_workflow_backend_fails_fast_when_dependencies_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    start_anchor = tmp_path / "start.png"
    end_anchor = tmp_path / "end.png"
    start_anchor.write_bytes(b"png")
    end_anchor.write_bytes(b"png")

    client = Mock()
    client.get_object_info.return_value = {"models": {"checkpoints": []}}
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.wait_for_comfy_ready",
        lambda *_args, **_kwargs: True,
    )

    backend = ComfyWorkflowVideoBackend(client=client, history_poll_interval=0.01, history_timeout=1.0)

    try:
        backend.execute(
            pipeline=Mock(),
            request=VideoExecutionRequest(
                backend_id="comfy",
                stage_name="video_workflow",
                stage_config={"enabled": True, "workflow_id": "ltx_multiframe_anchor_v1"},
                output_dir=tmp_path,
                input_image_path=start_anchor,
                end_anchor_path=end_anchor,
            ),
        )
    except RuntimeError as exc:
        assert "missing required Comfy dependencies" in str(exc)
        assert "ltx_model" in str(exc)
    else:
        raise AssertionError("Expected missing workflow dependencies to fail execution")


def test_comfy_workflow_backend_execute_segment_stamps_provenance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """PR-VIDEO-216: execute_segment() delegates to execute() and stamps
    segment provenance into raw_result and backend_metadata."""
    start_anchor = tmp_path / "start.png"
    end_anchor = tmp_path / "end.png"
    output_video = tmp_path / "seg1.mp4"
    preview_frame = tmp_path / "preview.png"
    for path, payload in (
        (start_anchor, b"png"),
        (end_anchor, b"png"),
        (output_video, b"mp4"),
        (preview_frame, b"png"),
    ):
        path.write_bytes(payload)

    client = Mock()
    client.get_object_info.return_value = {
        "ComfyUI-LTXVideo": {"nodes": ["LTXLoader"]},
        "models": {"checkpoints": ["ltx_video.safetensors"]},
        "ltx_video": True,
    }
    client.queue_prompt.return_value = {"prompt_id": "seg-prompt-001"}
    client.get_history.side_effect = [
        {},
        {
            "seg-prompt-001": {
                "outputs": {
                    "4": {
                        "videos": [{"filename": str(output_video)}],
                        "images": [{"filename": str(preview_frame)}],
                    }
                },
                "status": {"completed": True},
            }
        },
    ]
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.wait_for_comfy_ready",
        lambda *_args, **_kwargs: True,
    )

    backend = ComfyWorkflowVideoBackend(
        client=client, history_poll_interval=0.01, history_timeout=1.0
    )

    result = backend.execute_segment(
        pipeline=Mock(),
        request=VideoExecutionRequest(
            backend_id="comfy",
            stage_name="video_workflow",
            stage_config={
                "enabled": True,
                "workflow_id": "ltx_multiframe_anchor_v1",
                "workflow_version": "1.0.0",
            },
            output_dir=tmp_path,
            input_image_path=start_anchor,
            end_anchor_path=end_anchor,
            image_name="seg1",
            prompt="a stormy sea",
            negative_prompt="blurry",
            motion_profile="gentle",
            job_id="job-seg-test",
        ),
        segment_index=1,
        segment_id="abc123def456",
        carry_forward_policy="last_frame",
    )

    assert result is not None
    # Segment provenance stamped into raw_result.
    assert result.raw_result["segment_index"] == 1
    assert result.raw_result["segment_id"] == "abc123def456"
    assert result.raw_result["carry_forward_policy"] == "last_frame"
    # Segment provenance stamped into backend_metadata.
    assert result.backend_metadata["segment_index"] == 1
    assert result.backend_metadata["segment_id"] == "abc123def456"
    assert result.backend_metadata["carry_forward_policy"] == "last_frame"
    # Core execute fields still present.
    assert result.primary_path == str(output_video)
    assert result.backend_metadata["workflow_id"] == "ltx_multiframe_anchor_v1"

