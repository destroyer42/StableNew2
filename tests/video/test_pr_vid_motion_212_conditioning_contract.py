"""Conditioning wiring and fail-closed frame verification; no runtime or media decode."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.video.driving_frame_consumption import driving_frame_consumption
from src.video.motion_source_plan import MotionSourceUnavailable, motion_source_contract
from src.video.video_backend_types import VideoExecutionRequest
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_DRIVE_ID,
    build_wan_animate2_specs,
)
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_controls import resolve_operator_controls


def _spec(version="1.2.0"):
    return next(
        spec
        for spec in build_wan_animate2_specs()
        if spec.workflow_id == WAN_ANIMATE2_DRIVE_ID and spec.workflow_version == version
    )


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0", "1.2.0"])
@pytest.mark.parametrize(("width", "height"), [(480, 832), (832, 480)])
def test_rgb_pose_and_first_frame_vision_share_the_compiled_source_and_geometry(
    tmp_path: Path, version: str, width: int, height: int
):
    spec = _spec(version)
    # Paths represent inputs already frozen by the NJR builder (covered by PR-210 admission).
    stage = {
        "pose_video_path": str(tmp_path / "prepared-driving.mp4"),
        "source_preparation": {"target_dimensions": {"width": width, "height": height}},
        "frame_count": 41,
        "seed": 19103,
    }
    controls = resolve_operator_controls(spec, {"prompt": "Reference character in a studio"})
    if controls is not None:
        stage["operator_controls"] = controls
    request = VideoExecutionRequest(
        backend_id="comfy",
        stage_name="video_workflow",
        stage_config=stage,
        output_dir=tmp_path,
        input_image_path=tmp_path / "prepared-reference.png",
        prompt="Reference character in a studio",
        negative_prompt="stock negative",
        job_id="cpu-contract-only",
    )
    graph = WorkflowCompiler().compile(spec, request).backend_payload["prompt"]
    assert graph["7"]["inputs"]["image"] == str(request.input_image_path)
    assert graph["8"]["inputs"] == {"clip_vision": ["4", 0], "image": ["7", 0], "crop": "none"}
    assert graph["18"] == {"class_type": "LoadVideo", "inputs": {"file": stage["pose_video_path"]}}
    assert graph["19"] == {"class_type": "GetVideoComponents", "inputs": {"video": ["18", 0]}}
    assert graph["20"] == {
        "class_type": "ResizeImageMaskNode",
        "inputs": {
            "input": ["19", 0],
            "resize_type": "scale dimensions",
            "resize_type.width": width,
            "resize_type.height": height,
            "resize_type.crop": "center",
            "scale_method": "area",
        },
    }
    assert graph["21"] == {
        "class_type": "ImageFromBatch",
        "inputs": {"image": ["20", 0], "batch_index": 0, "length": 1},
    }
    assert graph["22"]["inputs"] == {"clip_vision": ["4", 0], "image": ["21", 0], "crop": "none"}
    consumer = graph["10"]["inputs"]
    assert consumer["reference_image"] == ["7", 0]
    assert consumer["clip_vision_output"] == ["8", 0]
    assert consumer["pose_video"] == ["20", 0]
    assert consumer["clip_vision_output_pose"] == ["22", 0]
    assert (consumer["width"], consumer["height"], consumer["length"]) == (width, height, 41)
    assert consumer["video_frame_offset"] == 0 and "continue_motion" not in consumer
    assert driving_frame_consumption(spec).verified


@pytest.mark.parametrize(
    ("node", "field", "value"),
    [
        ("10", "pose_video", ["18", 0]),  # bypass decode/resize, despite a recognised class
        ("10", "pose_video", ["20", 1]),
        ("20", "input", ["19", 1]),  # AUDIO, not IMAGE
        ("19", "video", ["18", 1]),
        ("20", "input", ["19"]),
        ("20", "input", ["19", 0, "extra"]),
        ("20", "input", ["19", False]),
        ("20", "input", ["19", "0"]),
        ("20", "input", ["20", 0]),  # cycle
        ("20", "input", ["missing", 0]),
        ("19", "video", None),
        ("18", "file", "stale-driving.mp4"),
        ("18", "file", "{{input.source_image}}"),
        ("10", "video_frame_offset", False),
        ("10", "continue_motion", ["7", 0]),  # can adjust the effective offset
    ],
)
def test_altered_paths_cannot_claim_verified_timing_or_enable_preparation(node, field, value):
    spec = _spec()
    defaults = deepcopy(spec.backend_defaults)
    defaults["prompt_template"][node]["inputs"][field] = value
    altered = replace(spec, backend_defaults=defaults)
    assert not driving_frame_consumption(altered).verified
    with pytest.raises(MotionSourceUnavailable):
        motion_source_contract(altered, 41)


@pytest.mark.parametrize("node", ["10", "18", "19", "20"])
def test_malformed_input_mappings_are_unverified(node):
    spec = _spec()
    defaults = deepcopy(spec.backend_defaults)
    defaults["prompt_template"][node]["inputs"] = ["not a mapping"]
    assert not driving_frame_consumption(replace(spec, backend_defaults=defaults)).verified


def test_verification_follows_connections_instead_of_requiring_catalog_node_ids():
    spec = _spec()
    defaults = deepcopy(spec.backend_defaults)
    graph = defaults["prompt_template"]
    renamed = {node: f"renamed-{node}" for node in graph}
    for entry in graph.values():
        for field, value in entry["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and value[0] in renamed:
                entry["inputs"][field] = (renamed[value[0]], value[1])
    defaults["prompt_template"] = {renamed[node]: entry for node, entry in graph.items()}
    assert driving_frame_consumption(replace(spec, backend_defaults=defaults)).verified
