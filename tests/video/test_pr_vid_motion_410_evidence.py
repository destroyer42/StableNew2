"""PR-VID-MOTION-410 Workstreams D, F, H, I, K: comparison integrity, motion ratings, evidence applicability, transfer.

A real temporary SQLite job repository holds NJRs built by the production Video Workflow builder for Wan-Animate-2; clip
bytes are fake and measurement is faked. No FFmpeg, runtime or GPU is involved and nothing is generated.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from src.queue.job_model import JobStatus
from src.video.video_eval_assessment import AssessmentState, MotionState, Verdict
from src.video.video_eval_integrity import (
    ComparisonKind,
    IntegrityClass,
    classify_group,
    classify_pair,
)
from src.video.video_eval_metrics import ClipMeasurement
from src.video.video_eval_ratings_store import (
    CONTEXT_COLUMN,
    MOTION_RATING_COLUMNS,
    RATING_COLUMNS,
    RUBRIC_COLUMN,
)
from src.video.video_eval_report import RATINGS_FILE, build_eval_report
from src.video.video_eval_rubric import (
    ACTION_KEYS,
    ATTACHMENT_KEYS,
    MOTION_RUBRIC_VERSION,
    parse_rating_row,
)
from src.video.video_eval_transfer import MIN_DISTINCT_SUBJECTS, summarize_transfer
from tests.helpers.video_review_211 import finish, new_repository, persist, video_result
from tests.video.motion_410_support import (
    controller,
    drive_arm,
    fake_prepared_record,
    make_image,
    make_video,
    motion_block,
    write_suite,
)
from tests.video.test_pr_vid_eval_320_report import _metrics

ARMS = [
    ("baseline", {"pose_strength": 1.0, "reference_image_strength": 1.0}),
    ("motion_emphasis", {"pose_strength": 1.2, "reference_image_strength": 1.0}),
    ("reference_emphasis", {"pose_strength": 1.0, "reference_image_strength": 1.3}),
]
FULL = {
    "requested_action": "achieved",
    "subject_attachment": "correct_subject",
    "motion_fidelity_1_to_5": "4",
    "source_fidelity_1_to_5": "4",
    "subject_stability_1_to_5": "4",
    "critical_identity_break": "no",
}


def fake_diagnose(calls: list):
    def diagnose(driver, result, cache=None, cancel=None):
        calls.append((driver, result))
        return {
            "status": "ok",
            "kind": "global_image_motion_diagnostic",
            "reasons": [],
            "comparison": {
                "trace_correlation": 0.8,
                "lag_seconds": 0.0,
                "onset_displacement_seconds": 0.0,
                "relative_motion_magnitude": 1.0,
                "result_frozen_while_driver_active_seconds": 0.0,
                "compared_seconds": 2.0,
                "fps_differs": False,
            },
        }

    return diagnose


class MotionRun:
    """subjects x three arms, admitted through the production controller, persisted and "generated" with fake clips."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        subjects: int = 2,
        prepared: bool = False,
        same_image: bool = False,
        fail: tuple[str, str] | None = None,
    ) -> None:
        self.tmp = tmp_path
        self.driver = make_video(tmp_path / "suite" / "motion" / "head.mp4")
        extra = (
            {"preparation": {"mode": "workflow_prepared", "fps_conversion": "workflow_rate"}}
            if prepared
            else {}
        )
        cases = []
        for index in range(subjects):
            image = make_image(
                tmp_path / "suite" / "images" / f"s{index}.png",
                color=(40, 90, 120) if same_image else (40 * index + 10, 90, 120),
            )
            cases.append(
                {
                    "case_id": f"head_s{index}",
                    "image": str(image),
                    "prompt": "a woman in a red coat stands in a studio",
                    "motion": motion_block(self.driver, **extra),
                }
            )
        arms = [drive_arm(arm_id, **controls) for arm_id, controls in ARMS]
        ctl, _service = controller(tmp_path, preparer=fake_prepared_record if prepared else None)
        self.plan = ctl.preview_eval_run(write_suite(tmp_path, cases, arms))
        assert self.plan.eligible, self.plan.summary()
        admission = ctl.submit_eval_run(self.plan)
        self.run_dir = admission.run_dir
        self.repo = new_repository(tmp_path)
        self.ids = persist(self.repo, [job.njr for job in self.plan.jobs])
        self.clips: dict[str, Path] = {}
        for job in self.plan.jobs:
            clip = tmp_path / "clips" / f"{job.job_id}.mp4"
            clip.parent.mkdir(exist_ok=True)
            clip.write_bytes(f"clip {job.case_id} {job.arm_id}".encode())
            self.clips[job.job_id] = clip
            if fail == (job.case_id, job.arm_id):
                finish(self.repo, job.job_id, JobStatus.FAILED, error="out of memory")
            else:
                finish(self.repo, job.job_id, JobStatus.COMPLETED, result=video_result(clip))
        self.diagnose_calls: list = []

    def build(self, **kwargs):
        def measure(path, cancel=None):
            return ClipMeasurement(path=path, ok=True, metrics=_metrics(3.0))

        kwargs.setdefault("diagnose", fake_diagnose(self.diagnose_calls))
        return build_eval_report(self.run_dir, self.repo, measure=measure, **kwargs)

    @property
    def ratings_path(self) -> Path:
        return self.run_dir / RATINGS_FILE

    def rows(self) -> list[dict[str, str]]:
        with self.ratings_path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def write_rows(self, rows: list[dict[str, str]], header: list[str] | None = None) -> None:
        header = header or list(rows[0])
        with self.ratings_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def rate(self, where, **values: str) -> None:
        rows = self.rows()
        for row in rows:
            if where(row):
                row.update(values)
        self.write_rows(rows)

    def job(self, case_id: str, arm_id: str):
        return next(j for j in self.plan.jobs if (j.case_id, j.arm_id) == (case_id, arm_id))


@pytest.fixture
def run(tmp_path) -> MotionRun:
    return MotionRun(tmp_path)


def cell(report, case_id: str, arm_id: str):
    return report.assessment.cell(case_id, arm_id)


# ------------------------------------------------------------------ F. the rubric


@pytest.mark.parametrize("value", ACTION_KEYS)
def test_every_action_outcome_state_parses_and_unobserved_states_are_not_complete(value) -> None:
    evidence = parse_rating_row({**FULL, "requested_action": value})
    assert evidence.requested_action == value and evidence.issues == ()
    assert evidence.motion_complete == (value != "cannot_assess")


@pytest.mark.parametrize("value", ATTACHMENT_KEYS)
def test_every_subject_attachment_state_parses(value) -> None:
    evidence = parse_rating_row({**FULL, "subject_attachment": value})
    assert evidence.subject_attachment == value and evidence.issues == ()
    assert evidence.motion_complete == (value != "cannot_assess")


def test_action_attachment_and_fidelity_are_independent_judgments() -> None:
    lively_wrong_subject = parse_rating_row(
        {
            **FULL,
            "requested_action": "achieved",
            "subject_attachment": "incorrect_subject",
            "motion_fidelity_1_to_5": "5",
        }
    )
    # Strong movement by the wrong figure is a recorded, complete rating - not a collapsed success or failure.
    assert lively_wrong_subject.motion_complete
    assert (lively_wrong_subject.requested_action, lively_wrong_subject.subject_attachment) == (
        "achieved",
        "incorrect_subject",
    )
    assert parse_rating_row({"motion_fidelity_1_to_5": "5"}).motion_missing() == (
        "Requested action (an observed outcome)",
        "Subject attachment",
    )


def test_fidelity_has_an_explicit_unassessed_state_and_rejects_values_outside_the_anchors() -> None:
    for blank in ("", "not_assessed"):
        row = {**FULL, "motion_fidelity_1_to_5": blank}
        assert (
            parse_rating_row(row).motion_fidelity is None
            and not parse_rating_row(row).motion_complete
        )
    bad = parse_rating_row({**FULL, "motion_fidelity_1_to_5": "6"})
    assert bad.motion_fidelity is None and bad.issues


def test_not_applicable_observations_are_explicit_and_never_negative() -> None:
    evidence = parse_rating_row(
        {
            **FULL,
            "root_displacement": "not_applicable",
            "action_direction": "correct",
            "driver_contamination": "none_observed",
        }
    )
    assert evidence.observations["root_displacement"] == "not_applicable"
    assert evidence.issues == ()
    unassessed = parse_rating_row({**FULL, "action_timing": "not_assessed"})
    assert unassessed.observations["action_timing"] is None
    assert parse_rating_row({**FULL, "action_timing": "late"}).issues


def test_motion_failure_categories_extend_the_existing_taxonomy_without_synonyms() -> None:
    evidence = parse_rating_row(
        {
            **FULL,
            "failure_categories": "wrong_direction; duplicate_or_ghost_subject; start_end_pose_mismatch; motion_freeze",
        }
    )
    assert evidence.failure_categories == (
        "wrong_direction",
        "duplicate_or_ghost_subject",
        "start_end_pose_mismatch",
        "motion_freeze",
    )
    assert evidence.issues == ()


# ------------------------------------------------------------------ D. comparison integrity semantics


def test_baseline_to_candidate_differing_by_one_declared_control_is_a_one_variable_experiment(
    run,
) -> None:
    report = run.build()
    for arm in ("motion_emphasis", "reference_emphasis"):
        pair = report.assessment.comparison("head_s0", arm)
        assert pair.integrity.kind is ComparisonKind.ONE_VARIABLE
        assert pair.integrity.integrity is IntegrityClass.VERIFIED_COMPARABLE
        assert len(pair.integrity.varied) == 1


def test_candidates_that_differ_in_two_controls_are_not_called_one_variable() -> None:
    motion = {
        "workflow_id": "w",
        "workflow_version": "1",
        "frame_count": 49,
        "fps": 24,
        "seed": 410,
        "driver_original_sha256": "a" * 64,
        "controls": {"pose_prompt": "x", "pose_strength": 1.2, "reference_image_strength": 1.0},
    }
    reference = {
        **motion,
        "controls": {"pose_prompt": "x", "pose_strength": 1.0, "reference_image_strength": 1.3},
    }
    pair = classify_pair(motion, reference)
    assert pair.kind is ComparisonKind.MULTI_ARM
    assert pair.integrity is IntegrityClass.VERIFIED_WITH_DISCLOSED_DIFFERENCES
    assert any("not separable" in text for text in pair.disclosed)


def test_a_workflow_version_change_is_a_disclosed_inseparable_difference() -> None:
    base = {
        "workflow_id": "w",
        "workflow_version": "1.1.0",
        "driver_original_sha256": "a" * 64,
        "seed": 1,
        "controls": {"pose_prompt": "x"},
    }
    pair = classify_pair(base, {**base, "workflow_version": "1.2.0"})
    assert pair.kind is ComparisonKind.MULTI_ARM
    assert pair.integrity is IntegrityClass.VERIFIED_WITH_DISCLOSED_DIFFERENCES
    assert any("not a strict one-variable" in text for text in pair.disclosed)


def test_a_different_driver_seed_or_motion_prompt_is_incomparable() -> None:
    base = {
        "driver_original_sha256": "a" * 64,
        "seed": 1,
        "controls": {"pose_prompt": "x", "pose_strength": 1.0},
    }
    for change in (
        {"driver_original_sha256": "b" * 64},
        {"seed": 2},
        {"controls": {"pose_prompt": "y", "pose_strength": 1.0}},
    ):
        assert classify_pair(base, {**base, **change}).integrity is IntegrityClass.INCOMPARABLE


def test_a_cell_problem_outranks_matching_settings() -> None:
    base = {"driver_original_sha256": "a" * 64, "seed": 1, "controls": {"pose_prompt": "x"}}
    pair = classify_pair(
        base,
        base,
        cell_problems=[IntegrityClass.FAILED_OR_INCOMPLETE],
        problem_reasons=["job failed"],
    )
    assert pair.integrity is IntegrityClass.FAILED_OR_INCOMPLETE and pair.reasons == ("job failed",)


def test_cross_subject_integrity_requires_fixed_motion_and_settings_and_two_subjects() -> None:
    settings = {
        "driver_original_sha256": "a" * 64,
        "seed": 1,
        "controls": {"pose_prompt": "x", "pose_strength": 1.0},
    }
    good = classify_group({"c1": settings, "c2": settings}, {"c1": "s1", "c2": "s2"})
    assert good.integrity is IntegrityClass.VERIFIED_COMPARABLE and good.distinct_subjects == 2
    drift = classify_group(
        {"c1": settings, "c2": {**settings, "seed": 2}}, {"c1": "s1", "c2": "s2"}
    )
    assert drift.integrity is IntegrityClass.INCOMPARABLE
    alone = classify_group({"c1": settings}, {"c1": "s1"})
    assert alone.integrity is IntegrityClass.MISSING_EVIDENCE


def test_the_run_groups_one_motion_across_subjects_per_arm(run) -> None:
    report = run.build()
    groups = report.assessment.cross_subject
    assert {g.arm_id for g in groups} == {"baseline", "motion_emphasis", "reference_emphasis"}
    assert all(set(g.case_ids) == {"head_s0", "head_s1"} for g in groups)
    assert all(
        g.integrity.integrity is IntegrityClass.VERIFIED_COMPARABLE
        and g.integrity.distinct_subjects == 2
        for g in groups
    )


# ------------------------------------------------------------------ H. persistence and applicability


def test_a_motion_run_writes_motion_columns_bound_to_the_clip_and_the_driving_context(run) -> None:
    report = run.build()
    rows = run.rows()
    assert all(column in rows[0] for column in MOTION_RATING_COLUMNS)
    assert all(
        len(row[CONTEXT_COLUMN]) == 64 and row[RUBRIC_COLUMN] == MOTION_RUBRIC_VERSION
        for row in rows
    )
    assert all(len(row["artifact_sha256"]) == 64 for row in rows)
    # Two subjects: two distinct contexts (the source image is part of the context), shared across arms of a subject.
    # The source image is part of the context: one per subject, shared by that subject's three arms.
    assert len({row[CONTEXT_COLUMN] for row in rows}) == 2
    assert cell(report, "head_s0", "baseline").motion_state is MotionState.UNREVIEWED
    assert cell(report, "head_s0", "baseline").integrity is IntegrityClass.VERIFIED_COMPARABLE


def test_non_motion_ratings_files_are_never_given_motion_columns() -> None:
    from src.video.video_eval_ratings_store import LoadedRatings, output_header

    assert output_header(LoadedRatings(path=Path("ratings.csv"))) == RATING_COLUMNS


def test_motion_ratings_survive_a_rebuild_and_a_fresh_process(run) -> None:
    run.build()
    run.rate(
        lambda row: row["case_id"] == "head_s0" and row["arm_id"] == "baseline",
        **FULL,
        notes="kept note",
    )
    first = run.build()
    before = run.ratings_path.read_bytes()
    second = run.build()  # a new build reads only the file: what a restarted application sees

    assert run.ratings_path.read_bytes() == before
    counted = cell(second, "head_s0", "baseline")
    assert (
        counted.motion_state is MotionState.REVIEWED and counted.motion_counts and counted.complete
    )
    assert (
        counted.evidence.subject_attachment == "correct_subject"
        and counted.evidence.motion_fidelity == 4
    )
    assert cell(first, "head_s0", "baseline").state is AssessmentState.REVIEWED
    assert (
        next(r for r in run.rows() if r["arm_id"] == "baseline" and r["case_id"] == "head_s0")[
            "notes"
        ]
        == "kept note"
    )


def test_unknown_columns_and_notes_survive_a_motion_rebuild(run) -> None:
    run.build()
    rows = run.rows()
    header = [*rows[0], "my_private_column"]
    for row in rows:
        row["my_private_column"] = f"keep-{row['arm_id']}"
    rows[0]["notes"] = "operator wrote this"
    run.write_rows(rows, header)
    run.build()
    kept = run.rows()
    assert [row["my_private_column"] for row in kept] == [f"keep-{row['arm_id']}" for row in rows]
    assert kept[0]["notes"] == "operator wrote this"


def test_a_changed_output_makes_every_earlier_rating_stale_without_deleting_it(run) -> None:
    run.build()
    run.rate(lambda row: row["arm_id"] == "baseline", **FULL)
    first = run.build()
    job = run.job("head_s0", "baseline")
    run.clips[job.job_id].write_bytes(b"a different clip")
    report = run.build()
    stale = cell(report, "head_s0", "baseline")
    assert stale.state is AssessmentState.STALE_ARTIFACT and not stale.counts
    assert stale.motion_state is MotionState.INAPPLICABLE and not stale.motion_counts
    assert stale.integrity is IntegrityClass.CHANGED_OUTPUT
    row = next(r for r in run.rows() if r["job_id"] == job.job_id)
    assert (
        row["motion_fidelity_1_to_5"] == "4"
        and row["artifact_sha256"] != hashlib.sha256(b"a different clip").hexdigest()
    )
    assert cell(first, "head_s0", "baseline").motion_counts  # the earlier state really was counted


def test_a_changed_driver_makes_prior_motion_evidence_inapplicable_and_incomparable(run) -> None:
    run.build()
    run.rate(lambda row: True, **FULL)
    run.build()
    bound = {row["job_id"]: row[CONTEXT_COLUMN] for row in run.rows()}
    run.diagnose_calls.clear()
    run.driver.write_bytes(b"another driving video")

    report = run.build()
    for assessed in report.assessment.cells:
        assert assessed.motion_state is MotionState.INAPPLICABLE and not assessed.motion_counts
        assert assessed.integrity is IntegrityClass.CHANGED_INPUT
        assert "driving video" in " ".join(assessed.motion_reasons)
    # The historical judgments and the context they were made against stay identifiable in the file.
    assert {row["job_id"]: row[CONTEXT_COLUMN] for row in run.rows()} == bound
    assert all(row["motion_fidelity_1_to_5"] == "4" for row in run.rows())
    assert (
        run.diagnose_calls == []
    )  # no diagnostic ran against a driver that is not the admitted one
    diag = next(c for c in report.cells if c.case_id == "head_s0").diagnostics
    assert diag["status"] == "unavailable" and diag["comparison"] is None
    pair = report.assessment.comparison("head_s0", "motion_emphasis")
    assert pair.verdict is Verdict.INCOMPARABLE or pair.verdict is Verdict.INSUFFICIENT
    assert pair.integrity.integrity is IntegrityClass.CHANGED_INPUT


def test_a_changed_source_image_is_a_changed_input(run) -> None:
    run.build()
    run.plan.suite.cases[0].image_path.write_bytes(b"a different source image")
    report = run.build()
    assert cell(report, "head_s0", "baseline").integrity is IntegrityClass.CHANGED_INPUT
    assert cell(report, "head_s1", "baseline").integrity is IntegrityClass.VERIFIED_COMPARABLE


def test_motion_judgments_without_a_recorded_context_are_legacy_unverified(run) -> None:
    run.build()
    run.rate(
        lambda row: row["arm_id"] == "baseline", **FULL, **{CONTEXT_COLUMN: "", RUBRIC_COLUMN: ""}
    )
    report = run.build()
    legacy = cell(report, "head_s0", "baseline")
    assert legacy.motion_state is MotionState.LEGACY_UNVERIFIED and not legacy.motion_counts
    assert (
        legacy.evidence.motion_fidelity == 4
    )  # shown for reference, never silently counted or dropped
    # The operator adopts the current context on purpose, the way artifact_sha256 is rebound.
    run.rate(lambda row: row["arm_id"] == "baseline", **{CONTEXT_COLUMN: "rebind"})
    assert cell(run.build(), "head_s0", "baseline").motion_state is MotionState.REVIEWED


def test_a_row_bound_to_another_context_is_inapplicable_not_reassigned(run) -> None:
    run.build()
    run.rate(lambda row: row["arm_id"] == "baseline", **FULL, **{CONTEXT_COLUMN: "f" * 64})
    report = run.build()
    assert cell(report, "head_s0", "baseline").motion_state is MotionState.INAPPLICABLE
    assert all(r[CONTEXT_COLUMN] == "f" * 64 for r in run.rows() if r["arm_id"] == "baseline")


def test_a_failed_job_is_failed_or_incomplete_not_an_unrated_success(tmp_path) -> None:
    run = MotionRun(tmp_path, fail=("head_s0", "baseline"))
    report = run.build()
    failed = cell(report, "head_s0", "baseline")
    assert (
        failed.integrity is IntegrityClass.FAILED_OR_INCOMPLETE
        and failed.motion_state is MotionState.UNAVAILABLE
    )
    group = next(g for g in report.transfer.level("arm") if g.key == "baseline")
    # The runtime failure stays in the attempt counts; it is not dropped and not counted as a rated failure.
    assert (group.planned, group.completed, group.failed_or_incomplete) == (2, 1, 1)
    assert {r.name: r for r in group.ratios}["Attempts completed"].value == 0.5
    assert group.readiness.value == "INSUFFICIENT EVIDENCE"
    pair = report.assessment.comparison("head_s0", "motion_emphasis")
    assert pair.integrity.integrity is IntegrityClass.FAILED_OR_INCOMPLETE


# ------------------------------------------------------------------ the effective driving input


def test_the_diagnostic_uses_the_driver_the_model_actually_consumed(tmp_path) -> None:
    run = MotionRun(tmp_path, prepared=True)
    run.build()
    effective = {
        run.job("head_s0", arm).motion.driver_effective_path
        for arm in ("baseline", "motion_emphasis")
    }
    assert len(effective) == 1 and next(iter(effective)) != str(
        run.driver
    )  # the derivative, shared by arms
    used = {driver for driver, _result in run.diagnose_calls}
    assert used == {next(iter(effective))}
    assert str(run.driver) not in used


# ------------------------------------------------------------------ I. transferability


def test_transfer_counts_carry_denominators_and_never_treat_a_missing_review_as_a_failure(
    run,
) -> None:
    run.build()
    # Rate five of the six cells; the sixth stays unreviewed.
    run.rate(
        lambda row: (row["case_id"], row["arm_id"]) != ("head_s1", "reference_emphasis"), **FULL
    )
    run.rate(
        lambda row: (row["case_id"], row["arm_id"]) == ("head_s1", "motion_emphasis"),
        requested_action="not_achieved",
        subject_attachment="incorrect_subject",
        motion_fidelity_1_to_5="",
    )
    report = run.build()
    arm = {g.key: g for g in report.transfer.level("arm")}
    baseline = arm["baseline"]
    assert (baseline.planned, baseline.completed, baseline.rated) == (2, 2, 2)
    assert baseline.subjects_evaluated == 2 and baseline.subjects_rated == 2 and baseline.seeds == 1
    ratios = {r.name: r for r in baseline.ratios}
    assert (ratios["Action achieved"].numerator, ratios["Action achieved"].denominator) == (2, 2)
    reference = arm["reference_emphasis"]
    # One result is simply unrated: the denominator shrinks to what was judged, nothing is counted as a failure.
    assert reference.rated == 1 and reference.completed == 2
    assert {r.name: r for r in reference.ratios}["Action achieved"].denominator == 1
    assert reference.readiness.value == "INSUFFICIENT EVIDENCE"
    partial = arm["motion_emphasis"]
    assert partial.action["not_achieved"] == 1 and partial.attachment["incorrect_subject"] == 1
    assert (
        partial.rated == 1
    )  # the second one lacks a fidelity rating, so it is judged but not fully rated


def test_unavailable_percentages_are_none_not_zero(run) -> None:
    report = run.build()
    group = report.transfer.level("motion_asset")[0]
    assert group.rated == 0
    ratios = {r.name: r for r in group.ratios}
    # Nothing was judged, so every judgment-based percentage is unavailable (its denominator is 0), not 0%.
    for name in (
        "Action achieved",
        "Intended subject performs the motion",
        "Critical identity break",
    ):
        assert ratios[name].denominator == 0 and ratios[name].value is None
    # Zero of six completed results rated is a real 0 over a real denominator.
    assert (
        ratios["Results rated (all three motion judgments)"].numerator,
        ratios["Results rated (all three motion judgments)"].denominator,
    ) == (0, 6)
    assert ratios["Attempts completed"].value == 1.0


def test_distinct_subjects_are_counted_by_source_bytes_and_replays_are_excluded(tmp_path) -> None:
    run = MotionRun(
        tmp_path, subjects=2, same_image=True
    )  # two case ids, one identical source image
    run.build()
    run.rate(lambda row: True, **FULL)
    report = run.build()
    asset = report.transfer.level("motion_asset")[0]
    assert asset.planned == 6 and asset.subjects_evaluated == 1  # not two: it is one subject
    assert asset.duplicates_excluded == 3  # the second case duplicates every arm of the first
    assert asset.rated == 3  # duplicates cannot raise the rated count
    assert "one source subject" in " ".join(asset.notes)
    assert asset.readiness.value == "INSUFFICIENT EVIDENCE"
    assert any("distinct rated source subject" in reason for reason in asset.readiness_reasons)
    assert len(report.transfer.duplicates) == 3


def test_two_complete_comparable_subjects_without_a_break_are_ready_for_owner_review(run) -> None:
    run.build()
    run.rate(lambda row: True, **FULL)
    report = run.build()
    asset = report.transfer.level("motion_asset")[0]
    assert asset.rated == 6 and asset.subjects_rated >= MIN_DISTINCT_SUBJECTS
    assert asset.readiness.value == "READY FOR OWNER REVIEW"
    assert report.assessment.readiness.value == "READY FOR OWNER REVIEW"


def test_a_critical_identity_break_raises_a_concern_in_every_group_it_belongs_to(run) -> None:
    run.build()
    run.rate(lambda row: True, **FULL)
    run.rate(
        lambda row: (row["case_id"], row["arm_id"]) == ("head_s0", "motion_emphasis"),
        critical_identity_break="yes",
    )
    report = run.build()
    arm = {g.key: g for g in report.transfer.level("arm")}
    assert (
        arm["motion_emphasis"].critical_breaks == 1
        and arm["motion_emphasis"].readiness.value == "IDENTITY CONCERNS"
    )
    assert arm["baseline"].readiness.value == "READY FOR OWNER REVIEW"
    assert report.transfer.level("motion_category")[0].critical_breaks == 1


def test_baseline_relative_motion_differences_use_counted_judgments_only(run) -> None:
    run.build()
    run.rate(lambda row: row["case_id"] == "head_s0" and row["arm_id"] == "baseline", **FULL)
    run.rate(
        lambda row: row["case_id"] == "head_s0" and row["arm_id"] == "motion_emphasis",
        **{**FULL, "motion_fidelity_1_to_5": "5"},
    )
    report = run.build()
    pair = report.assessment.comparison("head_s0", "motion_emphasis")
    assert pair.motion["motion_fidelity_delta"] == 1
    assert pair.motion["requested_action"] == ("achieved", "achieved")
    unrated = report.assessment.comparison("head_s0", "reference_emphasis")
    assert unrated.motion["motion_fidelity_delta"] is None


def test_summaries_of_an_ordinary_run_are_empty() -> None:
    from src.video.video_eval_assessment import Assessment

    assert summarize_transfer({}, Assessment()).groups == ()


# ------------------------------------------------------------------ K. the report


def test_the_report_distinguishes_human_ratings_from_global_diagnostics_and_hides_text_in_sfw(
    run,
) -> None:
    run.build()
    run.rate(lambda row: row["arm_id"] == "baseline", **FULL)
    report = run.build()
    page = report.report_path.read_text(encoding="utf-8")
    assert "Global image-motion diagnostic" in page and "not pose fidelity" in page
    assert "Motion transferability" in page and "Driving-motion reference" in page
    assert "Requested action" in page and "Subject attachment" in page and "Motion fidelity" in page
    assert "rather than a score" not in page and "composite" not in page.lower()
    # The driving video is never auto-played and is loaded only on request.
    assert (
        "preload='none'" in page
        and "autoplay" not in page.split("Driving-motion reference")[1].split("</video>")[0]
    )

    hidden = run.build(show_prompts=False).report_path.read_text(encoding="utf-8")
    assert (
        "The head rotates about 60 degrees" not in hidden
        and "The head rotates about 60 degrees" in page
    )
    assert "[hidden in SFW mode]" in hidden

    payload = json.loads((run.run_dir / "metrics.json").read_text(encoding="utf-8"))
    motion = payload["motion_evaluation"]
    assert motion["rubric_version"] == MOTION_RUBRIC_VERSION and motion["transfer"]["levels"]["arm"]
    assert payload["cells"][0]["motion_diagnostic"]["kind"] == "global_image_motion_diagnostic"
    assert "notes" not in json.dumps(payload["identity_assessment"]["cells"][0]["motion"])
    # metrics.json carries identities and structure only: no action, prompt or expected-outcome text (SFW policy).
    machine = json.dumps(payload)
    assert (
        "60 degrees" not in machine
        and "turns their head" not in machine
        and "turns the head" not in machine
    )
    assert (
        motion["cases"]["head_s0"]["driving"]["sha256"]
        and motion["cases"]["head_s0"]["category"] == "head_turn"
    )


def test_an_unmeasured_diagnostic_is_reported_as_unavailable_never_zero(run) -> None:
    report = run.build(
        diagnose=lambda *_a, **_k: {
            "status": "unavailable",
            "reasons": ["no decoder"],
            "comparison": None,
            "kind": "global_image_motion_diagnostic",
        }
    )
    page = report.report_path.read_text(encoding="utf-8")
    assert "no decoder" in page
    payload = json.loads((run.run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert payload["cells"][0]["motion_diagnostic"]["comparison"] is None
