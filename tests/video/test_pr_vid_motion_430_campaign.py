"""PR-VID-MOTION-430 Workstream H: the staged comparative campaign templates are structurally valid, bounded and unexecuted.

The example suites are templates whose images and driving videos are placeholders the operator binds.  Here they are
materialized as tiny local files so the real parser, the authoring validator and the production builders can prove the
structure through both engines.  Nothing is generated, no media is committed and no runtime is touched.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.video.video_eval_authoring import EvalSuiteDraft, EvalWorkflowCatalog, validate_draft
from src.video.video_eval_suite import MAX_EVAL_JOBS, SUITE_SCHEMA_V2, load_eval_suite
from src.video.workflow_conditioning import registered_contracts, shared_envelope
from tests.video.motion_410_support import controller, fake_prepared_record, make_image, make_video

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "examples"
FILES = {
    "stage1": "video_eval_conditioning_stage1_engine_pilot.suite.json",
    "stage2": "video_eval_conditioning_stage2_representation_screen.suite.json",
    "stage3": "video_eval_conditioning_stage3_cross_subject.suite.json",
    "stage4": "video_eval_conditioning_stage4_repeatability.suite.json",
}
EXPECTED_JOBS = {"stage1": 2, "stage2": 12, "stage3": 12, "stage4": 4}
CATALOG = EvalWorkflowCatalog()
ANIMATE = ("wan_animate2_drive_i2v_v1", "1.2.0")
FUN = ("wan22_fun_control_5b_canny_i2v_v1", "1.1.0")


def raw(name: str) -> dict:
    return json.loads((EXAMPLES / FILES[name]).read_text(encoding="utf-8"))


def materialize(name: str, tmp_path: Path) -> Path:
    data = raw(name)
    folder = tmp_path / name
    folder.mkdir(parents=True)
    for case in data["cases"]:
        image = folder / case["image"]
        if not image.exists():
            make_image(image, color=(10 + sum(image.name.encode()) % 200, 80, 120))
        driver = folder / case["motion"]["driving"]["path"]
        if not driver.exists():
            make_video(driver, case["motion"]["driving"]["path"].encode())
    target = folder / FILES[name]
    shutil.copy(EXAMPLES / FILES[name], target)
    return target


@pytest.mark.parametrize("name", FILES)
def test_each_stage_loads_validates_and_has_the_documented_size(name, tmp_path):
    path = materialize(name, tmp_path)
    suite = load_eval_suite(path)
    assert suite.schema == SUITE_SCHEMA_V2 and suite.has_motion
    assert suite.job_count == EXPECTED_JOBS[name] <= MAX_EVAL_JOBS
    result = validate_draft(EvalSuiteDraft.open(path), CATALOG)
    assert not result.errors, result.errors


def test_the_campaign_is_bounded_at_thirty_jobs_before_reuse_and_never_authorizes_itself():
    assert sum(EXPECTED_JOBS.values()) == 30
    for name in FILES:
        data = raw(name)
        assert "Unexecuted template" in data["description"]
        assert "separate authorization" in data["description"]
        assert "multi-engine" in data["description"]


def test_every_stage_compares_exactly_the_two_registered_engines_at_a_shared_legal_length():
    envelope = shared_envelope([registered_contracts()[ANIMATE], registered_contracts()[FUN]])
    for name in FILES:
        data = raw(name)
        assert data["baseline_arm"] == "animate2"
        engines = {(a["form"]["workflow_id"], a["form"]["workflow_version"]) for a in data["arms"]}
        assert engines == {ANIMATE, FUN}
        lengths = {a["form"]["frame_count"] for a in data["arms"]}
        assert len(lengths) == 1 and envelope.contains(lengths.pop())  # never 81 against 49
        assert all(a["form"]["experimental_opt_in"] is True for a in data["arms"])
        fun = next(a for a in data["arms"] if a["form"]["workflow_id"] == FUN[0])
        assert (
            "operator_controls" not in fun["form"]
        )  # Fun Control declares none; nothing is forced into it


def test_stage_designs_match_the_contract():
    s1, s2, s3, s4 = (raw(n) for n in FILES)
    assert len(s1["cases"]) == 1 and s1["cases"][0]["motion"]["category"] == "hand_wave"
    categories2 = {c["motion"]["category"] for c in s2["cases"]}
    assert categories2 == {"hand_wave", "walk_forward"} and len(s2["cases"]) == 6
    reps = {
        t for c in s2["cases"] for t in c["tags"] if t in {"character", "silhouette", "skeleton"}
    }
    assert reps == {"character", "silhouette", "skeleton"}
    assert {c["image"] for c in s2["cases"]} == {
        "images/upper_body_a.png",
        "images/full_body_a.png",
    }
    assert len(s3["cases"]) == 6 and len({c["image"] for c in s3["cases"]}) == 6
    assert {c["motion"]["category"] for c in s3["cases"]} == {
        "head_turn",
        "hand_wave",
        "walk_forward",
    }
    assert len(s4["cases"]) == 2 and s4["seed"] == 431
    assert {s["seed"] for s in (s1, s2, s3)} == {430}  # one seed; stage 4 adds exactly one more


def test_no_template_carries_machine_paths_or_committed_media():
    for name, file in FILES.items():
        text = (EXAMPLES / file).read_text(encoding="utf-8")
        assert (
            ":\\" not in text and ":/" not in text and "/Users/" not in text and "\\\\" not in text
        )
        data = raw(name)
        for case in data["cases"]:
            assert not Path(case["image"]).is_absolute()
            assert not Path(case["motion"]["driving"]["path"]).is_absolute()
            assert (
                "sha256" not in case["motion"]["driving"]
            )  # pinned when the operator binds real files
    assert not any(p.suffix in (".mp4", ".png") for p in EXAMPLES.iterdir())


@pytest.mark.parametrize("name", FILES)
def test_the_production_builders_admit_every_cell_through_both_engines(name, tmp_path):
    path = materialize(name, tmp_path)
    ctl, service = controller(tmp_path, preparer=fake_prepared_record)
    plan = ctl.preview_eval_run(path)
    assert plan.eligible, plan.summary()
    assert len(plan.jobs) == EXPECTED_JOBS[name]
    assert {job.arm_id for job in plan.jobs} == {"animate2", "fun_control"}
    assert "different driving contracts" in plan.summary()
    assert not service.calls  # previewing queues nothing
