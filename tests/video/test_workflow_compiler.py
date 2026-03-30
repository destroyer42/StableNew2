from __future__ import annotations

from pathlib import Path

from src.video import VideoExecutionRequest, WorkflowCompiler, build_default_workflow_registry


def test_workflow_compiler_builds_deterministic_payload_for_builtin_ltx_workflow(tmp_path: Path) -> None:
    registry = build_default_workflow_registry()
    compiler = WorkflowCompiler()
    request = VideoExecutionRequest(
        backend_id="comfy",
        stage_name="video_workflow",
        stage_config={"workflow_id": "ltx_multiframe_anchor_v1"},
        output_dir=tmp_path,
        input_image_path=tmp_path / "start.png",
        end_anchor_path=tmp_path / "end.png",
        mid_anchor_paths=[tmp_path / "mid_a.png", tmp_path / "mid_b.png"],
        image_name="clip_001",
        prompt="cinematic dolly shot",
        negative_prompt="blurry",
        motion_profile="gentle",
        job_id="job-123",
        backend_options={"comfy": {"queue": "video"}},
    )

    compiled = compiler.compile_registered(
        registry,
        workflow_id="ltx_multiframe_anchor_v1",
        request=request,
    )

    assert compiled.workflow_id == "ltx_multiframe_anchor_v1"
    assert compiled.backend_id == "comfy"
    assert compiled.compiled_inputs["start_anchor"] == str(tmp_path / "start.png")
    assert compiled.compiled_inputs["end_anchor"] == str(tmp_path / "end.png")
    assert compiled.compiled_inputs["mid_anchors"] == [
        str(tmp_path / "mid_a.png"),
        str(tmp_path / "mid_b.png"),
    ]
    assert compiled.compiled_outputs["output_dir"] == str(tmp_path)
    assert compiled.backend_payload["inputs"]["motion_profile"] == "gentle"
    assert compiled.backend_payload["backend_options"] == {"comfy": {"queue": "video"}}
    assert compiled.backend_payload["prompt"]["1"]["inputs"]["image"] == str(tmp_path / "start.png")
    assert compiled.backend_payload["prompt"]["4"]["inputs"]["output_dir"] == str(tmp_path)
    assert compiled.backend_payload["prompt"]["4"]["inputs"]["filename_prefix"] == "clip_001"
    assert compiled.compiler_metadata["job_id"] == "job-123"


def test_workflow_compiler_fails_fast_when_required_anchor_is_missing(tmp_path: Path) -> None:
    registry = build_default_workflow_registry()
    compiler = WorkflowCompiler()
    request = VideoExecutionRequest(
        backend_id="comfy",
        stage_name="video_workflow",
        stage_config={"workflow_id": "ltx_multiframe_anchor_v1"},
        output_dir=tmp_path,
        input_image_path=tmp_path / "start.png",
        image_name="clip_002",
    )

    try:
        compiler.compile_registered(
            registry,
            workflow_id="ltx_multiframe_anchor_v1",
            request=request,
        )
    except ValueError as exc:
        assert "end_anchor" in str(exc)
    else:
        raise AssertionError("Expected missing required workflow anchor to fail compilation")


def test_workflow_compiler_builds_conditioned_payload_from_nested_stage_config(tmp_path: Path) -> None:
    registry = build_default_workflow_registry()
    compiler = WorkflowCompiler()
    request = VideoExecutionRequest(
        backend_id="comfy",
        stage_name="video_workflow",
        stage_config={
            "workflow_id": "ltx_multiframe_anchor_v1_conditioned",
            "camera_intent": {
                "preset": "dolly_in",
                "strength": 0.4,
            },
            "controlnet": {
                "model": "depth",
                "weight": 0.85,
                "guidance_start": 0.1,
                "guidance_end": 0.9,
            },
            "depth_input": {
                "mode": "upload",
                "resolved_path": str(tmp_path / "depth.png"),
            },
        },
        output_dir=tmp_path,
        input_image_path=tmp_path / "start.png",
        end_anchor_path=tmp_path / "end.png",
        image_name="clip_conditioned",
        prompt="cinematic push-in",
        negative_prompt="blurry",
        motion_profile="balanced",
        job_id="job-conditioned-123",
    )

    compiled = compiler.compile_registered(
        registry,
        workflow_id="ltx_multiframe_anchor_v1_conditioned",
        request=request,
    )

    assert compiled.compiled_inputs["depth_map"] == str(tmp_path / "depth.png")
    assert compiled.compiled_inputs["camera_preset"] == "dolly_in"
    assert compiled.compiled_inputs["camera_strength"] == 0.4
    assert compiled.compiled_inputs["controlnet_model"] == "depth"
    assert compiled.compiled_inputs["guidance_end"] == 0.9
    assert compiled.backend_payload["prompt"]["3"]["inputs"]["image"] == str(tmp_path / "depth.png")
    assert compiled.backend_payload["prompt"]["4"]["inputs"]["controlnet_model"] == "depth"
    assert compiled.backend_payload["prompt"]["5"]["inputs"]["filename_prefix"] == "clip_conditioned"
