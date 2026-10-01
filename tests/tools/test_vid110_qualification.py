"""Deterministic coverage for the PR-VID-110 qualification tooling (no GPU, no Comfy)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools.qualification.vid110 import evidence as ev
from tools.qualification.vid110 import inventory
from tools.qualification.vid110.owned_comfy import build_command
from tools.qualification.vid110.workflows import (
    LANE_A_FILES,
    LANE_B_FILES,
    STOCK_NODE_CLASSES,
    GenerationSpec,
    build_lane_a,
    build_lane_b,
    validate_graph,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = GenerationSpec(prompt="the person waves", width=480, height=832, length=49)


def test_inventory_reports_comfy_nodes_and_loader_files(monkeypatch: pytest.MonkeyPatch) -> None:
    stats = {
        "system": {
            "comfyui_version": "0.3.65",
            "pytorch_version": "2.8",
            "python_version": "3.10.6 x",
            "argv": ["main.py"],
        }
    }
    info = {n: {} for n in inventory.REQUIRED_NODES}
    info["UNETLoader"] = {
        "input": {"required": {"unet_name": [["wan2.2_ti2v_5B_fp16.safetensors"]]}}
    }
    info["CLIPLoader"] = {"input": {"required": {"clip_name": [["umt5.safetensors"]]}}}
    info["VAELoader"] = {"input": {"required": {"vae_name": [["wan2.2_vae.safetensors"]]}}}
    monkeypatch.setattr(
        inventory,
        "_get_json",
        lambda url, timeout=20.0: stats if url.endswith("system_stats") else info,
    )
    result = inventory.inventory_comfy("http://127.0.0.1:1")
    assert result["reachable"] and result["comfyui_version"] == "0.3.65"
    assert (
        all(result["required_nodes"].values())
        and result["optional_nodes"]["WanAnimateToVideo"] is False
    )
    assert result["loader_files"]["diffusion_models"] == ["wan2.2_ti2v_5B_fp16.safetensors"]
    problems = inventory.missing_prerequisites({"comfy": result}, required_files=LANE_A_FILES)
    assert problems == [
        "missing text_encoders file umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    ]
    assert inventory.missing_prerequisites({"comfy": {"reachable": False}}, required_files={}) == [
        "ComfyUI is not reachable"
    ]


def test_inventory_marks_an_unreachable_comfy(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, timeout: float = 20.0):
        raise OSError("refused")

    monkeypatch.setattr(inventory, "_get_json", boom)
    assert inventory.inventory_comfy("http://127.0.0.1:1")["reachable"] is False


def test_lane_workflows_use_only_stock_nodes_and_have_no_dangling_links() -> None:
    lane_a = build_lane_a(SPEC, "source.png")
    lane_b = build_lane_b(SPEC, "source.png", "drive.mp4")
    t2v = build_lane_a(SPEC, None)
    reference_only = build_lane_b(SPEC, "source.png", None)
    for graph in (lane_a, lane_b, t2v, reference_only):
        assert validate_graph(graph) == []
        assert {n["class_type"] for n in graph.values()} <= STOCK_NODE_CLASSES
    assert "start_image" in lane_a["8"]["inputs"] and "start_image" not in t2v["8"]["inputs"]
    assert lane_b["20"]["inputs"]["reference_image"] == ["7", 0]
    assert "control_video" in lane_b["20"]["inputs"]
    assert "control_video" not in reference_only["20"]["inputs"] and "14" not in reference_only
    assert lane_b["21"]["inputs"]["trim_amount"] == ["20", 3]  # VACE trims its reference latent
    assert lane_a["1"]["inputs"]["unet_name"] == LANE_A_FILES["diffusion_models"][0]
    assert lane_b["1"]["inputs"]["unet_name"] == LANE_B_FILES["diffusion_models"][0]


def test_validate_graph_flags_custom_nodes_and_broken_links() -> None:
    graph = build_lane_a(SPEC, "source.png")
    graph["99"] = {"class_type": "SomeCommunityNode", "inputs": {"image": ["404", 0]}}
    problems = validate_graph(graph)
    assert any("non-stock class SomeCommunityNode" in p for p in problems)
    assert any("missing node 404" in p for p in problems)


def test_owned_comfy_is_isolated_stock_and_uses_its_own_port(tmp_path: Path) -> None:
    command = build_command(tmp_path)
    assert "--disable-all-custom-nodes" in command
    assert command[command.index("--port") + 1] == "8199"  # never the operator's 8000
    for flag in ("--input-directory", "--output-directory", "--temp-directory", "--user-directory"):
        assert str(tmp_path) in command[command.index(flag) + 1]


def _evidence(**overrides) -> ev.RunEvidence:
    record = ev.RunEvidence(
        candidate="wan2.2-ti2v-5b",
        lane="i2v",
        evidence_class="stock-comfy",
        completed=True,
        wall_seconds=300.0,
        peaks={"vram_peak_mib": 10000.0},
        metrics={"local_motion_px": 3.0},
        scores={c: 4 for c in ev.SCORE_CRITERIA if c != "driving_motion_fidelity"},
    )
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


def test_evidence_serialization_is_deterministic_and_round_trips() -> None:
    first, second = _evidence(), _evidence()
    assert first.to_json() == second.to_json()
    assert json.loads(first.to_json())["candidate"] == "wan2.2-ti2v-5b"


def test_scoring_inputs_are_validated() -> None:
    assert ev.scoring_inputs_valid({"identity_preservation": 3}) == []
    assert ev.scoring_inputs_valid({"vibes": 3, "face_stability": 9}) == [
        "unknown criterion vibes",
        "face_stability=9 outside 0..5",
    ]


def test_verdict_requires_materially_better_motion_than_svd_not_mere_execution() -> None:
    passing, reasons = ev.decide(_evidence(), baseline_local_motion_px=1.0, motion_transfer=False)
    assert passing == ev.PASS, reasons
    verdict, why = ev.decide(
        _evidence(metrics={"local_motion_px": 1.2}), 1.0, motion_transfer=False
    )
    assert verdict == ev.NO_GO and "SVD baseline" in why[0]
    verdict, why = ev.decide(_evidence(completed=False, failure="OOM"), 1.0, motion_transfer=False)
    assert verdict == ev.NO_GO and "OOM" in why[0]


def test_verdict_downgrades_footprint_and_evidence_class_to_conditional() -> None:
    verdict, why = ev.decide(_evidence(shared_gpu=True), 1.0, motion_transfer=False)
    assert verdict == ev.CONDITIONAL and "shared GPU" in why[0]
    verdict, why = ev.decide(
        _evidence(evidence_class="community-quantized"), 1.0, motion_transfer=False
    )
    assert verdict == ev.CONDITIONAL and "not stock-Comfy" in why[0]
    verdict, _ = ev.decide(_evidence(peaks={"vram_peak_mib": 12200.0}), 1.0, motion_transfer=False)
    assert verdict == ev.CONDITIONAL


def test_unscored_or_low_scored_runs_cannot_pass() -> None:
    verdict, why = ev.decide(_evidence(scores={}), 1.0, motion_transfer=False)
    assert verdict == ev.HOLD and "unscored" in why[0]
    low = {c: 4 for c in ev.SCORE_CRITERIA if c != "driving_motion_fidelity"} | {
        "limb_anatomy_integrity": 1
    }
    verdict, why = ev.decide(_evidence(scores=low), 1.0, motion_transfer=False)
    assert verdict == ev.NO_GO and "limb_anatomy_integrity" in why[0]
    verdict, why = ev.decide(_evidence(), 1.0, motion_transfer=True)
    assert verdict == ev.HOLD and "driving_motion_fidelity" in why[0]


def test_gpu_telemetry_is_parsed_recorded_and_flushed_per_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.qualification.vid110 import monitor

    sample = monitor.parse_gpu_line("11690, 71, 268.4, 2535, 10501, 100, 0x0000000000000004")
    assert (sample.vram_mib, sample.temp_c, sample.power_w) == (11690, 71, 268.4)
    assert (sample.gpu_mhz, sample.util_pct, sample.throttle) == (2535, 100, 0x4)

    monkeypatch.setattr(monitor, "_gpu_sample", lambda: sample)
    log = tmp_path / "trail.csv"
    with monitor.ResourceSampler(interval=60.0, log_path=log) as sampler:
        sampler._sample()
        rows = log.read_text(encoding="utf-8").splitlines()  # readable before close
    assert rows[0] == monitor.TELEMETRY_HEADER and len(rows) >= 2
    peaks = sampler.peaks.as_dict()
    assert peaks["temp_peak_c"] == 71 and peaks["gpu_mhz_min_busy"] == 2535
    assert peaks["throttle_reasons_seen"] == "0x4"


def test_qualification_candidates_are_never_approved_production_workflows() -> None:
    """Qualification candidates may exist in production only as opt-in experimental workflows.

    PR-VID-130/190 deliberately registered the qualified Wan2.2 / Wan-Animate-2 graphs as
    ``experimental`` (per-job opt-in, never default-runnable); the original "appears nowhere in
    src" invariant is superseded by tests/video/test_wan22_experimental_workflow.py.  What must
    still hold: the throwaway qualification harness is not imported by production code, and no
    candidate is ever an approved (default-runnable) workflow or a registered backend.
    """

    from src.video.workflow_registry import build_default_workflow_registry

    pattern = re.compile(r"wan2[._]?2|wan_2\.1|\bvace\b|scail|wan-?animate|vid110", re.IGNORECASE)
    harness_importers = [
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "src").rglob("*.py")
        if "__pycache__" not in path.parts
        and ".mypy_cache" not in path.parts
        and re.search(
            r"^\s*(from|import)\s+tools\.qualification", path.read_text(encoding="utf-8"), re.M
        )
    ]
    assert harness_importers == []

    registry = build_default_workflow_registry()
    candidate_specs = [
        registry.get_offerable(workflow_id, version)
        for workflow_id in registry.list_workflow_ids()
        if pattern.search(workflow_id)
        for version in registry.list_versions(workflow_id)
    ]
    assert candidate_specs, "expected the experimental Wan workflows to be registered"
    assert {spec.governance_state for spec in candidate_specs} == {"experimental"}
    runnable_ids = {spec.workflow_id for spec in registry.list_specs_for_backend("comfy")}
    assert not {spec.workflow_id for spec in candidate_specs} & runnable_ids
    for name in ("workflow_registry.py", "video_backend_registry.py"):
        assert not pattern.search((REPO_ROOT / "src" / "video" / name).read_text(encoding="utf-8"))


def test_recorded_scorecard_is_valid_and_deterministic() -> None:
    from tools.qualification.vid110.scorecard import SCORECARD

    assert len(SCORECARD) == 7
    for (candidate, lane), (scores, notes) in SCORECARD.items():
        assert ev.scoring_inputs_valid(scores) == [], (candidate, lane)
        transfer = lane.endswith(
            ("_control_canny", "_control_pose")
        )  # only control-video lanes score motion
        expected = {c for c in ev.SCORE_CRITERIA if transfer or c != "driving_motion_fidelity"}
        assert set(scores) == expected, (candidate, lane)
        assert notes  # every score is backed by a written observation


def test_pose_control_graph_bypasses_canny_and_stays_stock() -> None:
    graph = build_lane_b(SPEC, "source.png", "pose.mp4", control="raw")
    assert validate_graph(graph) == []
    assert "17" not in graph and graph["20"]["inputs"]["control_video"] == ["16", 0]
    canny = build_lane_b(SPEC, "source.png", "drive.mp4")
    assert canny["20"]["inputs"]["control_video"] == ["17", 0]


def test_pose_skeleton_segments_drop_hidden_joints_and_add_a_neck() -> None:
    from tools.qualification.vid110 import pose

    marks = {
        pose.NOSE: (0.5, 0.2, 1.0),
        pose.L_SH: (0.4, 0.3, 1.0),
        pose.R_SH: (0.6, 0.3, 1.0),
        pose.L_EL: (0.4, 0.5, 0.05),  # hidden: its limb must be dropped
    }
    segments = pose.limb_points(marks)
    assert ((0.5, 0.2), (0.5, 0.3)) in [(a, b) for a, b, _ in segments]  # nose -> neck midpoint
    assert len(segments) == 3  # nose-neck, neck-R shoulder, neck-L shoulder
