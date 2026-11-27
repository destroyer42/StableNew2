"""V1 end frame: the experimental A14B start-and-end-image workflow, from catalog to frozen NJR and dispatch inputs.

No GPU, Comfy process, model or network: the graph is compiled and the job built against temp files.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.pipeline.njr_core_v26 import thaw_json
from src.pipeline.policy_warnings import CODE_VIDEO_END_FRAME_CROPPED, CODE_VIDEO_EXPERIMENTAL
from src.video.motion_rerun import intent_snapshot, rerun_form_state
from src.video.video_backend_types import VideoExecutionRequest
from src.video.video_workflow_intent import form_visibility
from src.video.video_workflow_njr_builder import VideoWorkflowNjrBuilder
from src.video.workflow_catalog_wan_a14b import (
    WAN_A14B_FLF_ID,
    WAN_A14B_ID,
    a14b_launch_attention,
    build_wan_a14b_flf_spec,
    build_wan_a14b_spec,
)
from src.video.workflow_compiler import WorkflowCompiler
from src.video.workflow_tasks import (
    TASK_ANIMATE,
    TASK_BATCH,
    TASK_BETWEEN,
    TASK_FOLLOW_CLIP,
    TASK_SEQUENCE,
    choose_workflow,
    eligible_workflows,
    infer_task,
)


def _image(path: Path, size: tuple[int, int], color: str = "navy") -> str:
    Image.new("RGB", size, color).save(path)
    return str(path)


@pytest.fixture
def builder(tmp_path):
    return VideoWorkflowNjrBuilder(
        workflow_registry=DefaultWorkflowRegistryPort(),
        output_dir_provider=lambda: str(tmp_path / "output"),
    )


def _form(end_image: str, **extra):
    return {
        "workflow_id": WAN_A14B_FLF_ID,
        "workflow_version": "1.0.0",
        "prompt": "turns toward the camera",
        "seed": "7",
        "frame_count": 49,
        "end_anchor_path": end_image,
        "experimental_opt_in": True,
        **extra,
    }


def _build(builder, source: str, form):
    frozen = builder.freeze_inputs(source, form)
    return frozen, builder.build_job(form, frozen)


def _stage(njr):
    return thaw_json(next(s for s in njr.stage_chain if s.stage_type == "video_workflow").extra)


def test_the_graph_is_1_0_0_with_the_stock_first_and_last_frame_node():
    base, flf = build_wan_a14b_spec(), build_wan_a14b_flf_spec()
    graph, base_graph = (
        flf.backend_defaults["prompt_template"],
        base.backend_defaults["prompt_template"],
    )
    assert graph["10"]["class_type"] == "WanFirstLastFrameToVideo"
    assert graph["10"]["inputs"]["start_image"] == ["9", 0]
    assert graph["10"]["inputs"]["end_image"] == ["19", 0]
    assert graph["19"] == {"class_type": "LoadImage", "inputs": {"image": "{{input.end_anchor}}"}}
    changed = {
        node_id
        for node_id in set(graph) | set(base_graph)
        if graph.get(node_id) != base_graph.get(node_id)
    }
    assert changed == {"10", "16", "19"}  # the samplers, experts, LoRAs and encoder are untouched
    # The approved 1.0.0 is untouched.
    assert base_graph["10"]["class_type"] == "WanImageToVideo" and "19" not in base_graph
    assert flf.is_experimental and flf.workflow_id != WAN_A14B_ID
    assert "end_anchor" in flf.required_input_names
    assert "mid_anchors" not in flf.accepted_controls
    nodes = {d.locator for d in flf.dependency_specs if d.dependency_kind == "stock_node"}
    assert "WanFirstLastFrameToVideo" in nodes and "WanImageToVideo" not in nodes
    assert a14b_launch_attention(flf) == "baseline"
    visible = form_visibility(flf)
    assert visible["end_anchor"] and not visible["mid_anchors"] and not visible["pose_video"]


def test_both_images_reach_the_compiled_graph(tmp_path):
    spec = build_wan_a14b_flf_spec()
    request = VideoExecutionRequest(
        backend_id="comfy",
        stage_name="video_workflow",
        stage_config={
            "seed": 7,
            "frame_count": 49,
            "source_preparation": {"target_dimensions": {"width": 480, "height": 832}},
        },
        output_dir=tmp_path,
        input_image_path=tmp_path / "start.png",
        end_anchor_path=tmp_path / "end.png",
        prompt="p",
        negative_prompt="n",
        job_id="job",
    )
    compiled = WorkflowCompiler().compile(spec, request)
    prompt = compiled.backend_payload["prompt"]
    assert prompt["9"]["inputs"]["image"] == str(tmp_path / "start.png")
    assert prompt["19"]["inputs"]["image"] == str(tmp_path / "end.png")
    assert prompt["10"]["inputs"]["width"] == 480 and prompt["10"]["inputs"]["length"] == 49


def test_the_end_image_is_prepared_to_the_start_images_size_and_frozen_with_its_hash(
    builder, tmp_path
):
    source = _image(tmp_path / "start.png", (480, 832))
    end = _image(tmp_path / "end.png", (960, 1664), "maroon")
    frozen, built = _build(builder, source, _form(end))
    stage = _stage(built.njr)
    prepared = Path(stage["end_anchor_path"])
    assert prepared != Path(end) and Image.open(prepared).size == (480, 832)
    assert stage["end_anchor_sha256"] == frozen.end_frame["prepared_sha256"]
    meta = built.njr.extra_metadata["video_workflow"]["end_frame"]
    assert meta["original_path"] == end and meta["prepared_path"] == str(prepared)
    accepted = {item["code"] for item in built.njr.extra_metadata["accepted_warnings"]}
    assert accepted == {CODE_VIDEO_EXPERIMENTAL}  # same shape: no crop warning
    builder.verify_unchanged(frozen)
    Image.new("RGB", (4, 4)).save(end)
    with pytest.raises(ValueError, match="original end image changed"):
        builder.verify_unchanged(frozen)


def test_an_end_image_of_another_shape_is_warned_about_not_refused(builder, tmp_path):
    source = _image(tmp_path / "start.png", (480, 832))
    end = _image(tmp_path / "wide.png", (1280, 720), "maroon")
    _frozen, built = _build(builder, source, _form(end))
    codes = [item["code"] for item in built.njr.extra_metadata["accepted_warnings"]]
    assert CODE_VIDEO_END_FRAME_CROPPED in codes


def test_without_an_end_image_the_job_is_refused_with_the_reason(builder, tmp_path):
    source = _image(tmp_path / "start.png", (480, 832))
    ok, reason = builder.validate_form_data(_form(""))
    assert not ok and "end anchor image" in reason
    with pytest.raises(ValueError):
        builder.freeze_inputs(source, _form(""))


def test_experimental_needs_the_jobs_own_opt_in(builder, tmp_path):
    ok, reason = builder.validate_form_data(
        _form(_image(tmp_path / "e.png", (64, 64)), experimental_opt_in=False)
    )
    assert not ok and "experimental" in reason


def test_a_re_run_restores_the_operators_own_end_image(builder, tmp_path):
    source = _image(tmp_path / "start.png", (480, 832))
    end = _image(tmp_path / "end.png", (960, 1664), "maroon")
    _frozen, built = _build(builder, source, _form(end))
    snapshot = intent_snapshot(built.njr)
    assert snapshot.end_image_path == end
    assert rerun_form_state(snapshot)["end_anchor_path"] == end


def _records():
    return [
        {
            "workflow_id": spec.workflow_id,
            "governance_state": spec.governance_state,
            "experimental": spec.is_experimental,
            "required_inputs": list(spec.required_input_names),
            "form_visibility": form_visibility(spec),
        }
        for spec in (build_wan_a14b_spec(), build_wan_a14b_flf_spec())
    ]


def test_only_the_start_and_end_task_offers_the_end_frame_workflow():
    records = _records()
    assert [r["workflow_id"] for r in eligible_workflows(TASK_BETWEEN, records)] == [
        WAN_A14B_FLF_ID
    ]
    for task in (TASK_ANIMATE, TASK_SEQUENCE, TASK_BATCH, TASK_FOLLOW_CLIP):
        assert WAN_A14B_FLF_ID not in [r["workflow_id"] for r in eligible_workflows(task, records)]
    choice = choose_workflow(TASK_BETWEEN, records)
    assert choice.workflow_id == WAN_A14B_FLF_ID and choice.needs_opt_in
    assert infer_task(records[1]) == TASK_BETWEEN
    assert infer_task(records[1], saved_task=TASK_ANIMATE) == TASK_BETWEEN
