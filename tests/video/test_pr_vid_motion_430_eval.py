"""PR-VID-MOTION-430 Workstreams F and G: engine and representation comparisons keep their integrity and denominators.

A real temporary job repository holds NJRs built by the production Video Workflow builder (Wan-Animate-2); clip bytes are fake and
measurement is faked.  No runtime, FFmpeg or GPU is involved and nothing is generated.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.queue.job_model import JobStatus
from src.video.video_eval_integrity import (
    ComparisonKind,
    IntegrityClass,
    classify_pair,
    classify_representation_group,
    engine_disclosures,
)
from src.video.video_eval_metrics import ClipMeasurement
from src.video.video_eval_motion import MotionBindingError, parse_motion
from src.video.video_eval_report import build_eval_report
from src.video.video_eval_transfer import LEVELS, summarize_transfer
from tests.helpers.video_review_211 import finish, new_repository, persist, video_result
from tests.video.motion_410_support import (
    controller,
    drive_arm,
    make_image,
    make_video,
    motion_block,
    write_suite,
)
from tests.video.test_pr_vid_eval_320_report import _metrics

FUN = "wan22_fun_control_5b_canny_i2v_v1"
ANIMATE = "wan_animate2_drive_i2v_v1"
KEY = "c" * 64


def _settings(**over):
    base = {
        "workflow_id": ANIMATE,
        "workflow_version": "1.2.0",
        "frame_count": 49,
        "fps": 24,
        "seed": 7,
        "driver_original_sha256": "a" * 64,
        "driver_effective_sha256": "b" * 64,
        "ordered_frames_sha256": "d" * 64,
        "preparation_settings": {"start": 0},
        "interpolation": False,
        "controls": {"pose_prompt": "wave"},
        "alignment": None,
        "temporal_plan_sha256": "e" * 64,
    }
    base.update(over)
    return base


# ----------------------------------------------------------------------------------------------- engine comparison


def test_two_engines_are_a_multi_engine_comparison_with_inseparable_differences_disclosed():
    pair = classify_pair(
        _settings(),
        _settings(workflow_id=FUN, workflow_version="1.1.0", driver_effective_sha256="f" * 64),
    )
    assert pair.kind is ComparisonKind.MULTI_ENGINE
    assert pair.integrity is IntegrityClass.VERIFIED_WITH_DISCLOSED_DIFFERENCES
    text = "\n".join(pair.disclosed)
    assert "multi-engine comparison, not a one-variable experiment" in text
    assert "RGB frames, resized and VAE-encoded directly vs Canny edge map" in text
    assert "same seed value does not give equivalent noise" in text


def test_a_version_change_of_one_engine_stays_a_multi_setting_comparison():
    pair = classify_pair(_settings(), _settings(workflow_version="1.1.0"))
    assert pair.kind is ComparisonKind.MULTI_ARM


def test_an_81_frame_animate_arm_is_flagged_against_a_49_frame_fun_control_arm():
    base = _settings(frame_count=81)
    cand = _settings(workflow_id=FUN, workflow_version="1.1.0", frame_count=49)
    notes = engine_disclosures(base, cand)
    assert any("81 frames is outside the shared envelope for baseline" in n for n in notes)
    pair = classify_pair(base, cand)
    assert "frame count differs" in "\n".join(pair.disclosed)
    assert pair.integrity.comparable  # disclosed, never silently equalised


def test_engine_specific_controls_are_listed_not_dropped():
    base = _settings(controls={"pose_prompt": "wave", "pose_strength": 1.0})
    cand = _settings(workflow_id=FUN, workflow_version="1.1.0", controls={"pose_prompt": "wave"})
    assert any("pose_strength" in n for n in engine_disclosures(base, cand))


def test_a_different_driver_or_seed_across_engines_is_still_incomparable():
    pair = classify_pair(_settings(), _settings(workflow_id=FUN, workflow_version="1.1.0", seed=8))
    assert pair.integrity is IntegrityClass.INCOMPARABLE


# ----------------------------------------------------------------------------------------------- representation groups


def _block(kind, key=KEY):
    return {"representation": kind, "movement_key": key, "profile": "p", "plan_digest": "x"}


def _group(**over):
    settings = {
        "c": _settings(driver_original_sha256="1" * 64),
        "s": _settings(driver_original_sha256="2" * 64, driver_effective_sha256="9" * 64),
        "k": _settings(driver_original_sha256="3" * 64, driver_effective_sha256="8" * 64),
    }
    blocks = {
        "c": _block("rendered_character"),
        "s": _block("rendered_silhouette"),
        "k": _block("rendered_skeleton"),
    }
    subjects = dict.fromkeys(settings, "img")
    settings.update(over.pop("settings", {}))
    blocks.update(over.pop("blocks", {}))
    subjects.update(over.pop("subjects", {}))
    return classify_representation_group(settings, blocks, subjects, **over)


def test_a_verified_common_movement_with_one_source_and_fixed_settings_is_controlled():
    result = _group()
    assert result.kind is ComparisonKind.REPRESENTATION
    assert result.integrity is IntegrityClass.VERIFIED_COMPARABLE and result.distinct_subjects == 1
    assert "differs by design" in result.disclosed[0]


def test_a_different_alignment_is_a_disclosed_additional_intervention():
    result = _group(settings={"s": _settings(driver_original_sha256="2" * 64, alignment="t" * 64)})
    assert result.integrity is IntegrityClass.VERIFIED_WITH_DISCLOSED_DIFFERENCES
    assert any("additional intervention" in d for d in result.disclosed)


@pytest.mark.parametrize(
    ("override", "integrity", "expected"),
    [
        ({"blocks": {"k": None}}, IntegrityClass.MISSING_EVIDENCE, "exploratory"),
        (
            {"blocks": {"k": _block("rendered_skeleton", "d" * 64)}},
            IntegrityClass.INCOMPARABLE,
            "same movement",
        ),
        ({"subjects": {"k": "other-image"}}, IntegrityClass.INCOMPARABLE, "source image differs"),
        (
            {"settings": {"k": _settings(driver_original_sha256="3" * 64, frame_count=33)}},
            IntegrityClass.INCOMPARABLE,
            "frame_count",
        ),
        (
            {"settings": {"k": _settings(driver_original_sha256="3" * 64, workflow_id=FUN)}},
            IntegrityClass.INCOMPARABLE,
            "workflow_id",
        ),
        (
            {"settings": {"k": _settings(driver_original_sha256="3" * 64, seed=99)}},
            IntegrityClass.INCOMPARABLE,
            "seed",
        ),
        (
            {
                "settings": {
                    "k": _settings(
                        driver_original_sha256="3" * 64, controls={"pose_prompt": "other"}
                    )
                }
            },
            IntegrityClass.INCOMPARABLE,
            "controls.pose_prompt",
        ),
        (
            {
                "cell_problems": [IntegrityClass.FAILED_OR_INCOMPLETE],
                "problem_reasons": ["job failed"],
            },
            IntegrityClass.FAILED_OR_INCOMPLETE,
            "job failed",
        ),
    ],
)
def test_anything_that_breaks_the_controlled_claim_is_named(override, integrity, expected):
    result = _group(**override)
    assert result.integrity is integrity
    assert expected in " ".join(result.reasons)
    assert not result.integrity.comparable


def test_one_representation_or_one_case_is_not_a_comparison():
    same = _group(blocks={"s": _block("rendered_character"), "k": _block("rendered_character")})
    assert (
        same.integrity is IntegrityClass.MISSING_EVIDENCE
        and "same driving representation" in same.reasons[0]
    )
    single = classify_representation_group(
        {"c": _settings()}, {"c": _block("rendered_character")}, {"c": "img"}
    )
    assert single.integrity is IntegrityClass.MISSING_EVIDENCE


# ----------------------------------------------------------------------------------------------- suite binding


def _binding(tmp_path, representation):
    driver = make_video(tmp_path / "d" / "walk.mp4", b"walk-render")
    digest = hashlib.sha256(driver.read_bytes()).hexdigest()
    library = {"asset_id": "mot_1", "sha256": digest}
    if representation is not None:
        library["representation"] = representation
    block = motion_block(
        driver, driving={"path": str(driver), "sha256": digest, "library_asset": library}
    )
    return parse_motion(block, "c1", None)


def test_a_library_binding_may_carry_a_validated_representation_claim(tmp_path):
    claim = _block("rendered_silhouette")
    binding = _binding(tmp_path, claim)
    assert binding.library_asset["representation"] == {**claim, "profile": "p", "plan_digest": "x"}
    assert binding.to_record()["driving"]["library_asset"]["representation"]["movement_key"] == KEY
    plain = _binding(tmp_path, None)
    assert "representation" not in plain.library_asset
    # The same-motion identity is unchanged by the additive claim.
    assert binding.identity == plain.identity


@pytest.mark.parametrize(
    "bad",
    [
        {"representation": "depth_video", "movement_key": KEY},
        {"representation": "rendered_skeleton", "movement_key": "nope"},
        {"representation": "rendered_skeleton", "movement_key": KEY, "extra": 1},
        "skeleton",
    ],
)
def test_a_malformed_representation_claim_is_refused_not_ignored(tmp_path, bad):
    with pytest.raises(MotionBindingError):
        _binding(tmp_path, bad)


# ----------------------------------------------------------------------------------------------- end to end


class RepresentationRun:
    """One source image, three drivers of one movement (claimed representations), two arms; fake clips, no generation."""

    def __init__(
        self, tmp_path: Path, *, claims: bool = True, fail: tuple[str, str] | None = None
    ) -> None:
        image = make_image(tmp_path / "suite" / "images" / "s.png")
        kinds = (
            ("char", "rendered_character", b"render-character"),
            ("sil", "rendered_silhouette", b"render-silhouette"),
            ("skel", "rendered_skeleton", b"render-skeleton"),
        )
        cases = []
        for name, kind, payload in kinds:
            driver = make_video(tmp_path / "suite" / "motion" / f"{name}.mp4", payload)
            digest = hashlib.sha256(payload).hexdigest()
            library = {"asset_id": f"mot_{name}", "sha256": digest}
            if claims:
                library["representation"] = _block(kind)
            cases.append(
                {
                    "case_id": name,
                    "image": str(image),
                    "prompt": "a woman in a red coat stands in a studio",
                    "motion": motion_block(
                        driver,
                        driving={"path": str(driver), "sha256": digest, "library_asset": library},
                    ),
                }
            )
        arms = [drive_arm("baseline"), drive_arm("strong", pose_strength=1.2)]
        ctl, _service = controller(tmp_path)
        self.plan = ctl.preview_eval_run(write_suite(tmp_path, cases, arms))
        assert self.plan.eligible, self.plan.summary()
        admission = ctl.submit_eval_run(self.plan)
        self.run_dir = admission.run_dir
        self.repo = new_repository(tmp_path)
        persist(self.repo, [job.njr for job in self.plan.jobs])
        for job in self.plan.jobs:
            clip = tmp_path / "clips" / f"{job.job_id}.mp4"
            clip.parent.mkdir(exist_ok=True)
            clip.write_bytes(f"clip {job.case_id} {job.arm_id}".encode())
            if fail == (job.case_id, job.arm_id):
                finish(self.repo, job.job_id, JobStatus.FAILED, error="out of memory")
            else:
                finish(self.repo, job.job_id, JobStatus.COMPLETED, result=video_result(clip))

    def build(self):
        def measure(path, cancel=None):
            return ClipMeasurement(path=path, ok=True, metrics=_metrics(3.0))

        return build_eval_report(self.run_dir, self.repo, measure=measure)


def test_a_verified_trio_forms_a_controlled_group_per_arm_in_the_report(tmp_path):
    report = RepresentationRun(tmp_path).build()
    groups = report.assessment.representation_groups
    assert {g.arm_id for g in groups} == {"baseline", "strong"}
    for group in groups:
        assert group.kind is ComparisonKind.REPRESENTATION
        assert set(group.representations) == {
            "rendered_character",
            "rendered_silhouette",
            "rendered_skeleton",
        }
        assert group.integrity.integrity.comparable, group.integrity
    by_rep = {g.key: g for g in report.transfer.level("representation")}
    assert set(by_rep) == {"rendered_character", "rendered_silhouette", "rendered_skeleton"}
    assert all(g.planned == 2 and g.completed == 2 for g in by_rep.values())
    movement = report.transfer.level("representation_group")
    assert len(movement) == 1 and movement[0].planned == 6 and movement[0].key == KEY[:12]


def test_unclaimed_drivers_are_labelled_exploratory_not_a_controlled_comparison(tmp_path):
    report = RepresentationRun(tmp_path, claims=False).build()
    groups = report.assessment.representation_groups
    assert groups and all(not g.integrity.integrity.comparable for g in groups)
    assert all("exploratory" in " ".join(g.integrity.reasons) for g in groups)
    assert {g.key for g in report.transfer.level("representation")} == {"unverified"}
    html = report_html(report)
    assert "Driving-representation groups" in html and "exploratory" in html


def report_html(report) -> str:
    from src.video import video_eval_motion_html as motion_html

    return motion_html.representation_groups_html(report.assessment)


def test_a_failed_generation_stays_in_the_denominators_and_the_group_integrity(tmp_path):
    report = RepresentationRun(tmp_path, fail=("skel", "baseline")).build()
    skeleton = {g.key: g for g in report.transfer.level("representation")}["rendered_skeleton"]
    assert (skeleton.planned, skeleton.completed, skeleton.failed_or_incomplete) == (2, 1, 1)
    baseline = next(g for g in report.assessment.representation_groups if g.arm_id == "baseline")
    assert baseline.integrity.integrity is IntegrityClass.FAILED_OR_INCOMPLETE
    assert report.assessment.representation_groups  # nothing hides the failure


def test_new_summary_levels_cover_engine_alignment_and_length_with_the_existing_ones(tmp_path):
    report = RepresentationRun(tmp_path).build()
    assert {
        "engine",
        "representation",
        "representation_group",
        "alignment",
        "generation_length",
    } <= set(LEVELS)
    engine = report.transfer.level("engine")
    assert len(engine) == 1 and "RGB frames, resized and VAE-encoded directly" in engine[0].label
    assert engine[0].planned == 6
    assert {g.key for g in report.transfer.level("alignment")} == {"unaligned"}
    assert {g.key for g in report.transfer.level("generation_length")} == {"49 frames at 24 fps"}
    notes = " ".join(report.transfer.to_payload()["notes"])
    assert "Generation time" in notes and "faster engine" in notes


def test_ordinary_summaries_remain_empty():
    from src.video.video_eval_assessment import Assessment

    assert summarize_transfer({}, Assessment()).groups == ()


# ----------------------------------------------------------------------------------------------- two engines end to end


def test_the_motion_prompt_is_only_sent_to_an_engine_that_declares_the_control():
    from src.video.workflow_conditioning import takes_motion_prompt

    assert takes_motion_prompt(ANIMATE, "1.2.0") and takes_motion_prompt(ANIMATE, "1.1.0")
    assert not takes_motion_prompt(ANIMATE, "1.0.0")  # 1.0.0 declares no controls at all
    assert not takes_motion_prompt(FUN, "1.1.0") and not takes_motion_prompt("nope", "1")


def test_an_engine_without_a_motion_prompt_is_disclosed_not_incomparable():
    base = _settings(controls={"pose_prompt": "wave"})
    cand = _settings(workflow_id=FUN, workflow_version="1.1.0", controls={})
    pair = classify_pair(base, cand)
    assert pair.kind is ComparisonKind.MULTI_ENGINE and pair.integrity.comparable
    assert any("takes no separate motion prompt" in note for note in pair.disclosed)
    both = classify_pair(
        base,
        _settings(workflow_id=FUN, workflow_version="1.1.0", controls={"pose_prompt": "other"}),
    )
    assert (
        both.integrity is IntegrityClass.INCOMPARABLE
    )  # two different prompts are never a disclosure
    same_engine = classify_pair(base, _settings(controls={}))
    assert (
        same_engine.integrity is IntegrityClass.INCOMPARABLE
    )  # the carve-out is for different engines only


class EngineRun:
    """One case, Animate-2 against Fun Control at a shared length, through the production builders with a fake preparer."""

    def __init__(self, tmp_path: Path) -> None:
        from tests.video.motion_410_support import fake_prepared_record

        image = make_image(tmp_path / "suite" / "images" / "s.png")
        driver = make_video(tmp_path / "suite" / "motion" / "wave.mp4", b"wave")
        case = {
            "case_id": "wave",
            "image": str(image),
            "prompt": "a woman in a red coat stands in a studio",
            "motion": motion_block(
                driver,
                category="hand_wave",
                action="waves the right hand",
                motion_prompt="the person waves their right hand",
                expected_outcome="The right hand waves side to side; the body stays still.",
                preparation={"mode": "workflow_prepared", "fps_conversion": "workflow_rate"},
            ),
        }
        fun = {
            "arm_id": "fun",
            "label": "Fun Control 5B Canny (trial)",
            "backend": "video_workflow",
            "form": {
                "workflow_id": FUN,
                "workflow_version": "1.1.0",
                "frame_count": 33,
                "experimental_opt_in": True,
            },
        }
        ctl, self.service = controller(tmp_path, preparer=fake_prepared_record)
        self.plan = ctl.preview_eval_run(
            write_suite(tmp_path, [case], [drive_arm("animate", frame_count=33), fun])
        )
        assert self.plan.eligible, self.plan.summary()
        self.admission = ctl.submit_eval_run(self.plan)
        self.run_dir = self.admission.run_dir
        self.repo = new_repository(tmp_path)
        persist(self.repo, [job.njr for job in self.plan.jobs])
        for job in self.plan.jobs:
            clip = tmp_path / "clips" / f"{job.job_id}.mp4"
            clip.parent.mkdir(exist_ok=True)
            clip.write_bytes(f"clip {job.arm_id}".encode())
            finish(self.repo, job.job_id, JobStatus.COMPLETED, result=video_result(clip))

    def build(self):
        def measure(path, cancel=None):
            return ClipMeasurement(path=path, ok=True, metrics=_metrics(3.0))

        return build_eval_report(self.run_dir, self.repo, measure=measure)


def test_animate2_and_fun_control_admit_in_one_suite_and_the_fun_job_freezes_no_motion_prompt(
    tmp_path,
):
    run = EngineRun(tmp_path)
    jobs = {job.arm_id: job for job in run.plan.jobs}
    from src.video.video_eval_motion import motion_facts_from_njr

    animate = motion_facts_from_njr(jobs["animate"].njr)
    fun = motion_facts_from_njr(jobs["fun"].njr)
    assert animate.motion_prompt == "the person waves their right hand"
    assert fun.motion_prompt == "" and fun.workflow_id == FUN and fun.workflow_version == "1.1.0"
    assert fun.driver_original_sha256 == animate.driver_original_sha256
    assert (fun.frame_count, fun.fps) == (animate.frame_count, animate.fps) == (33, 24)
    assert fun.prepared and animate.prepared
    # each engine consumes its own preparation contract (workflow, version and length), never another engine's derivative
    assert fun.driver_effective_sha256 != animate.driver_effective_sha256
    assert "2 different driving contracts" in run.plan.summary()
    assert len(run.service.calls[0]) == 2  # both jobs submitted together, all-or-none


def test_the_report_calls_it_a_multi_engine_comparison_with_the_disclosures_and_both_engines_in_the_summary(
    tmp_path,
):
    report = EngineRun(tmp_path).build()
    comparison = report.assessment.comparison("wave", "fun")
    assert comparison.integrity.kind is ComparisonKind.MULTI_ENGINE
    assert comparison.integrity.integrity is IntegrityClass.VERIFIED_WITH_DISCLOSED_DIFFERENCES
    text = " ".join(comparison.integrity.disclosed)
    assert "multi-engine comparison, not a one-variable experiment" in text
    assert "takes no separate motion prompt" in text
    engines = {g.key.split(" - ")[0] for g in report.transfer.level("engine")}
    assert engines == {f"{ANIMATE}@1.2.0", f"{FUN}@1.1.0"}
    labels = " ".join(g.label for g in report.transfer.level("engine"))
    assert "Canny edge map" in labels and "RGB frames, resized and VAE-encoded directly" in labels
