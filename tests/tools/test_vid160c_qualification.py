"""PR-VID-160C qualification harness: pose-video graph freeze, no face_video, identical
frozen model/seed/settings to VID-160B, exactly-one-submit, external-runtime refusal, no retry,
ownership-safe teardown, safety thresholds unchanged, pose-asset determinism, evidence
persistence on exception (no GPU, no real Comfy, no queue)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools.qualification.vid160b import graph as backbone_graph
from tools.qualification.vid160b.telemetry import HIGH_SWAP_PERCENT, LOW_RAM_CONSECUTIVE, LOW_RAM_GB
from tools.qualification.vid160c import graph as pose_graph
from tools.qualification.vid160c import pose_asset
from tools.qualification.vid160c import run as harness

# --- graph freeze: pose_video present, wired, no face_video ------------------------------------


def test_frozen_graph_contains_pose_video_wired_to_get_video_components() -> None:
    spec = pose_graph.PoseProbeSpec(reference_image="ref.png", pose_video_file="pose.mp4")
    wf = pose_graph.build_pose_probe_graph(spec)
    assert pose_graph.validate_graph(wf) == []
    animate_inputs = next(
        n["inputs"] for n in wf.values() if n["class_type"] == "WanAnimateToVideo"
    )
    assert animate_inputs["pose_video"] == ["17", 0]
    assert wf["17"] == {"class_type": "GetVideoComponents", "inputs": {"video": ["16", 0]}}
    assert wf["16"]["class_type"] == "LoadVideo"
    assert wf["16"]["inputs"]["file"] == "pose.mp4"


def test_frozen_graph_never_includes_face_background_or_character_mask() -> None:
    spec = pose_graph.PoseProbeSpec(reference_image="ref.png", pose_video_file="pose.mp4")
    wf = pose_graph.build_pose_probe_graph(spec)
    animate_inputs = next(
        n["inputs"] for n in wf.values() if n["class_type"] == "WanAnimateToVideo"
    )
    for excluded in ("face_video", "background_video", "character_mask"):
        assert excluded not in animate_inputs


def test_validate_graph_flags_missing_pose_video() -> None:
    spec = pose_graph.PoseProbeSpec(reference_image="ref.png", pose_video_file="pose.mp4")
    wf = pose_graph.build_pose_probe_graph(spec)
    del wf["10"]["inputs"]["pose_video"]
    problems = pose_graph.validate_graph(wf)
    assert any("missing pose_video" in p for p in problems)


def test_validate_graph_flags_a_face_video_addition() -> None:
    spec = pose_graph.PoseProbeSpec(reference_image="ref.png", pose_video_file="pose.mp4")
    wf = pose_graph.build_pose_probe_graph(spec)
    wf["10"]["inputs"]["face_video"] = ["17", 0]
    problems = pose_graph.validate_graph(wf)
    assert any("must not include face_video" in p for p in problems)


def test_validate_graph_flags_pose_video_wired_to_the_wrong_node() -> None:
    spec = pose_graph.PoseProbeSpec(reference_image="ref.png", pose_video_file="pose.mp4")
    wf = pose_graph.build_pose_probe_graph(spec)
    wf["10"]["inputs"]["pose_video"] = ["7", 0]  # wired to LoadImage instead
    problems = pose_graph.validate_graph(wf)
    assert any("not wired to GetVideoComponents" in p for p in problems)


# --- identical frozen model/seed/settings to VID-160B -------------------------------------------


def test_pose_probe_defaults_match_the_vid160b_backbone_probe_exactly() -> None:
    backbone = backbone_graph.ProbeSpec(reference_image="ref.png")
    pose = pose_graph.PoseProbeSpec(reference_image="ref.png", pose_video_file="pose.mp4")
    for field in ("width", "height", "length", "steps", "cfg", "shift", "seed", "sampler",
                  "scheduler"):
        assert getattr(backbone, field) == getattr(pose, field), field


def test_pose_probe_reuses_the_same_frozen_model_constants() -> None:
    assert pose_graph.UNET_GGUF_FILENAME == backbone_graph.UNET_GGUF_FILENAME
    assert pose_graph.CLIP_FILENAME == backbone_graph.CLIP_FILENAME
    assert pose_graph.VAE_FILENAME == backbone_graph.VAE_FILENAME
    assert pose_graph.CLIP_VISION_FILENAME == backbone_graph.CLIP_VISION_FILENAME


def test_graph_rejects_dimensions_not_divisible_by_16() -> None:
    with pytest.raises(ValueError, match="divisible by 16"):
        pose_graph.build_pose_probe_graph(
            pose_graph.PoseProbeSpec(reference_image="ref.png", pose_video_file="p.mp4", width=257)
        )


def test_graph_rejects_an_invalid_length() -> None:
    with pytest.raises(ValueError, match="length must be"):
        pose_graph.build_pose_probe_graph(
            pose_graph.PoseProbeSpec(reference_image="ref.png", pose_video_file="p.mp4", length=10)
        )


# --- pose-asset determinism ----------------------------------------------------------------------


def test_sample_indices_are_deterministic_and_evenly_spaced() -> None:
    first = pose_asset.sample_indices(49, 13)
    second = pose_asset.sample_indices(49, 13)
    assert first == second
    assert len(first) == 13
    assert first[0] == 0 and first[-1] == 48
    assert first == sorted(first)


def test_sample_indices_never_exceeds_available_frames() -> None:
    indices = pose_asset.sample_indices(5, 13)
    assert len(indices) == 5
    assert max(indices) == 4


def test_sample_indices_rejects_non_positive_arguments() -> None:
    with pytest.raises(ValueError):
        pose_asset.sample_indices(0, 13)
    with pytest.raises(ValueError):
        pose_asset.sample_indices(49, 0)


def test_center_square_crop_produces_a_square_from_a_portrait_frame() -> None:
    import numpy as np

    frame = np.zeros((832, 480, 3), dtype=np.uint8)
    cropped = pose_asset.center_square_crop(frame)
    assert cropped.shape[0] == cropped.shape[1] == 480


# --- external-runtime refusal / dry-run ----------------------------------------------------------


def test_main_stops_before_building_anything_when_an_external_comfy_is_serving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    built: list[str] = []
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "healthy"})
    monkeypatch.setattr(harness, "run_probe", lambda *_a: built.append("ran") or 0)
    assert harness.main(["ref.png", "pose.mp4"]) == 3
    assert built == []
    assert "never adopts or restarts" in capsys.readouterr().out


def test_dry_run_never_calls_run_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    monkeypatch.setattr(harness, "run_probe", lambda *_a: built.append("ran") or 0)
    assert harness.main(["ref.png", "pose.mp4", "--dry"]) == 0
    assert built == []


# --- exactly-one-submit / no retry ----------------------------------------------------------------


def test_run_probe_calls_the_stack_exactly_once_and_never_retries_a_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(harness, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    monkeypatch.setattr(harness, "_teardown", lambda _stack: (False, []))
    calls: list[str] = []

    def failing_run(stack, args, evidence):
        calls.append("attempt")
        evidence["status"] = "dependency_blocked"
        return 1

    monkeypatch.setattr(harness, "_run_probe", failing_run)
    assert harness.run_probe(argparse.Namespace(reference_image="ref.png", pose_video="p.mp4")) == 1
    assert calls == ["attempt"]

    data = json.loads((tmp_path / "reports" / "evidence.json").read_text(encoding="utf-8"))
    assert data["status"] == "dependency_blocked"


# --- evidence persistence on abort / owned-runtime cleanup -----------------------------------------


def test_run_probe_writes_partial_evidence_and_still_tears_down_on_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(harness, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    teardown_calls: list[int] = []

    def teardown(_stack):
        teardown_calls.append(1)
        return False, []

    monkeypatch.setattr(harness, "_teardown", teardown)

    def aborting_run(stack, args, evidence):
        evidence["prompt_id"] = "in-flight"
        raise RuntimeError("GPU lost")

    monkeypatch.setattr(harness, "_run_probe", aborting_run)
    with pytest.raises(RuntimeError, match="GPU lost"):
        harness.run_probe(argparse.Namespace(reference_image="ref.png", pose_video="p.mp4"))

    assert teardown_calls == [1]
    data = json.loads((tmp_path / "reports" / "evidence.json").read_text(encoding="utf-8"))
    assert data["prompt_id"] == "in-flight"
    assert "GPU lost" in data["aborted"]


def test_teardown_stops_only_a_process_this_run_owns() -> None:
    owned_manager = SimpleNamespace(owns_process=True, stop=Mock())
    stack = harness._Stack(manager=owned_manager)
    owned, errors = harness._teardown(stack)
    assert owned is True and errors == []
    owned_manager.stop.assert_called_once()


def test_teardown_never_stops_an_unowned_or_external_process() -> None:
    for manager in (SimpleNamespace(owns_process=False, stop=Mock()), None):
        stack = harness._Stack(manager=manager)
        owned, errors = harness._teardown(stack)
        assert owned is False and errors == []
        if manager is not None:
            manager.stop.assert_not_called()


# --- safety thresholds unchanged from VID-160B ------------------------------------------------------


def test_safety_thresholds_are_reused_unchanged_from_vid160b() -> None:
    assert LOW_RAM_GB == 1.0
    assert LOW_RAM_CONSECUTIVE == 2
    assert HIGH_SWAP_PERCENT == 90.0


# --- pose-video staging (filesystem copy, no mutation of the frozen source) -----------------------


def test_stage_pose_video_copies_without_mutating_the_source(tmp_path: Path) -> None:
    source = tmp_path / "source_pose.mp4"
    source.write_bytes(b"fake-mp4-bytes")
    original_bytes = source.read_bytes()
    command = ["comfy", "--base-directory", str(tmp_path / "comfy_base")]

    filename = harness.stage_pose_video(command, source)

    assert filename == "source_pose.mp4"
    staged = tmp_path / "comfy_base" / "input" / "source_pose.mp4"
    assert staged.read_bytes() == original_bytes
    assert source.read_bytes() == original_bytes  # source untouched


def test_comfy_input_dir_requires_base_directory_flag() -> None:
    with pytest.raises(RuntimeError, match="--base-directory"):
        harness._comfy_input_dir(["comfy", "--listen", "127.0.0.1"])
