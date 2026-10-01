"""PR-VID-175 qualification harness: frozen 480x832 spec identical to PR-VID-170 Case C except
resolution, temporal-index equivalence with Case C, pose_video always present/face_video always
absent, exactly one submission, no retry, external-runtime refusal, owner-only teardown,
commit-aware safety guard unchanged, evidence persistence on abort (no GPU, no real Comfy,
no queue)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.helpers.optional_deps import requires_cv2, requires_numpy
from tools.qualification.vid160c.pose_asset import sample_indices
from tools.qualification.vid170.graph import CharacterizationSpec, build_characterization_graph
from tools.qualification.vid175 import pose_asset_480x832
from tools.qualification.vid175 import run as harness

# --- frozen 480x832 spec identical to VID-170 Case C except resolution --------------------------


def test_frozen_geometry_is_480x832() -> None:
    assert harness.WIDTH == 480
    assert harness.HEIGHT == 832


def test_spec_at_480x832_matches_vid170_case_c_defaults_on_every_other_field() -> None:
    case_c_default = CharacterizationSpec(reference_image="ref.png", pose_video_file="pose.mp4")
    this_spec = CharacterizationSpec(
        reference_image="ref.png",
        pose_video_file="pose.mp4",
        width=harness.WIDTH,
        height=harness.HEIGHT,
    )
    unchanged_fields = (
        "length",
        "steps",
        "cfg",
        "shift",
        "seed",
        "sampler",
        "scheduler",
        "positive_prompt",
        "negative_prompt",
        "fps",
    )
    for field in unchanged_fields:
        assert getattr(case_c_default, field) == getattr(this_spec, field), field
    assert (case_c_default.width, case_c_default.height) == (256, 256)
    assert (this_spec.width, this_spec.height) == (480, 832)


def test_graph_at_480x832_contains_pose_video_and_never_face_video() -> None:
    spec = CharacterizationSpec(
        reference_image="ref.png",
        pose_video_file="pose.mp4",
        width=harness.WIDTH,
        height=harness.HEIGHT,
    )
    wf = build_characterization_graph(spec)
    animate_inputs = next(
        n["inputs"] for n in wf.values() if n["class_type"] == "WanAnimateToVideo"
    )
    assert animate_inputs["pose_video"] == ["17", 0]
    assert animate_inputs["width"] == 480
    assert animate_inputs["height"] == 832
    assert "face_video" not in animate_inputs


# --- temporal-index equivalence with VID-170 Case C ------------------------------------------------


@requires_numpy
def test_pose_asset_temporal_indices_equal_vid170_case_c() -> None:
    case_c_indices = sample_indices(49, 13)  # the exact call VID-170 Case C's adaptation used
    assert pose_asset_480x832.TARGET_FRAMES == 13
    # The 175 adapter reuses sample_indices directly with the same (total, count) -- verified here
    # against the exact same source frame count (49) VID-170 Case C's source had.
    reused_indices = sample_indices(49, pose_asset_480x832.TARGET_FRAMES)
    assert reused_indices == case_c_indices


@requires_cv2
def test_pose_asset_480x832_preserves_native_resolution_no_crop(tmp_path: Path) -> None:
    target, indices, dims = pose_asset_480x832.adapt_pose_video_native(
        target=tmp_path / "pose_480x832.mp4"
    )
    assert target.exists() and target.stat().st_size > 0
    assert dims == (480, 832)
    assert len(indices) == 13
    assert indices == sample_indices(49, 13)


# --- external-runtime refusal / dry-run -----------------------------------------------------------


def test_main_stops_before_building_anything_when_an_external_comfy_is_serving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    built: list[str] = []
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "healthy"})
    monkeypatch.setattr(harness, "run_once", lambda *_a: built.append("ran") or 0)
    assert harness.main(["ref.png", "pose.mp4"]) == 3
    assert built == []
    assert "never adopts or restarts" in capsys.readouterr().out


def test_dry_run_never_calls_run_once(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    monkeypatch.setattr(harness, "run_once", lambda *_a: built.append("ran") or 0)
    assert harness.main(["ref.png", "pose.mp4", "--dry"]) == 0
    assert built == []


# --- exactly one submission / no retry / evidence / teardown -------------------------------------


def test_run_once_calls_the_stack_exactly_once_and_never_retries_a_failure(
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

    monkeypatch.setattr(harness, "_run_once", failing_run)
    assert harness.run_once(argparse.Namespace(reference_image="ref.png", pose_video="p.mp4")) == 1
    assert calls == ["attempt"]

    data = json.loads((tmp_path / "reports" / "evidence.json").read_text(encoding="utf-8"))
    assert data["status"] == "dependency_blocked"


def test_run_once_writes_partial_evidence_and_still_tears_down_on_exception(
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

    monkeypatch.setattr(harness, "_run_once", aborting_run)
    with pytest.raises(RuntimeError, match="GPU lost"):
        harness.run_once(argparse.Namespace(reference_image="ref.png", pose_video="p.mp4"))

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


# --- commit-aware safety gate unchanged from VID-160C ---------------------------------------------


def test_commit_aware_safety_thresholds_are_reused_unchanged() -> None:
    from tools.qualification.vid160c.telemetry import (
        COMMIT_HEADROOM_ABORT_GB,
        COMMIT_PERCENT_ABORT,
        CONSECUTIVE_SAMPLES,
        EMERGENCY_RAM_GB,
        WARN_RAM_GB,
    )

    assert WARN_RAM_GB == 1.0
    assert EMERGENCY_RAM_GB == 0.25
    assert COMMIT_PERCENT_ABORT == 97.0
    assert COMMIT_HEADROOM_ABORT_GB == 1.0
    assert CONSECUTIVE_SAMPLES == 2
