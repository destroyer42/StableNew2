"""PR-VID-180 qualification harness: frozen 480x832 spec identical to PR-VID-170/175 defaults,
only A and B are runnable (no Case C submission path), native-resolution synthetic pose controls
for A/B preserve VID-170's normalized motion semantics (arm-angle progression, gait phase,
root-translation fraction of width) at 480x832, deterministic rendering, pose_video
present/face_video absent, exactly one submission, no retry, external-runtime refusal,
owner-only teardown, commit-aware safety guard unchanged, evidence persistence on abort (no GPU,
no real Comfy, no queue)."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.helpers.optional_deps import requires_cv2
from tools.qualification.vid170.graph import CharacterizationSpec, build_characterization_graph
from tools.qualification.vid180 import native_pose
from tools.qualification.vid180 import run as harness

# --- only A and B are runnable; no Case C submission path ----------------------------------------


def test_only_a_and_b_are_runnable_no_case_c_submission_path() -> None:
    assert set(harness.CASES) == {"A", "B"}
    assert "C" not in harness.CASES


def test_case_reports_dirs_are_distinct_and_never_mix_output() -> None:
    assert harness.case_reports_dir("A") == Path("reports/vid180/run_a")
    assert harness.case_reports_dir("B") == Path("reports/vid180/run_b")
    assert harness.case_reports_dir("A") != harness.case_reports_dir("B")


# --- frozen 480x832 spec identical to VID-170/175 defaults ---------------------------------------


def test_frozen_geometry_is_480x832() -> None:
    assert harness.WIDTH == 480
    assert harness.HEIGHT == 832


def test_spec_at_480x832_matches_frozen_defaults_on_every_other_field() -> None:
    default = CharacterizationSpec(reference_image="ref.png", pose_video_file="pose.mp4")
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
        assert getattr(default, field) == getattr(this_spec, field), field
    assert (this_spec.width, this_spec.height) == (480, 832)
    assert this_spec.length == 13
    assert this_spec.fps == 8.0
    assert this_spec.steps == 20
    assert this_spec.cfg == 1.0
    assert this_spec.shift == 5.0
    assert this_spec.sampler == "uni_pc"
    assert this_spec.scheduler == "simple"
    assert this_spec.seed == 1733123036


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


def test_case_a_and_b_differ_only_by_pose_asset() -> None:
    a_spec = CharacterizationSpec(
        reference_image="ref.png",
        pose_video_file="a.mp4",
        width=harness.WIDTH,
        height=harness.HEIGHT,
    )
    b_spec = CharacterizationSpec(
        reference_image="ref.png",
        pose_video_file="b.mp4",
        width=harness.WIDTH,
        height=harness.HEIGHT,
    )
    a_graph = build_characterization_graph(a_spec)
    b_graph = build_characterization_graph(b_spec)
    for node_id in a_graph:
        a_inputs, b_inputs = dict(a_graph[node_id]["inputs"]), dict(b_graph[node_id]["inputs"])
        a_inputs.pop("file", None)
        b_inputs.pop("file", None)
        assert a_inputs == b_inputs, node_id
    assert a_graph["16"]["inputs"]["file"] == "a.mp4"
    assert b_graph["16"]["inputs"]["file"] == "b.mp4"


# --- native-resolution motion preserves VID-170's normalized semantics ---------------------------


def _vid170_case_a_angle(t: int, frames: int = 13) -> float:
    """Transcribed, independent recomputation of VID-170 Case A's angle formula (the render
    function itself has no standalone angle helper to import)."""

    raise_fraction = math.sin(math.pi * t / (frames - 1))
    return math.pi * raise_fraction


def _vid170_case_b_phase(t: int, frames: int = 13, cycles: float = 2.0) -> float:
    progress = t / (frames - 1)
    return 2 * math.pi * cycles * progress


def _vid170_case_b_leg_angle(phase: float, *, opposite: bool = False) -> float:
    swing = math.radians(28)
    return swing * math.sin(phase + (math.pi if opposite else 0.0))


def _vid170_case_b_hip_x_fraction(t: int, frames: int = 13) -> float:
    progress = t / (frames - 1)
    return 0.32 + (0.68 - 0.32) * progress


def test_native_case_a_arm_angle_matches_vid170_case_a_every_frame() -> None:
    for t in range(native_pose.FRAMES):
        assert native_pose.arm_raise_angle(t) == pytest.approx(_vid170_case_a_angle(t))


def test_native_case_b_gait_phase_and_leg_swing_match_vid170_case_b_every_frame() -> None:
    for t in range(native_pose.FRAMES):
        phase = native_pose.gait_phase(t)
        assert phase == pytest.approx(_vid170_case_b_phase(t))
        assert native_pose.leg_swing_angle(phase) == pytest.approx(_vid170_case_b_leg_angle(phase))
        assert native_pose.leg_swing_angle(phase, opposite=True) == pytest.approx(
            _vid170_case_b_leg_angle(phase, opposite=True)
        )


def test_native_case_b_root_translation_fraction_matches_vid170_case_b_every_frame() -> None:
    for t in range(native_pose.FRAMES):
        assert native_pose.hip_x_fraction(t) == pytest.approx(_vid170_case_b_hip_x_fraction(t))


def test_native_pose_frame_count_and_fps_match_vid170() -> None:
    assert native_pose.FRAMES == 13
    assert native_pose.FPS == 8.0


# --- deterministic native-resolution rendering ----------------------------------------------------


@requires_cv2
def test_render_arm_raise_native_is_deterministic_and_480x832(tmp_path: Path) -> None:
    first = native_pose.render_arm_raise_native(tmp_path / "a1.mp4")
    second = native_pose.render_arm_raise_native(tmp_path / "a2.mp4")
    assert native_pose.sha256_of(first) == native_pose.sha256_of(second)
    assert first.exists() and first.stat().st_size > 0


@requires_cv2
def test_render_walk_forward_native_is_deterministic_and_480x832(tmp_path: Path) -> None:
    first = native_pose.render_walk_forward_native(tmp_path / "b1.mp4")
    second = native_pose.render_walk_forward_native(tmp_path / "b2.mp4")
    assert native_pose.sha256_of(first) == native_pose.sha256_of(second)
    assert first.exists() and first.stat().st_size > 0


def test_render_functions_use_480x832_by_default() -> None:
    assert native_pose.WIDTH == 480
    assert native_pose.HEIGHT == 832


# --- external-runtime refusal / dry-run -----------------------------------------------------------


def test_main_stops_before_building_anything_when_an_external_comfy_is_serving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    built: list[str] = []
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "healthy"})
    monkeypatch.setattr(harness, "run_case", lambda *_a: built.append("ran") or 0)
    assert harness.main(["ref.png", "--case", "A"]) == 3
    assert built == []
    assert "never adopts or restarts" in capsys.readouterr().out


def test_dry_run_never_calls_run_case(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    monkeypatch.setattr(harness, "run_case", lambda *_a: built.append("ran") or 0)
    assert harness.main(["ref.png", "--case", "B", "--dry"]) == 0
    assert built == []


def test_main_rejects_case_c() -> None:
    with pytest.raises(SystemExit):
        harness.main(["ref.png", "--case", "C"])


# --- exactly one submission / no retry / evidence / teardown -------------------------------------


def test_run_case_calls_the_stack_exactly_once_and_never_retries_a_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(harness, "REPORTS_ROOT", tmp_path / "reports")
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    monkeypatch.setattr(harness, "_teardown", lambda _stack: (False, []))
    calls: list[str] = []

    def failing_run(stack, args, evidence, reports):
        calls.append("attempt")
        evidence["status"] = "dependency_blocked"
        return 1

    monkeypatch.setattr(harness, "_run_case", failing_run)
    args = argparse.Namespace(reference_image="ref.png", case="A")
    assert harness.run_case(args) == 1
    assert calls == ["attempt"]

    data = json.loads(
        (tmp_path / "reports" / "run_a" / "evidence.json").read_text(encoding="utf-8")
    )
    assert data["status"] == "dependency_blocked"


def test_run_case_writes_partial_evidence_and_still_tears_down_on_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(harness, "REPORTS_ROOT", tmp_path / "reports")
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    teardown_calls: list[int] = []

    def teardown(_stack):
        teardown_calls.append(1)
        return False, []

    monkeypatch.setattr(harness, "_teardown", teardown)

    def aborting_run(stack, args, evidence, reports):
        evidence["prompt_id"] = "in-flight"
        raise RuntimeError("GPU lost")

    monkeypatch.setattr(harness, "_run_case", aborting_run)
    args = argparse.Namespace(reference_image="ref.png", case="B")
    with pytest.raises(RuntimeError, match="GPU lost"):
        harness.run_case(args)

    assert teardown_calls == [1]
    data = json.loads(
        (tmp_path / "reports" / "run_b" / "evidence.json").read_text(encoding="utf-8")
    )
    assert data["prompt_id"] == "in-flight"
    assert "GPU lost" in data["aborted"]


def test_run_case_rejects_unknown_case_without_submitting(tmp_path: Path) -> None:
    stack = harness._Stack()
    evidence: dict = {}
    with pytest.raises(ValueError, match="unknown case"):
        harness._run_case(
            stack, argparse.Namespace(reference_image="ref.png", case="C"), evidence, tmp_path
        )


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
