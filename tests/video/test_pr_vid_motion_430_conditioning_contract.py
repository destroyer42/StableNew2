"""PR-VID-MOTION-430 Workstream A/D: the conditioning contract is derived from the registered graphs."""

from __future__ import annotations

import pytest

from src.video.workflow_catalog import build_builtin_workflow_specs
from src.video.workflow_conditioning import (
    MECH_CANNY_THEN_RESIZE,
    MECH_RGB_VAE,
    REP_POSE_MAP,
    REP_PRECOMPUTED_EDGES,
    REP_RENDERED_SILHOUETTE,
    REP_RENDERED_SKELETON,
    REP_RGB_FOOTAGE,
    REPRESENTATIONS,
    conditioning_contract,
    conditioning_contracts,
    engine_change_problem,
    envelope_problem,
    shared_envelope,
    trace_driver_path,
)
from src.video.workflow_registry import build_default_workflow_registry

FUN = "wan22_fun_control_5b_canny_i2v_v1"
ANIMATE = "wan_animate2_drive_i2v_v1"
PROMPT_ONLY = "wan22_ti2v_5b_i2v_v1"


def _spec(workflow_id: str, version: str):
    return build_default_workflow_registry().get(workflow_id, version, allow_experimental=True)


def test_fun_control_runs_canny_before_its_own_crop_and_resize():
    contract = conditioning_contract(_spec(FUN, "1.1.0"))
    assert contract is not None
    assert contract.mechanism == MECH_CANNY_THEN_RESIZE
    assert [s.node for s in contract.stages] == [
        "LoadVideo",
        "GetVideoComponents",
        "Canny",
        "Wan22FunControlToVideo",
    ]
    # No resize stage exists in the graph: the only crop/resize is inside the consuming node, after Canny.
    assert contract.preprocessing_before_resize is True
    assert contract.edge_preprocessing
    assert (
        "centre-cropped" in contract.stages[-1].detail
        and "bilinearly" in contract.stages[-1].detail
    )


def test_animate2_resizes_and_encodes_rgb_with_first_frame_vision_context():
    contract = conditioning_contract(_spec(ANIMATE, "1.2.0"))
    assert contract is not None
    assert contract.mechanism == MECH_RGB_VAE
    kinds = [s.kind for s in contract.stages]
    assert "edge_detect" not in kinds and "resize" in kinds and "vision_context" in kinds
    assert contract.preprocessing_before_resize is None
    assert not contract.edge_preprocessing
    assert "pose_strength" in contract.supported_controls


def test_prompt_only_workflows_have_no_conditioning_contract_and_are_not_reinterpreted():
    registry = build_default_workflow_registry()
    spec = registry.get(PROMPT_ONLY, "1.3.0", allow_experimental=True)
    assert conditioning_contract(spec) is None


def test_version_specific_governance_is_preserved():
    published = conditioning_contract(_spec(FUN, "1.0.0"))
    trial = conditioning_contract(_spec(FUN, "1.1.0"))
    assert published.refusal_reason and published.status_label == "Refused"
    assert published.qualification_status == "not_qualified"
    assert not trial.refusal_reason and trial.trial
    assert trial.status_label == "Experimental trial (not qualified)"
    assert trial.qualification_status == "trial_unqualified"
    assert trial.resource_readiness["min_available_to_comfy_vram_mib"] == 10000
    assert any("provisional" in text for text, _basis in trial.limitations)
    # Same graph, so the same conditioning path.
    assert [s.node for s in published.stages] == [s.node for s in trial.stages]


def test_precomputed_edges_and_pose_maps_are_refused_for_both_mechanisms():
    for contract in (
        conditioning_contract(_spec(FUN, "1.1.0")),
        conditioning_contract(_spec(ANIMATE, "1.2.0")),
    ):
        edges = contract.acceptance(REP_PRECOMPUTED_EDGES)
        pose = contract.acceptance(REP_POSE_MAP)
        assert not edges.accepted and not pose.accepted
        assert "OpenPose" in pose.note
    fun_edges = conditioning_contract(_spec(FUN, "1.1.0")).acceptance(REP_PRECOMPUTED_EDGES)
    assert "second time" in fun_edges.note and "no direct edge-input mode" in fun_edges.note


def test_a_silhouette_video_is_silhouette_derived_rgb_not_an_edge_tensor():
    fun = conditioning_contract(_spec(FUN, "1.1.0")).acceptance(REP_RENDERED_SILHOUETTE)
    assert fun.accepted
    assert "not an externally computed edge tensor" in fun.note
    animate = conditioning_contract(_spec(ANIMATE, "1.2.0")).acceptance(REP_RENDERED_SILHOUETTE)
    assert animate.accepted and "not tested" in animate.note


def test_every_known_representation_has_an_explicit_answer_and_unknown_is_refused():
    contract = conditioning_contract(_spec(ANIMATE, "1.2.0"))
    assert {contract.acceptance(r).representation for r in REPRESENTATIONS} == set(REPRESENTATIONS)
    assert contract.acceptance(REP_RGB_FOOTAGE).accepted
    assert contract.acceptance(REP_RENDERED_SKELETON).accepted
    assert not contract.acceptance("depth_video").accepted


def test_shared_envelope_is_the_intersection_of_declared_lengths():
    animate = conditioning_contract(_spec(ANIMATE, "1.2.0"))
    fun = conditioning_contract(_spec(FUN, "1.1.0"))
    envelope = shared_envelope([animate, fun])
    assert envelope.fps == 24
    assert (envelope.minimum, envelope.maximum) == (17, 49)
    assert envelope.contains(33) and envelope.contains(49) and not envelope.contains(81)
    assert not envelope.contains(18)  # not 4n+1
    assert "81 frames is outside the shared envelope" in envelope_problem(envelope, 81)
    assert envelope_problem(envelope, 49) is None
    assert max(animate.legal_frames) == 81 and max(fun.legal_frames) == 49


def test_a_disjoint_or_empty_comparison_says_so():
    assert shared_envelope([]).notes
    fun = conditioning_contract(_spec(FUN, "1.1.0"))
    assert "share no legal length" in envelope_problem(
        type(shared_envelope([fun]))((), 24, ("a", "b")), 33
    )


@pytest.mark.parametrize(
    ("prepared", "frames", "expected"),
    [
        (None, 33, "records no workflow contract"),
        ({"workflow_id": ANIMATE, "workflow_version": "1.2.0", "frame_count": 33}, 33, "not"),
        ({"workflow_id": FUN, "workflow_version": "1.0.0", "frame_count": 33}, 33, "1.0.0"),
        ({"workflow_id": FUN, "workflow_version": "1.1.0", "frame_count": 49}, 33, "49 frames"),
        ({"workflow_id": FUN, "workflow_version": "1.1.0", "frame_count": 33}, 33, None),
    ],
)
def test_an_engine_change_never_silently_reuses_an_incompatible_preparation(
    prepared, frames, expected
):
    contract = conditioning_contract(_spec(FUN, "1.1.0"))
    problem = engine_change_problem(prepared, contract, frames)
    if expected is None:
        assert problem is None
    else:
        assert problem is not None and expected in problem


def test_alignment_is_reported_from_the_real_support_check():
    animate = conditioning_contract(_spec(ANIMATE, "1.2.0"))
    fun = conditioning_contract(_spec(FUN, "1.1.0"))
    assert animate.required_preparation[-1].startswith("Align Motion is available")
    assert fun.required_preparation[-1].startswith("Align Motion is not available")


def test_contracts_are_json_plain_and_cover_every_registered_driving_workflow():
    specs = [s for s in build_builtin_workflow_specs() if "pose_video" in s.declared_input_names]
    contracts = conditioning_contracts(specs)
    assert len(contracts) == len(specs) >= 4
    assert {c.workflow_id for c in contracts} >= {FUN, ANIMATE}
    for contract in contracts:
        payload = contract.to_dict()
        assert payload["mechanism"] in (MECH_RGB_VAE, MECH_CANNY_THEN_RESIZE)
        assert payload["stages"] and payload["limitations"]


def test_trace_finds_nothing_in_a_graph_without_a_driver():
    assert trace_driver_path({"1": {"class_type": "KSampler", "inputs": {"seed": 1}}}) == ([], [])
