from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.video import (
    ComfyHealthCheckTimeout,
    ComfyWorkflowVideoBackend,
    DepthResolutionResult,
    VideoExecutionRequest,
)


def _ready_process_manager(base_url: str = "http://127.0.0.1:8188") -> object:
    return SimpleNamespace(
        ensure_running=lambda: True,
        _config=SimpleNamespace(base_url=base_url),
    )


class _DepthResolverStub:
    def __init__(self, resolved_path: Path) -> None:
        self._resolved_path = resolved_path
        self.calls: list[dict[str, object]] = []

    def resolve(self, *, source_image_path, depth_input, output_dir):
        self.calls.append(
            {
                "source_image_path": str(source_image_path),
                "depth_input": dict(depth_input or {}),
                "output_dir": str(output_dir),
            }
        )
        return DepthResolutionResult(
            mode="auto",
            source_image_path=str(source_image_path),
            resolved_path=str(self._resolved_path),
            cache_path=str(self._resolved_path),
            cache_hit=True,
        )


def test_comfy_workflow_backend_executes_ltx_workflow_and_writes_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    start_anchor = tmp_path / "start.png"
    end_anchor = tmp_path / "end.png"
    mid_anchor = tmp_path / "mid.png"
    output_video = tmp_path / "clip.mp4"
    preview_frame = tmp_path / "preview.png"
    for path, payload in (
        (start_anchor, b"png"),
        (end_anchor, b"png"),
        (mid_anchor, b"png"),
        (output_video, b"mp4"),
        (preview_frame, b"png"),
    ):
        path.write_bytes(payload)

    client = Mock()
    client.get_object_info.return_value = {
        "StableNewLTXAnchorBridge": {
            "input": {
                "required": {
                    "start_anchor": ["IMAGE"],
                    "end_anchor": ["IMAGE"],
                },
                "optional": {
                    "mid_anchors": ["STRING", {"default": "[]", "multiline": False}],
                    "prompt": ["STRING", {"default": "", "multiline": True}],
                    "negative_prompt": ["STRING", {"default": "", "multiline": True}],
                    "motion_profile": ["STRING", {"default": "gentle", "multiline": False}],
                },
            }
        },
        "StableNewSaveVideo": {
            "input": {
                "required": {
                    "images": ["IMAGE"],
                    "output_dir": ["STRING", {"default": "", "multiline": False}],
                    "filename_prefix": ["STRING", {"default": "clip", "multiline": False}],
                },
                "optional": {
                    "fps": ["FLOAT", {"default": 8.0}],
                    "format": [["mp4", "gif"], {"default": "mp4"}],
                },
            }
        },
        "LoadImage": {
            "input": {
                "required": {
                    "image": [["start.png", "end.png"], {"image_upload": True}],
                }
            }
        },
        "models": {"checkpoints": ["ltx_video.safetensors"]},
    }
    client.upload_image.side_effect = [
        {"name": "uploaded_start.png", "subfolder": "", "type": "input"},
        {"name": "uploaded_end.png", "subfolder": "", "type": "input"},
    ]
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
    write_video_container_metadata = Mock(return_value=True)
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata",
        write_video_container_metadata,
    )

    backend = ComfyWorkflowVideoBackend(
        client=client,
        process_manager=_ready_process_manager(),
        history_poll_interval=0.01,
        history_timeout=1.0,
    )

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
            mid_anchor_paths=[mid_anchor],
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
    assert queue_payload["prompt"]["1"]["inputs"]["image"] == "uploaded_start.png"
    assert queue_payload["prompt"]["2"]["inputs"]["image"] == "uploaded_end.png"
    assert queue_payload["prompt"]["3"]["inputs"]["mid_anchors"] == json.dumps([str(mid_anchor)])
    assert queue_payload["prompt"]["4"]["inputs"]["output_dir"] == str(tmp_path)
    variant_payload = result.to_variant_payload()
    assert variant_payload["video_backend_id"] == "comfy"
    assert variant_payload["manifest_path"] == result.manifest_path
    assert variant_payload["artifact"]["primary_path"] == str(output_video)
    write_video_container_metadata.assert_called_once()
    assert write_video_container_metadata.call_args.args[0] == str(output_video)


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
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata",
        lambda *_args, **_kwargs: True,
    )

    backend = ComfyWorkflowVideoBackend(
        client=client,
        process_manager=_ready_process_manager(),
        history_poll_interval=0.01,
        history_timeout=1.0,
    )

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
        assert "restart ComfyUI" in str(exc)
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
        "StableNewLTXAnchorBridge": {
            "input": {
                "required": {
                    "start_anchor": ["IMAGE"],
                    "end_anchor": ["IMAGE"],
                },
                "optional": {
                    "mid_anchors": ["STRING", {"default": "[]", "multiline": False}],
                    "prompt": ["STRING", {"default": "", "multiline": True}],
                    "negative_prompt": ["STRING", {"default": "", "multiline": True}],
                    "motion_profile": ["STRING", {"default": "gentle", "multiline": False}],
                },
            }
        },
        "StableNewSaveVideo": {
            "input": {
                "required": {
                    "images": ["IMAGE"],
                    "output_dir": ["STRING", {"default": "", "multiline": False}],
                    "filename_prefix": ["STRING", {"default": "clip", "multiline": False}],
                },
                "optional": {
                    "fps": ["FLOAT", {"default": 8.0}],
                    "format": [["mp4", "gif"], {"default": "mp4"}],
                },
            }
        },
        "LoadImage": {
            "input": {
                "required": {
                    "image": [["start.png", "end.png"], {"image_upload": True}],
                }
            }
        },
        "models": {"checkpoints": ["ltx_video.safetensors"]},
    }
    client.upload_image.side_effect = [
        {"name": "uploaded_start.png", "subfolder": "", "type": "input"},
        {"name": "uploaded_end.png", "subfolder": "", "type": "input"},
    ]
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
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata",
        lambda *_args, **_kwargs: True,
    )

    backend = ComfyWorkflowVideoBackend(
        client=client,
        process_manager=_ready_process_manager(),
        history_poll_interval=0.01,
        history_timeout=1.0,
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


def test_comfy_workflow_backend_reports_missing_managed_runtime_configuration(
    monkeypatch,
) -> None:
    backend = ComfyWorkflowVideoBackend(history_poll_interval=0.01, history_timeout=1.0)
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.build_default_comfy_process_config",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.get_global_comfy_process_manager",
        lambda: None,
    )

    def _unavailable(*_args, **_kwargs):
        raise ComfyHealthCheckTimeout("connection refused")

    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.wait_for_comfy_ready",
        _unavailable,
    )

    try:
        backend._ensure_runtime_ready()  # noqa: SLF001
    except RuntimeError as exc:
        message = str(exc)
        assert "no managed ComfyUI launch configuration" in message
        assert "presets/settings.json" in message
        assert "comfy_command" in message
        assert "comfy_workdir" in message
    else:
        raise AssertionError("Expected missing ComfyUI runtime configuration to fail")


def test_comfy_workflow_backend_executes_conditioned_ltx_workflow_with_resolved_depth(
    tmp_path: Path,
    monkeypatch,
) -> None:
    start_anchor = tmp_path / "start.png"
    end_anchor = tmp_path / "end.png"
    depth_map = tmp_path / "depth.png"
    output_video = tmp_path / "conditioned.mp4"
    preview_frame = tmp_path / "conditioned_preview.png"
    for path, payload in (
        (start_anchor, b"png"),
        (end_anchor, b"png"),
        (depth_map, b"png"),
        (output_video, b"mp4"),
        (preview_frame, b"png"),
    ):
        path.write_bytes(payload)

    client = Mock()
    client.get_object_info.return_value = {
        "StableNewLTXDepthControlBridge": {
            "input": {
                "required": {
                    "start_anchor": ["IMAGE"],
                    "end_anchor": ["IMAGE"],
                    "depth_map": ["IMAGE"],
                },
                "optional": {
                    "mid_anchors": ["STRING", {"default": "[]", "multiline": False}],
                    "prompt": ["STRING", {"default": "", "multiline": True}],
                    "negative_prompt": ["STRING", {"default": "", "multiline": True}],
                    "motion_profile": ["STRING", {"default": "gentle", "multiline": False}],
                    "camera_preset": ["STRING", {"default": "none", "multiline": False}],
                    "camera_strength": ["FLOAT", {"default": 0.35}],
                    "controlnet_model": ["STRING", {"default": "depth", "multiline": False}],
                    "controlnet_weight": ["FLOAT", {"default": 1.0}],
                    "guidance_start": ["FLOAT", {"default": 0.0}],
                    "guidance_end": ["FLOAT", {"default": 1.0}],
                },
            }
        },
        "StableNewSaveVideo": {
            "input": {
                "required": {
                    "images": ["IMAGE"],
                    "output_dir": ["STRING", {"default": "", "multiline": False}],
                    "filename_prefix": ["STRING", {"default": "clip", "multiline": False}],
                }
            }
        },
        "LoadImage": {
            "input": {
                "required": {
                    "image": [["start.png", "end.png", "depth.png"], {"image_upload": True}],
                }
            }
        },
        "models": {"checkpoints": ["ltx_video.safetensors", "depth_control_v1.safetensors"]},
    }
    client.upload_image.side_effect = [
        {"name": "uploaded_start.png", "subfolder": "", "type": "input"},
        {"name": "uploaded_end.png", "subfolder": "", "type": "input"},
        {"name": "uploaded_depth.png", "subfolder": "", "type": "input"},
    ]
    client.queue_prompt.return_value = {"prompt_id": "prompt-conditioned-001"}
    client.get_history.side_effect = [
        {},
        {
            "prompt-conditioned-001": {
                "outputs": {
                    "5": {
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
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata",
        lambda *_args, **_kwargs: True,
    )
    depth_resolver = _DepthResolverStub(depth_map)
    backend = ComfyWorkflowVideoBackend(
        client=client,
        depth_map_resolver=depth_resolver,
        process_manager=_ready_process_manager(),
        history_poll_interval=0.01,
        history_timeout=1.0,
    )

    result = backend.execute(
        pipeline=Mock(),
        request=VideoExecutionRequest(
            backend_id="comfy",
            stage_name="video_workflow",
            stage_config={
                "enabled": True,
                "workflow_id": "ltx_multiframe_anchor_v1_conditioned",
                "workflow_version": "1.0.0",
                "camera_intent": {"preset": "dolly_in", "strength": 0.4},
                "controlnet": {
                    "model": "depth",
                    "weight": 0.9,
                    "guidance_start": 0.1,
                    "guidance_end": 0.95,
                },
                "depth_input": {"mode": "auto"},
            },
            output_dir=tmp_path,
            input_image_path=start_anchor,
            end_anchor_path=end_anchor,
            image_name="conditioned",
            prompt="dramatic push in",
            negative_prompt="blurry",
            motion_profile="balanced",
            job_id="job-conditioned-001",
            workflow_id="ltx_multiframe_anchor_v1_conditioned",
            workflow_version="1.0.0",
        ),
    )

    assert result is not None
    assert depth_resolver.calls[0]["depth_input"]["mode"] == "auto"
    queue_payload = client.queue_prompt.call_args.args[0]
    assert queue_payload["prompt"]["1"]["inputs"]["image"] == "uploaded_start.png"
    assert queue_payload["prompt"]["2"]["inputs"]["image"] == "uploaded_end.png"
    assert queue_payload["prompt"]["3"]["inputs"]["image"] == "uploaded_depth.png"
    assert queue_payload["prompt"]["4"]["inputs"]["camera_preset"] == "dolly_in"
    assert queue_payload["prompt"]["4"]["inputs"]["controlnet_weight"] == 0.9
    assert result.backend_metadata["conditioning"]["depth_input"]["resolved_path"] == str(depth_map)
    manifest_payload = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest_payload["conditioning"]["camera_intent"]["preset"] == "dolly_in"
    assert manifest_payload["conditioning"]["depth_input"]["resolved_path"] == str(depth_map)


def test_comfy_workflow_backend_promotes_reencoded_secondary_motion_video(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
    monkeypatch.setattr("src.video.comfy_workflow_backend.wait_for_comfy_ready", lambda *_args, **_kwargs: True)
    container_payloads: list[dict[str, object]] = []
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata",
        lambda _path, payload: container_payloads.append(dict(payload)) or True,
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
                "summary": {"status": "applied", "policy_id": "workflow_motion_v1"}
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

    backend = ComfyWorkflowVideoBackend(
        client=client,
        process_manager=_ready_process_manager(),
        history_poll_interval=0.01,
        history_timeout=1.0,
    )
    result = backend.execute(
        pipeline=Mock(),
        request=VideoExecutionRequest(
            backend_id="comfy",
            stage_name="video_workflow",
            stage_config={
                "enabled": True,
                "workflow_id": "ltx_multiframe_anchor_v1",
                "workflow_version": "1.0.0",
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
            prompt="cinematic dolly shot",
            negative_prompt="blurry",
            motion_profile="gentle",
            job_id="job-123",
        ),
    )

    assert result is not None
    assert result.primary_path == str(promoted_video)
    assert result.raw_result["secondary_motion_source_video_path"] == str(output_video)
    assert result.raw_result["secondary_motion"]["summary"]["status"] == "applied"
    assert result.raw_result["secondary_motion_summary"]["status"] == "applied"
    assert result.replay_manifest_fragment["secondary_motion_summary"]["status"] == "applied"
    assert result.replay_manifest_fragment["secondary_motion_source_video_path"] == str(output_video)
    assert container_payloads[0]["secondary_motion_summary"]["status"] == "applied"


def test_comfy_workflow_backend_preserves_original_video_when_secondary_motion_unavailable(
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
        "StableNewLTXAnchorBridge": {"input": {}},
        "models": {"checkpoints": ["ltx_video.safetensors"]},
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
    monkeypatch.setattr("src.video.comfy_workflow_backend.wait_for_comfy_ready", lambda *_args, **_kwargs: True)
    container_payloads: list[dict[str, object]] = []
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata",
        lambda _path, payload: container_payloads.append(dict(payload)) or True,
    )
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.apply_secondary_motion_to_video",
        lambda **_kwargs: {
            "primary_path": str(output_video),
            "output_paths": [str(output_video)],
            "video_path": str(output_video),
            "video_paths": [str(output_video)],
            "frame_paths": [],
            "thumbnail_path": None,
            "secondary_motion": {
                "summary": {
                    "schema": "stablenew.secondary-motion-summary.v1",
                    "status": "unavailable",
                    "policy_id": "workflow_motion_v1",
                    "application_path": "video_reencode_worker",
                    "skip_reason": "ffmpeg_unavailable",
                }
            },
            "secondary_motion_summary": {
                "schema": "stablenew.secondary-motion-summary.v1",
                "status": "unavailable",
                "policy_id": "workflow_motion_v1",
                "application_path": "video_reencode_worker",
                "skip_reason": "ffmpeg_unavailable",
            },
            "source_video_path": str(output_video),
        },
    )

    backend = ComfyWorkflowVideoBackend(
        client=client,
        process_manager=_ready_process_manager(),
        history_poll_interval=0.01,
        history_timeout=1.0,
    )
    result = backend.execute(
        pipeline=Mock(),
        request=VideoExecutionRequest(
            backend_id="comfy",
            stage_name="video_workflow",
            stage_config={
                "enabled": True,
                "workflow_id": "ltx_multiframe_anchor_v1",
                "workflow_version": "1.0.0",
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
            prompt="cinematic dolly shot",
            negative_prompt="blurry",
            motion_profile="gentle",
            job_id="job-123",
        ),
    )

    assert result is not None
    assert result.primary_path == str(output_video)
    assert result.output_paths == [str(output_video)]
    assert result.raw_result["secondary_motion_summary"]["status"] == "unavailable"
    assert result.raw_result["secondary_motion_summary"]["skip_reason"] == "ffmpeg_unavailable"
    assert result.raw_result["secondary_motion_source_video_path"] == str(output_video)
    assert result.replay_manifest_fragment["secondary_motion_summary"]["status"] == "unavailable"
    assert container_payloads[0]["secondary_motion_summary"]["status"] == "unavailable"

