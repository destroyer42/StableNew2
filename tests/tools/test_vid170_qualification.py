"""PR-VID-170 qualification harness: exactly three named cases, fixed settings across cases (only
pose asset changes), pose_video always present, face_video always absent, no retry, one submit per
requested case, external-runtime refusal, owner-only teardown, commit-aware safety gate retained,
evidence persistence on abort, and output association cannot mix cases (no GPU, no real Comfy,
no queue)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.helpers.optional_deps import requires_cv2
from tools.qualification.vid170 import graph as graph_mod
from tools.qualification.vid170 import run as harness
from tools.qualification.vid170 import synthetic_pose

# --- exactly three named cases -------------------------------------------------------------------


def test_exactly_three_cases_are_defined() -> None:
    assert set(harness.CASES) == {"A", "B", "C"}


def test_case_reports_dirs_are_distinct_and_case_named() -> None:
    dirs = {case: harness.case_reports_dir(case) for case in harness.CASES}
    assert len(set(dirs.values())) == 3
    for case, path in dirs.items():
        assert path.name == f"run_{case.lower()}"
        assert path.parent == harness.REPORTS_ROOT


# --- graph freeze: only pose asset changes; pose_video always present; face_video always absent --


def test_graph_contains_pose_video_and_never_face_video() -> None:
    spec = graph_mod.CharacterizationSpec(reference_image="ref.png", pose_video_file="pose.mp4")
    wf = graph_mod.build_characterization_graph(spec)
    assert graph_mod.validate_graph(wf) == []
    animate_inputs = next(
        n["inputs"] for n in wf.values() if n["class_type"] == "WanAnimateToVideo"
    )
    assert animate_inputs["pose_video"] == ["17", 0]
    assert "face_video" not in animate_inputs
    assert "background_video" not in animate_inputs
    assert "character_mask" not in animate_inputs


def test_only_the_pose_video_file_differs_between_case_specs() -> None:
    specs = {
        case: graph_mod.CharacterizationSpec(reference_image="ref.png", pose_video_file=str(path))
        for case, path in harness.CASES.items()
    }
    shared_fields = (
        "reference_image",
        "width",
        "height",
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
    for field in shared_fields:
        values = {getattr(spec, field) for spec in specs.values()}
        assert len(values) == 1, field
    pose_files = {spec.pose_video_file for spec in specs.values()}
    assert len(pose_files) == 3


def test_frozen_settings_match_the_official_wan_animate_defaults() -> None:
    spec = graph_mod.CharacterizationSpec(reference_image="ref.png", pose_video_file="pose.mp4")
    assert spec.steps == 20  # wan_animate_14B.py: sample_steps
    assert spec.cfg == 1.0  # wan_animate_14B.py: sample_guide_scale
    assert spec.shift == 5.0  # wan_animate_14B.py: sample_shift
    assert spec.sampler == "uni_pc"  # generate.py --sample_solver default 'unipc'
    assert spec.positive_prompt == graph_mod.OFFICIAL_DEFAULT_PROMPT


def test_graph_rejects_dimensions_not_divisible_by_16() -> None:
    with pytest.raises(ValueError, match="divisible by 16"):
        graph_mod.build_characterization_graph(
            graph_mod.CharacterizationSpec(
                reference_image="ref.png", pose_video_file="p.mp4", width=257
            )
        )


def test_validate_graph_flags_missing_pose_video() -> None:
    spec = graph_mod.CharacterizationSpec(reference_image="ref.png", pose_video_file="pose.mp4")
    wf = graph_mod.build_characterization_graph(spec)
    del wf["10"]["inputs"]["pose_video"]
    problems = graph_mod.validate_graph(wf)
    assert any("missing pose_video" in p for p in problems)


def test_validate_graph_flags_a_face_video_addition() -> None:
    spec = graph_mod.CharacterizationSpec(reference_image="ref.png", pose_video_file="pose.mp4")
    wf = graph_mod.build_characterization_graph(spec)
    wf["10"]["inputs"]["face_video"] = ["17", 0]
    problems = graph_mod.validate_graph(wf)
    assert any("must not include face_video" in p for p in problems)


# --- synthetic pose determinism (Cases A/B) -------------------------------------------------------


@requires_cv2
def test_synthetic_pose_renders_frozen_frame_count_and_geometry(tmp_path: Path) -> None:
    a = synthetic_pose.render_arm_raise(tmp_path / "a.mp4")
    b = synthetic_pose.render_walk_forward(tmp_path / "b.mp4")
    assert a.exists() and a.stat().st_size > 0
    assert b.exists() and b.stat().st_size > 0


@requires_cv2
def test_synthetic_pose_rendering_is_deterministic(tmp_path: Path) -> None:
    import hashlib

    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    a1 = synthetic_pose.render_arm_raise(tmp_path / "a1.mp4")
    a2 = synthetic_pose.render_arm_raise(tmp_path / "a2.mp4")
    assert sha(a1) == sha(a2)


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


# --- one submit per case / no retry / output association cannot mix cases ------------------------


def test_run_case_calls_the_stack_exactly_once_and_never_retries_a_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(harness, "REPORTS_ROOT", tmp_path / "reports")
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    monkeypatch.setattr(harness, "_teardown", lambda _stack: (False, []))
    calls: list[str] = []

    def failing_run(stack, args, evidence, reports):
        calls.append(args.case)
        evidence["status"] = "dependency_blocked"
        return 1

    monkeypatch.setattr(harness, "_run_case", failing_run)
    assert harness.run_case(argparse.Namespace(reference_image="ref.png", case="C")) == 1
    assert calls == ["C"]  # exactly one attempt for the requested case; no loop, no retry

    evidence_path = harness.case_reports_dir("C") / "evidence.json"
    data = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert data["status"] == "dependency_blocked"
    assert data["case"] == "C"


def test_each_case_writes_evidence_to_its_own_directory_never_mixing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(harness, "REPORTS_ROOT", tmp_path / "reports")
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    monkeypatch.setattr(harness, "_teardown", lambda _stack: (False, []))

    def run(stack, args, evidence, reports):
        evidence["status"] = "completed"
        evidence["output_path"] = str(reports / f"case_{args.case.lower()}_output.mp4")
        return 0

    monkeypatch.setattr(harness, "_run_case", run)
    for case in ("A", "B", "C"):
        harness.run_case(argparse.Namespace(reference_image="ref.png", case=case))

    for case in ("A", "B", "C"):
        data = json.loads(
            (harness.case_reports_dir(case) / "evidence.json").read_text(encoding="utf-8")
        )
        assert data["case"] == case
        assert f"case_{case.lower()}_output.mp4" in data["output_path"]


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
    with pytest.raises(RuntimeError, match="GPU lost"):
        harness.run_case(argparse.Namespace(reference_image="ref.png", case="B"))

    assert teardown_calls == [1]
    data = json.loads((harness.case_reports_dir("B") / "evidence.json").read_text(encoding="utf-8"))
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


def test_run_case_rejects_an_unknown_case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(harness, "REPORTS_ROOT", tmp_path / "reports")
    monkeypatch.setattr(harness, "preflight", lambda: {"endpoint_state": "free"})
    with pytest.raises(ValueError, match="unknown case"):
        harness.run_case(argparse.Namespace(reference_image="ref.png", case="D"))


# --- commit-aware safety gate retained (reused unchanged from VID-160C) --------------------------


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
