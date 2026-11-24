"""Fun Control 1.1.0 trial: the same graph as 1.0.0, queueable under an enforced VRAM floor.

1.0.0 stays pinned and refused (tests/video/test_pr_vid_fun_352.py). These tests prove the trial version
is admitted for owner testing, that the resource policy still blocks when the GPU is too full, and that
nothing about the trial weakens the per-job experimental opt-in."""

import copy
from types import SimpleNamespace

import pytest

from src.gui.view_contracts.video_batch_contract import build_preview_view
from src.video.motion_source_plan import motion_source_contract
from src.video.workflow_admission import require_workflow_admission
from src.video.workflow_readiness import WorkflowResourceReadiness
from src.video.workflow_registry import build_default_workflow_registry
from tests.video.test_pr_vid_motion_210_admission import _inputs, _record, _stack

FUN_ID = "wan22_fun_control_5b_canny_i2v_v1"
TRIAL = "1.1.0"
_CUDA = {"devices": [{"type": "cuda", "index": 0, "torch_vram_total": 0, "vram_free": 0}]}


def _spec(version: str):
    return build_default_workflow_registry().get(FUN_ID, version, allow_experimental=True)


def _built_trial(tmp_path):
    source, clip = _inputs(tmp_path)
    record = _record(tmp_path, clip, frames=17, version=TRIAL, workflow_id=FUN_ID)
    record["derived"].update(frame_rate="24/1", frames_md5_sha256="a" * 64)
    record["contract"] = motion_source_contract(_spec(TRIAL), 17).to_record()
    form = {
        "workflow_id": FUN_ID,
        "workflow_version": TRIAL,
        "prompt": "walk forward",
        "seed": "424242",
        "frame_count": "17",
        "pose_video_path": str(clip),
        "experimental_opt_in": True,
        "prepared_motion_source": record,
    }
    controller, _service = _stack(tmp_path)
    builder = controller._njr_builder
    njr = builder.build_job(form, builder.freeze_inputs(source, form)).njr
    return njr, controller, form


def test_trial_is_the_same_graph_with_a_policy_not_a_hard_refusal():
    published, trial = _spec("1.0.0"), _spec(TRIAL)
    assert trial.is_experimental and published.is_experimental
    assert trial.backend_defaults["prompt_template"] == published.backend_defaults["prompt_template"]
    assert trial.backend_defaults["asset_integrity"] == published.backend_defaults["asset_integrity"]
    # 1.0.0 is untouched and still refused.
    assert published.backend_defaults["resource_readiness"]["qualification_status"] == "not_qualified"
    assert "admission_block_reason" in published.backend_defaults["operator_projection"]
    # The trial replaces the refusal with an enforced floor and carries no block reason.
    policy = trial.backend_defaults["resource_readiness"]
    assert policy["qualification_status"] != "not_qualified"
    assert policy["min_available_to_comfy_vram_mib"] == 10000
    assert "admission_block_reason" not in trial.backend_defaults["operator_projection"]
    assert trial.backend_defaults["operator_projection"]["trial_unqualified"] is True
    assert "TRIAL" in trial.governance_notes and "NOT QUALIFIED" in trial.governance_notes


def test_trial_is_still_gated_by_per_job_experimental_opt_in():
    from src.video.workflow_registry import WorkflowLookupError

    with pytest.raises(WorkflowLookupError, match="experimental"):
        build_default_workflow_registry().get(FUN_ID, TRIAL)


def test_trial_is_blocked_when_the_gpu_is_too_full():
    readiness = WorkflowResourceReadiness(ram_probe=lambda: 32, gpu_probe=lambda _: (12282, 6000))
    result = readiness.evaluate(_spec(TRIAL), system_stats=_CUDA)
    assert not result.ready
    assert "GPU memory" in result.message and "NOT QUALIFIED" not in result.message


def test_trial_is_ready_when_the_gpu_has_the_floor_free():
    readiness = WorkflowResourceReadiness(ram_probe=lambda: 32, gpu_probe=lambda _: (12282, 11500))
    result = readiness.evaluate(_spec(TRIAL), system_stats=_CUDA)
    assert result.ready, result.message


def test_trial_is_admitted_at_the_canonical_boundary(tmp_path):
    njr, _controller, _form = _built_trial(tmp_path)
    require_workflow_admission(njr)  # no longer raises NOT QUALIFIED


def test_trial_admission_still_requires_the_jobs_own_opt_in(tmp_path):
    njr, _controller, _form = _built_trial(tmp_path)
    stage = copy.deepcopy(njr.config["video_workflow"])
    stage["video_execution"]["experimental_opt_in"] = False
    record = SimpleNamespace(
        config={"video_workflow": stage},
        stage_chain_labels=["video_workflow"],
        input_image_paths=njr.input_image_paths,
    )
    with pytest.raises(ValueError, match="experimental opt-in"):
        require_workflow_admission(record)


def test_trial_preview_no_longer_reports_queue_off_for_hardware(tmp_path):
    from pathlib import Path

    _njr, controller, form = _built_trial(tmp_path)
    source = form["prepared_motion_source"]["original"]["path"]
    reference = str(Path(source).parent / "portrait.png")
    plan = controller.preview_batch(
        form_data=form, sources=controller.select_batch_sources([reference]).sources
    )
    view = build_preview_view(plan)
    assert view.frozen
    assert "NOT QUALIFIED" not in dict(view.summary)["Hardware"]
    assert "Queue is off" not in view.headline
