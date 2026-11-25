"""PR-VID-MOTION-410 Workstream J: the initial controlled-motion campaign template is structurally valid and unexecuted.

The example suites are templates: their images and driving videos are placeholders the operator binds. Here the
placeholders are materialized as tiny local files so the real parser, the authoring validator and the production builders
can prove the structure. Nothing is generated and no media is committed.
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
    "short": "video_eval_controlled_motion_short.suite.json",
    "long": "video_eval_controlled_motion_long.suite.json",
    "a": "video_eval_controlled_motion_stage_a.suite.json",
    "b": "video_eval_controlled_motion_stage_b.suite.json",
    "c_short": "video_eval_controlled_motion_stage_c_short.suite.json",
}
EXPECTED_JOBS = {"short": 18, "long": 18, "a": 3, "b": 12, "c_short": 6}
CATEGORIES = {"head_turn", "hand_wave", "raise_arms", "sit_down", "turn_around", "walk_forward"}
CATALOG = EvalWorkflowCatalog()


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
        make_image(folder / case["image"], color=(20 * index + 10, 80, 120))
        make_video(folder / case["motion"]["driving"]["path"], case["motion"]["category"].encode())
    target = folder / FILES[name]
    shutil.copy(EXAMPLES / FILES[name], target)
    return target


@pytest.mark.parametrize("name", FILES)
def test_each_template_loads_validates_and_has_the_documented_size(name, tmp_path) -> None:
    path = materialize(name, tmp_path)
    suite = load_eval_suite(path)
    assert suite.schema == SUITE_SCHEMA_V2 and suite.has_motion
    assert suite.job_count == EXPECTED_JOBS[name] <= MAX_EVAL_JOBS
    result = validate_draft(EvalSuiteDraft.open(path), CATALOG)
    assert not result.errors, result.errors


def test_the_full_design_is_36_jobs_across_six_motion_classes_two_subjects_and_three_arms() -> None:
    full = raw("short")["cases"] + raw("long")["cases"]
    assert len(full) * 3 == 36 == cells("short").__len__() + cells("long").__len__()
    assert {case["motion"]["category"] for case in full} == CATEGORIES
    for category in CATEGORIES:
        members = [case for case in full if case["motion"]["category"] == category]
        assert len(members) == 2  # two visually compatible source images per class
        assert len({case["image"] for case in members}) == 2
        assert (
            len({case["motion"]["driving"]["path"] for case in members}) == 1
        )  # one clean driver per class


def test_the_three_arms_differ_from_the_baseline_by_exactly_one_declared_control() -> None:
    for name in FILES:
        arms = {arm["arm_id"]: arm["form"] for arm in raw(name)["arms"]}
        assert list(arms) == ["baseline", "motion_emphasis", "reference_emphasis"]
        controls = {arm: form["operator_controls"] for arm, form in arms.items()}
        assert controls["baseline"] == {"pose_strength": 1.0, "reference_image_strength": 1.0}
        assert controls["motion_emphasis"] == {
            "pose_strength": 1.2,
            "reference_image_strength": 1.0,
        }
        assert controls["reference_emphasis"] == {
            "pose_strength": 1.0,
            "reference_image_strength": 1.3,
        }
        for arm in ("motion_emphasis", "reference_emphasis"):
            changed = [k for k in controls[arm] if controls[arm][k] != controls["baseline"][k]]
            assert len(changed) == 1
        # Everything else is shared; the pose conditioning interval keeps its default full range and no smoothing is set.
        shared = {
            key: {k: v for k, v in form.items() if k != "operator_controls"}
            for key, form in arms.items()
        }
        assert shared["baseline"] == shared["motion_emphasis"] == shared["reference_emphasis"]
        assert "interpolation" not in shared["baseline"]
        assert not {"pose_start_percent", "pose_end_percent"} & set(controls["baseline"])


def test_the_workflow_identity_is_the_verified_offerable_animate_2_version() -> None:
    form = raw("short")["arms"][0]["form"]
    assert (form["workflow_id"], form["workflow_version"]) == ("wan_animate2_drive_i2v_v1", "1.2.0")
    spec = CATALOG.get(form["workflow_id"], form["workflow_version"])
    assert spec.governance_state == "experimental" and form["experimental_opt_in"] is True
    assert "pose_video" in spec.declared_input_names
    # PR-VID-ANIMATE-CK-WARM: 1.3.0 is now the newest offerable version; the campaign deliberately keeps pinning 1.2.0, the
    # no-CK baseline that every recorded pilot, stage and alignment result was produced on.
    assert (
        CATALOG.inherited_version(form["workflow_id"]) == "1.3.0"
    )  # the newest offerable version of that id


def test_frame_counts_are_legal_and_constant_within_each_suite() -> None:
    for name in FILES:
        counts = {arm["form"]["frame_count"] for arm in raw(name)["arms"]}
        assert len(counts) == 1
        (count,) = counts
        assert 17 <= count <= 81 and (count - 1) % 4 == 0
    assert raw("short")["arms"][0]["form"]["frame_count"] == 49
    assert raw("long")["arms"][0]["form"]["frame_count"] == 81
    assert len({raw(name)["seed"] for name in FILES}) == 1 and isinstance(raw("short")["seed"], int)


def test_the_stages_nest_and_cover_the_design_without_a_new_campaign_authority() -> None:
    full = cells("short") | cells("long")
    assert len(full) == 36
    a, b, c_short, long = cells("a"), cells("b"), cells("c_short"), cells("long")
    assert (
        len(a) == 3 and len(b) == 12 and a <= b
    )  # the pilot's cells are part of the diagnostic sample
    stage_c = c_short | long
    assert len(stage_c) == 24 and not (
        stage_c & b
    )  # Stage C is the remainder: no accepted cell is rerun
    assert b | stage_c == full
    # Stage cells are identical to the full design's: same case content, so exact-identity evidence can be reused.
    full_cases = {c["case_id"]: c for c in raw("short")["cases"] + raw("long")["cases"]}
    for name in ("a", "b", "c_short"):
        for case in raw(name)["cases"]:
            assert case == full_cases[case["case_id"]]
    assert set(FILES) == set(EXPECTED_JOBS)


def test_each_case_states_a_specific_observable_outcome() -> None:
    for name in FILES:
        for case in raw(name)["cases"]:
            motion = case["motion"]
            assert len(motion["expected_outcome"]) > 60 and len(motion["action"]) > 20
            assert motion["motion_prompt"] and motion["phases"] and motion["direction"]
    walk = next(c for c in raw("long")["cases"] if c["motion"]["category"] == "walk_forward")
    text = walk["motion"]["expected_outcome"]
    assert "second walking figure" in text and "background motion" in text


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
    for job in plan.jobs:
        assert job.seed == 410 and job.motion is not None and job.motion.prepared
        assert job.motion.workflow_version == "1.2.0" and not job.motion.interpolation
        assert job.motion.controls["pose_strength"] in (1.0, 1.2)
    by_arm = {}
    for job in plan.jobs:
        by_arm.setdefault(job.arm_id, set()).add(
            (job.motion.controls["pose_strength"], job.motion.controls["reference_image_strength"])
        )
    assert by_arm == {
        "baseline": {(1.0, 1.0)},
        "motion_emphasis": {(1.2, 1.0)},
        "reference_emphasis": {(1.0, 1.3)},
    }
    # One shared prepared derivative per motion and length, not one per job.
    assert len({job.motion.driver_effective_sha256 for job in plan.jobs}) == len(
        {job.motion.driver_original_sha256 for job in plan.jobs}
    )
    ctl.submit_eval_run(plan)
    assert len(service.calls) == 1 and len(service.calls[0]) == EXPECTED_JOBS[name]
