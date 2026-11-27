"""PR-VID-MOTION-410 post-pilot Stage C: the revised templates are structurally valid, wider, longer and unexecuted.

The pilot (Stages A and B) showed the 1.2 / 1.3 arms indistinguishable from the baseline, 2 s clips too short to judge timing, and
an unnatural opening when the driver starts in a different pose from the source. The revised suites widen the arm spread, use the
longest legal length and name a start-pose-matched driver. They are templates: the media are placeholders the operator binds, and
nothing is generated here.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.video.video_eval_authoring import EvalSuiteDraft, EvalWorkflowCatalog, validate_draft
from src.video.video_eval_suite import MAX_EVAL_JOBS, SUITE_SCHEMA_V2, load_eval_suite
from tests.video.motion_410_support import controller, fake_prepared_record, make_image, make_video

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "examples"
FILES = {
    "c0": "video_eval_controlled_motion_stage_c0_canary.suite.json",
    "c1": "video_eval_controlled_motion_stage_c1_subject_a.suite.json",
    "c2": "video_eval_controlled_motion_stage_c2_subject_b.suite.json",
    "c3": "video_eval_controlled_motion_stage_c3_start_pose_contrast.suite.json",
}
EXPECTED_JOBS = {"c0": 1, "c1": 12, "c2": 12, "c3": 4}
CATALOG = EvalWorkflowCatalog()
ARM_IDS = [
    "baseline",
    "pose_low",
    "pose_high",
    "reference_low",
    "reference_high",
    "pose_early_stop",
]


def raw(name: str) -> dict:
    return json.loads((EXAMPLES / FILES[name]).read_text(encoding="utf-8"))


def cells(name: str) -> set[tuple[str, str]]:
    data = raw(name)
    return {(case["case_id"], arm["arm_id"]) for case in data["cases"] for arm in data["arms"]}


def materialize(name: str, tmp_path: Path) -> Path:
    """Copy a template next to tiny placeholder media, as an operator would after binding their own files."""

    data = raw(name)
    folder = tmp_path / name
    folder.mkdir(parents=True)
    for index, case in enumerate(data["cases"]):
        image = folder / case["image"]
        if not image.exists():
            make_image(image, color=(20 * index + 10, 80, 120))
        driver = folder / case["motion"]["driving"]["path"]
        if not driver.exists():
            make_video(driver, driver.stem.encode())
    target = folder / FILES[name]
    shutil.copy(EXAMPLES / FILES[name], target)
    return target


def controls(name: str) -> dict[str, dict[str, float]]:
    return {arm["arm_id"]: arm["form"]["operator_controls"] for arm in raw(name)["arms"]}


@pytest.mark.parametrize("name", FILES)
def test_each_template_loads_validates_and_has_the_documented_size(name, tmp_path) -> None:
    path = materialize(name, tmp_path)
    suite = load_eval_suite(path)
    assert suite.schema == SUITE_SCHEMA_V2 and suite.has_motion
    assert suite.job_count == EXPECTED_JOBS[name] <= MAX_EVAL_JOBS
    result = validate_draft(EvalSuiteDraft.open(path), CATALOG)
    assert not result.errors, result.errors


def test_the_arms_are_wide_and_each_changes_exactly_one_declared_control() -> None:
    for name in ("c1", "c2"):
        by_arm = controls(name)
        assert list(by_arm) == ARM_IDS
        baseline = by_arm["baseline"]
        assert baseline == {"pose_strength": 1.0, "reference_image_strength": 1.0}
        for arm_id in ARM_IDS[1:]:
            merged = {"pose_end_percent": 1.0, **by_arm[arm_id]}
            base = {"pose_end_percent": 1.0, **baseline}
            assert len([k for k in merged if merged[k] != base[k]]) == 1, arm_id
        # The pilot's 1.2 / 1.3 arms were indistinguishable: the spread is now at least a factor of two each way.
        assert (
            by_arm["pose_low"]["pose_strength"]
            <= 0.5
            <= 1.0
            <= 2.0
            <= by_arm["pose_high"]["pose_strength"]
        )
        assert by_arm["reference_low"]["reference_image_strength"] <= 0.5
        assert by_arm["reference_high"]["reference_image_strength"] >= 2.0
        assert 0.0 < by_arm["pose_early_stop"]["pose_end_percent"] < 1.0
        shared = {
            arm["arm_id"]: {k: v for k, v in arm["form"].items() if k != "operator_controls"}
            for arm in raw(name)["arms"]
        }
        assert all(form == shared["baseline"] for form in shared.values())
        assert "interpolation" not in shared["baseline"]


def test_the_canary_is_the_baseline_cell_of_the_first_batch() -> None:
    (case,) = raw("c0")["cases"]
    assert [arm["arm_id"] for arm in raw("c0")["arms"]] == ["baseline"]
    assert cells("c0") <= cells("c1")
    first = next(c for c in raw("c1")["cases"] if c["case_id"] == case["case_id"])
    assert first == case  # identical case content: the canary is a strict subset of C1


def test_frame_count_is_the_longest_legal_length_in_every_suite() -> None:
    for name in FILES:
        counts = {arm["form"]["frame_count"] for arm in raw(name)["arms"]}
        assert counts == {81}  # the previous pilot used 49 (2 s); 81 is the longest legal length
        assert (81 - 1) % 4 == 0
    assert {raw(name)["seed"] for name in FILES} == {410}


def test_the_workflow_identity_is_the_verified_offerable_animate_2_version() -> None:
    form = raw("c1")["arms"][0]["form"]
    assert (form["workflow_id"], form["workflow_version"]) == ("wan_animate2_drive_i2v_v1", "1.2.0")
    spec = CATALOG.get(form["workflow_id"], form["workflow_version"])
    assert spec.governance_state == "experimental" and form["experimental_opt_in"] is True
    assert "pose_video" in spec.declared_input_names
    # PR-VID-ANIMATE-CK-WARM: 1.3.0 is now the newest offerable version; the campaign deliberately keeps pinning 1.2.0, the
    # no-CK baseline that every recorded pilot, stage and alignment result was produced on.
    assert CATALOG.inherited_version(form["workflow_id"]) == "1.3.0"


def test_the_two_subject_suites_differ_only_by_the_subject_and_share_both_drivers() -> None:
    a, b = raw("c1"), raw("c2")
    assert a["arms"] == b["arms"]
    assert len(a["cases"]) == len(b["cases"]) == 2
    for ca, cb in zip(a["cases"], b["cases"], strict=True):
        assert ca["motion"] == cb["motion"]  # one driver and one motion contract per class
        assert ca["image"] != cb["image"] and ca["prompt"] != cb["prompt"]
        assert ca["case_id"].endswith("_a") and cb["case_id"].endswith("_b")
    assert {c["motion"]["category"] for c in a["cases"]} == {"head_turn", "hand_wave"}


def test_the_head_turn_driver_starts_in_the_sources_pose() -> None:
    for name in ("c0", "c1", "c2"):
        for case in raw(name)["cases"]:
            motion = case["motion"]
            notes = motion["annotations"]
            assert "source faces the camera" in notes["compatibility"]
            assert "facing the camera" in notes["start_pose"]
            if motion["category"] == "head_turn":
                assert motion["driving"]["path"] == "motion/head_turn_front_to_profile.mp4"
                assert motion["action"].lower().startswith("starts facing the camera")
                assert "not already turned far over a shoulder" in motion["expected_outcome"]
                assert motion["phases"][0] == "facing the camera"


def test_each_case_states_a_specific_observable_outcome() -> None:
    for name in FILES:
        for case in raw(name)["cases"]:
            motion = case["motion"]
            assert len(motion["expected_outcome"]) > 60 and len(motion["action"]) > 20
            assert motion["motion_prompt"] and motion["phases"] and motion["direction"]
    wave = next(c for c in raw("c1")["cases"] if c["motion"]["category"] == "hand_wave")
    assert "extra arm" in wave["motion"]["expected_outcome"]  # the one artifact seen in the pilot


def test_templates_carry_no_media_no_absolute_paths_and_claim_no_execution() -> None:
    for name in FILES:
        data = raw(name)
        text = (EXAMPLES / FILES[name]).read_text(encoding="utf-8")
        for case in data["cases"]:
            for path in (case["image"], case["motion"]["driving"]["path"]):
                assert not Path(path).is_absolute() and ":" not in path and ".." not in path
        assert "Unexecuted template" in data["description"]
        assert "qualified" not in text.lower().replace("not qualified", "")
    media = [
        p
        for p in EXAMPLES.iterdir()
        if p.suffix.lower() in {".png", ".jpg", ".mp4", ".webm", ".mov", ".mkv"}
    ]
    assert media == []


@pytest.mark.parametrize("name", FILES)
def test_every_stage_compiles_through_the_production_builders_as_one_all_or_none_run(
    name, tmp_path
) -> None:
    path = materialize(name, tmp_path)
    ctl, service = controller(tmp_path, preparer=fake_prepared_record)
    plan = ctl.preview_eval_run(path)
    assert plan.eligible, plan.summary()
    assert len(plan.jobs) == EXPECTED_JOBS[name]
    expected = {arm_id: controls(name)[arm_id] for arm_id in controls(name)}
    for job in plan.jobs:
        assert job.seed == 410 and job.motion is not None and job.motion.prepared
        assert job.frame_count == 81 and not job.motion.interpolation
        assert job.motion.workflow_version == "1.2.0"
        for key, value in expected[job.arm_id].items():
            assert job.motion.controls[key] == value
    if name in ("c1", "c2"):
        stopped = {
            j.motion.controls["pose_end_percent"]
            for j in plan.jobs
            if j.arm_id == "pose_early_stop"
        }
        assert stopped == {0.6}
        assert {
            j.motion.controls["pose_end_percent"]
            for j in plan.jobs
            if j.arm_id != "pose_early_stop"
        } == {1.0}
    # One shared prepared derivative per motion and length, not one per job.
    assert len({job.motion.driver_effective_sha256 for job in plan.jobs}) == len(
        {job.motion.driver_original_sha256 for job in plan.jobs}
    )
    ctl.submit_eval_run(plan)
    assert len(service.calls) == 1 and len(service.calls[0]) == EXPECTED_JOBS[name]


def test_the_contrast_suite_pairs_matched_and_unmatched_drivers_on_each_subject() -> None:
    data = raw("c3")
    assert [arm["arm_id"] for arm in data["arms"]] == ["baseline"]
    cases = {case["case_id"]: case for case in data["cases"]}
    assert set(cases) == {
        "head_turn_front_to_profile_a",
        "head_turn_profile_start_a",
        "head_turn_front_to_profile_b",
        "head_turn_profile_start_b",
    }
    for subject in ("a", "b"):
        matched = cases[f"head_turn_front_to_profile_{subject}"]
        unmatched = cases[f"head_turn_profile_start_{subject}"]
        assert (
            matched["image"] == unmatched["image"]
        )  # the same source, so the driver's start pose is the only variable
        assert matched["prompt"] == unmatched["prompt"]
        assert matched["motion"]["category"] == unmatched["motion"]["category"] == "head_turn"
        assert matched["motion"]["driving"]["path"] == "motion/head_turn_front_to_profile.mp4"
        assert unmatched["motion"]["driving"]["path"] == "motion/head_turn_profile_start.mp4"
        assert "NOT matched" in " ".join(unmatched["motion"]["annotations"]["compatibility"])
        assert "NOT matched" not in " ".join(matched["motion"]["annotations"]["compatibility"])
        assert "deliberately unmatched" in unmatched["motion"]["annotations"]["start_pose"]
    # The matched cells are exactly the head-turn cells of the C1 / C2 sensitivity suites.
    assert cases["head_turn_front_to_profile_a"] == next(
        c for c in raw("c1")["cases"] if c["case_id"] == "head_turn_front_to_profile_a"
    )
    assert cases["head_turn_front_to_profile_b"] == next(
        c for c in raw("c2")["cases"] if c["case_id"] == "head_turn_front_to_profile_b"
    )
