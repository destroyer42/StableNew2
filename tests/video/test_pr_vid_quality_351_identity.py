"""PR-VID-QUALITY-351: evidence-based identity and continuity acceptance of eval runs.

Offline only: a real temporary SQLite repository with production-built NJRs, fake clip bytes and a faked
measurement function. No FFmpeg, model, runtime or GPU, and no job is ever submitted.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import threading
from pathlib import Path

import pytest

from src.queue.job_model import JobStatus
from src.video import video_eval_ratings_store as store
from src.video.video_eval_assessment import (
    AssessmentState,
    CellInput,
    Provenance,
    Readiness,
    Verdict,
    assess_cell,
    project_assessment,
)
from src.video.video_eval_identity import (
    ArtifactUnhashable,
    CellIdentity,
    Comparability,
    EvalCancelled,
    SourceStatus,
    hash_artifact,
    verify_source,
)
from src.video.video_eval_metrics import ClipMeasurement
from src.video.video_eval_report import (
    METRICS_FILE,
    RATINGS_FILE,
    REPORT_FILE,
    EvalReportError,
    build_eval_report,
)
from src.video.video_eval_rubric import (
    CATEGORY_KEYS,
    SCORE_COLUMNS,
    parse_rating_row,
)
from src.video.video_eval_run import RUN_MANIFEST_NAME, RUN_SCHEMA
from tests.helpers.video_review_211 import (
    build_plan,
    finish,
    new_repository,
    persist_plan,
    video_result,
)
from tests.video.test_pr_vid_eval_320_report import _metrics

COMPLETE = {
    "rating_1_to_5": "4",
    "requested_action": "achieved",
    "source_fidelity_1_to_5": "4",
    "subject_stability_1_to_5": "4",
    "critical_identity_break": "no",
}


# ------------------------------------------------------------------ fixture: a real two-arm eval run


class _Run:
    """One case x two arms (baseline ``base``, candidate ``cand``) over production-built NJRs."""

    def __init__(self, tmp_path: Path, *, seed: int = 424242) -> None:
        plan = build_plan(tmp_path, seed=str(seed))
        self.tmp = tmp_path
        self.repo = new_repository(tmp_path)
        self.ids = persist_plan(self.repo, plan)[:2]
        self.source = tmp_path / "reference.png"
        self.prompt = plan.arms[0].njr  # placeholder, replaced below
        from src.video.video_eval_identity import read_job_facts

        facts = read_job_facts(self.repo.get_job(self.ids[0]).snapshot)
        assert facts is not None
        self.prompt = facts.prompt or ""
        self.seed = seed
        self.clips = {}
        for index, job_id in enumerate(self.ids):
            clip = tmp_path / "clips" / f"{job_id}.mp4"
            clip.parent.mkdir(exist_ok=True)
            clip.write_bytes(f"clip bytes {index}".encode())
            self.clips[job_id] = clip
            finish(self.repo, job_id, JobStatus.COMPLETED, result=video_result(clip))
        self.run_dir = tmp_path / "output" / "video_eval" / "run1"
        self.run_dir.mkdir(parents=True)
        self.write_manifest()

    def write_manifest(self, **overrides) -> None:
        manifest = {
            "schema": RUN_SCHEMA,
            "run_id": "run1",
            "suite": {"suite_id": "core", "seed": self.seed, "baseline_arm": "base"},
            "cases": [
                {
                    "case_id": "portrait",
                    "image": str(self.source),
                    "image_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
                    "prompt": self.prompt,
                }
            ],
            "arms": [
                {"arm_id": "base", "label": "Baseline", "backend": "video_workflow"},
                {"arm_id": "cand", "label": "Candidate", "backend": "video_workflow"},
            ],
            "jobs": [
                {"case_id": "portrait", "arm_id": "base", "job_id": self.ids[0], "seed": self.seed},
                {"case_id": "portrait", "arm_id": "cand", "job_id": self.ids[1], "seed": self.seed},
            ],
        }
        manifest.update(overrides)
        (self.run_dir / RUN_MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    def build(self, **kwargs):
        def measure(path, cancel=None):
            return ClipMeasurement(path=path, ok=True, metrics=_metrics(3.0))

        return build_eval_report(
            self.run_dir, self.repo, measure=kwargs.pop("measure", measure), **kwargs
        )

    @property
    def ratings_path(self) -> Path:
        return self.run_dir / RATINGS_FILE

    def rows(self) -> list[dict[str, str]]:
        with self.ratings_path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def rate(self, job_index: int, **values: str) -> None:
        rows = self.rows()
        header = list(rows[0])
        rows[job_index].update(values)
        with self.ratings_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def cell(self, report, index: int):
        return report.assessment.cells[index]


@pytest.fixture
def run(tmp_path) -> _Run:
    return _Run(tmp_path)


# ------------------------------------------------------------------ A. review rubric


def test_rubric_accepts_only_documented_values_and_reports_the_rest():
    ok = parse_rating_row(
        {**COMPLETE, "failure_categories": "face_or_identity_drift; Motion freeze"}
    )
    assert ok.complete and ok.issues == ()
    assert ok.failure_categories == ("face_or_identity_drift", "motion_freeze")

    bad = parse_rating_row(
        {
            "source_fidelity_1_to_5": "6",
            "subject_stability_1_to_5": "3.5",
            "rating_1_to_5": "0",
            "requested_action": "maybe",
            "critical_identity_break": "perhaps",
            "failure_categories": "face_or_identity_drift;not_a_category",
        }
    )
    assert not bad.complete
    assert len(bad.issues) == 6
    assert all(value is None for value in bad.scores.values()) and bad.overall is None
    assert bad.failure_categories == ("face_or_identity_drift",)
    assert set(CATEGORY_KEYS) >= set(bad.failure_categories)


def test_blank_means_not_assessed_not_zero_or_failure():
    blank = parse_rating_row({"source_fidelity_1_to_5": "", "notes": "looked fine"})
    assert blank.scores["source_fidelity_1_to_5"] is None
    assert blank.has_content is False and blank.issues == () and not blank.complete


@pytest.mark.parametrize("raw", ["-1", "nan", "inf", "soon", "99"])
def test_first_failure_time_must_be_a_real_time_inside_the_clip(raw):
    evidence = parse_rating_row({"first_failure_seconds": raw}, duration_seconds=3.5)
    assert evidence.first_failure_seconds is None and len(evidence.issues) == 1
    fine = parse_rating_row({"first_failure_seconds": "1.25"}, duration_seconds=3.5)
    assert fine.first_failure_seconds == 1.25 and fine.issues == ()


def _cell(**overrides) -> CellInput:
    values = {
        "case_id": "c",
        "arm_id": "a",
        "job_id": "j",
        "job_state": "playable",
        "clip_available": True,
        "measured": True,
        "duration_seconds": 3.0,
        "current_sha256": "a" * 64,
        "identity": CellIdentity(Comparability.VERIFIED),
    }
    values.update(overrides)
    return CellInput(**values)


def _row(**values: str) -> dict[str, str]:
    return {"artifact_sha256": "a" * 64, **values}


def test_critical_break_is_independent_of_the_overall_rating():
    cell = assess_cell(
        _cell(), _row(**{**COMPLETE, "rating_1_to_5": "5", "critical_identity_break": "yes"})
    )
    assert cell.state is AssessmentState.IDENTITY_CONCERN
    assert cell.critical_break == "yes" and cell.evidence.overall == 5


def test_excellent_motion_with_poor_identity_and_the_reverse_both_stand():
    moves_wrong_subject = assess_cell(
        _cell(),
        _row(
            **{
                **COMPLETE,
                "requested_action": "achieved",
                "subject_stability_1_to_5": "1",
                "critical_identity_break": "yes",
            }
        ),
    )
    stable_but_frozen = assess_cell(
        _cell(),
        _row(
            **{
                **COMPLETE,
                "requested_action": "not_achieved",
                "source_fidelity_1_to_5": "5",
                "subject_stability_1_to_5": "5",
            }
        ),
    )
    assert moves_wrong_subject.evidence.requested_action == "achieved"
    assert moves_wrong_subject.state is AssessmentState.IDENTITY_CONCERN
    assert (
        stable_but_frozen.state is AssessmentState.REVIEWED
    )  # a complete review, not a motion success
    assert stable_but_frozen.evidence.requested_action == "not_achieved"


def test_unreviewed_and_incomplete_reviews_are_never_passing():
    assert assess_cell(_cell(), _row()).state is AssessmentState.UNREVIEWED
    partial = assess_cell(_cell(), _row(source_fidelity_1_to_5="5"))
    assert partial.state is AssessmentState.PARTIAL and not partial.complete
    assert any("Subject stability" in reason for reason in partial.reasons)
    cannot = assess_cell(_cell(), _row(**{**COMPLETE, "critical_identity_break": "cannot_assess"}))
    assert cannot.state is AssessmentState.PARTIAL


def test_the_projection_is_deterministic():
    manifest = {
        "suite": {"baseline_arm": "base", "seed": 1},
        "cases": [{"case_id": "c"}],
        "arms": [{"arm_id": "base"}, {"arm_id": "cand"}],
        "jobs": [
            {"case_id": "c", "arm_id": a, "job_id": f"j-{a}", "seed": 1} for a in ("base", "cand")
        ],
    }
    cells = [_cell(arm_id=a, job_id=f"j-{a}") for a in ("base", "cand")]
    rows = {("c", a, f"j-{a}"): _row(**COMPLETE) for a in ("base", "cand")}
    assert project_assessment(manifest, cells, rows) == project_assessment(manifest, cells, rows)


# ------------------------------------------------------------------ B. source and artifact identity


def test_a_pinned_source_verifies_and_a_missing_or_changed_one_is_reported(tmp_path):
    image = tmp_path / "ref.png"
    image.write_bytes(b"original")
    sha = hashlib.sha256(b"original").hexdigest()
    case = {"case_id": "c", "image": str(image), "image_sha256": sha}

    assert verify_source(case).status is SourceStatus.VERIFIED
    image.write_bytes(b"swapped")  # same path, different bytes
    changed = verify_source(case)
    assert changed.status is SourceStatus.MISMATCH and not changed.displayable
    image.unlink()
    assert verify_source(case).status is SourceStatus.MISSING
    assert (
        verify_source({**case, "image": "ref.png"}).status is SourceStatus.MISSING
    )  # never searched for
    assert (
        verify_source({"case_id": "c", "image": str(tmp_path / "x.png")}).status
        is SourceStatus.MISSING
    )
    image.write_bytes(b"original")
    assert verify_source({**case, "image_sha256": ""}).status is SourceStatus.UNPINNED


def test_a_rating_binds_to_the_clip_bytes_and_a_replaced_clip_does_not_inherit_it(run):
    run.build()
    run.rate(0, **COMPLETE)
    first = run.build()
    reviewed = first.assessment.cell("portrait", "base")
    assert reviewed.state is AssessmentState.REVIEWED and reviewed.provenance is Provenance.BOUND
    bound = run.rows()[0]["artifact_sha256"]
    assert bound == hashlib.sha256(run.clips[run.ids[0]].read_bytes()).hexdigest()

    run.clips[run.ids[0]].write_bytes(b"a different clip under the same path")
    second = run.build()

    stale = second.assessment.cell("portrait", "base")
    assert stale.state is AssessmentState.STALE_ARTIFACT and stale.provenance is Provenance.STALE
    assert not stale.counts and stale.bound_sha256 == bound != stale.current_sha256
    assert run.rows()[0]["artifact_sha256"] == bound  # never silently re-bound
    assert run.rows()[0]["source_fidelity_1_to_5"] == "4"  # history kept
    assert second.assessment.arms[0].identity_reviewed_cases == 0

    run.rate(0, artifact_sha256="rebind")
    third = run.build()
    assert third.assessment.cell("portrait", "base").state is AssessmentState.REVIEWED
    assert run.rows()[0]["artifact_sha256"] == stale.current_sha256


def test_an_unchanged_clip_keeps_its_review_across_rebuilds(run):
    run.build()
    run.rate(0, **COMPLETE)
    run.build()
    again = run.build()
    assert again.assessment.cell("portrait", "base").state is AssessmentState.REVIEWED


def test_missing_and_unlisted_clips_are_unreviewable_and_lookalikes_are_not_arms(run):
    run.clips[run.ids[1]].unlink()
    lookalike = run.tmp / "clips" / "base_lookalike.mp4"
    lookalike.write_bytes(b"x")
    report = build = run.build()
    cand = report.assessment.cell("portrait", "cand")
    assert cand.state is AssessmentState.UNAVAILABLE and not cand.counts
    assert [
        c.job_id for c in build.cells
    ] == run.ids  # membership is the manifest's job ids, never filenames
    assert run.rows()[1]["artifact_sha256"] == ""


def test_a_job_that_does_not_match_the_manifest_is_incomparable(run):
    other = _Run(run.tmp / "other", seed=7)  # a different seed and source, same NJR shape
    swapped = [other.ids[0], run.ids[1]]
    run.repo = (
        other.repo
    )  # the repository now holds other's job under a manifest id it does not own
    run.ids = swapped
    run.clips[swapped[0]] = other.clips[other.ids[0]]
    run.write_manifest()

    report = run.build()

    base = report.assessment.cell("portrait", "base")
    assert base.identity.status is Comparability.INCOMPARABLE
    assert base.state is AssessmentState.INCOMPARABLE
    assert any("seed" in f or "source image" in f for f in base.identity.findings)
    assert report.assessment.comparison("portrait", "cand").verdict is Verdict.INCOMPARABLE


def test_a_changed_source_image_makes_the_case_incomparable_and_is_not_displayed(run):
    run.source.write_bytes(b"not the image the suite was admitted with")
    # The manifest still claims the admitted digest.
    manifest = json.loads((run.run_dir / RUN_MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["cases"][0]["image_sha256"] = "0" * 64
    (run.run_dir / RUN_MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    report = run.build()

    assert report.sources["portrait"].status is SourceStatus.MISMATCH
    page = (run.run_dir / REPORT_FILE).read_text(encoding="utf-8")
    assert "<img" not in page and "source image: mismatch" in page
    assert report.assessment.cell("portrait", "base").state is AssessmentState.INCOMPARABLE


def test_a_missing_manifest_seed_or_manifest_contradiction_is_not_a_controlled_pair(run):
    manifest = json.loads((run.run_dir / RUN_MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["jobs"][1]["seed"] = 1
    (run.run_dir / RUN_MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    report = run.build()
    assert report.assessment.comparison("portrait", "cand").verdict is Verdict.INCOMPARABLE


def test_a_verified_pair_needs_the_stored_job_snapshots(run):
    report = run.build()
    pair = report.assessment.comparison("portrait", "cand")
    assert pair.comparability is Comparability.VERIFIED  # real NJRs agree with the manifest
    from types import SimpleNamespace

    from src.queue.job_history_store import JobHistoryEntry

    class _NoSnapshots:
        def get_job(self, job_id):
            entry = run.repo.get_job(job_id)
            return JobHistoryEntry(**{**entry.__dict__, "snapshot": None})

    again = build_eval_report(
        run.run_dir,
        _NoSnapshots(),
        measure=lambda path, cancel=None: ClipMeasurement(
            path=path, ok=True, metrics=_metrics(3.0)
        ),
    )
    assert (
        again.assessment.comparison("portrait", "cand").comparability
        is Comparability.NOT_FULLY_VERIFIED
    )
    assert isinstance(SimpleNamespace(), object)


# ------------------------------------------------------------------ C. report and baseline


def _pair(base: dict[str, str], cand: dict[str, str], *, flags=(), status=Comparability.VERIFIED):
    manifest = {
        "suite": {"baseline_arm": "base", "seed": 1},
        "cases": [{"case_id": "c"}],
        "arms": [{"arm_id": "base"}, {"arm_id": "cand"}],
        "jobs": [
            {"case_id": "c", "arm_id": a, "job_id": f"j-{a}", "seed": 1} for a in ("base", "cand")
        ],
    }
    cells = [
        _cell(arm_id="base", job_id="j-base"),
        _cell(arm_id="cand", job_id="j-cand", flags=tuple(flags), identity=CellIdentity(status)),
    ]
    rows = {("c", "base", "j-base"): _row(**base), ("c", "cand", "j-cand"): _row(**cand)}
    return project_assessment(manifest, cells, rows)


def test_equal_lower_and_higher_candidate_ratings_report_zero_regression_improvement():
    equal = _pair(COMPLETE, COMPLETE).comparison("c", "cand")
    assert (
        equal.verdict is Verdict.NO_DIFFERENCE
        and equal.differences["subject_stability_1_to_5"] == 0
    )

    worse = _pair(COMPLETE, {**COMPLETE, "subject_stability_1_to_5": "2"}).comparison("c", "cand")
    assert (
        worse.verdict is Verdict.REGRESSION and worse.differences["subject_stability_1_to_5"] == -2
    )
    assert worse.material

    better = _pair(COMPLETE, {**COMPLETE, "source_fidelity_1_to_5": "5"}).comparison("c", "cand")
    assert (
        better.verdict is Verdict.IMPROVEMENT and better.differences["source_fidelity_1_to_5"] == 1
    )
    assert not better.material

    mixed = _pair(
        COMPLETE, {**COMPLETE, "source_fidelity_1_to_5": "5", "subject_stability_1_to_5": "3"}
    )
    assert mixed.comparison("c", "cand").verdict is Verdict.MIXED


def test_a_missing_baseline_review_is_insufficient_not_a_win():
    result = _pair({}, COMPLETE)
    pair = result.comparison("c", "cand")
    assert pair.verdict is Verdict.INSUFFICIENT
    assert result.readiness is Readiness.INSUFFICIENT
    assert pair.differences["subject_stability_1_to_5"] is None


def test_a_critical_break_stays_visible_even_when_the_overall_rating_is_high():
    result = _pair(COMPLETE, {**COMPLETE, "rating_1_to_5": "5", "critical_identity_break": "yes"})
    pair = result.comparison("c", "cand")
    assert pair.verdict is Verdict.REGRESSION and pair.material
    assert pair.critical_break == ("no", "yes")
    assert result.readiness is Readiness.CONCERNS
    assert result.arms[1].critical_identity_failures == 1


def test_numeric_flags_never_override_the_operators_judgment():
    result = _pair(COMPLETE, COMPLETE, flags=("less than half the baseline motion",))
    pair = result.comparison("c", "cand")
    assert pair.verdict is Verdict.NO_DIFFERENCE and pair.numeric_flags
    assert result.readiness is Readiness.READY  # a flag is a prompt to look, not a verdict
    assert result.arms[1].numeric_flagged == 1


def test_an_unverified_case_does_not_contribute_to_verified_comparisons():
    result = _pair(COMPLETE, COMPLETE, status=Comparability.NOT_FULLY_VERIFIED)
    assert result.comparison("c", "cand").verdict is Verdict.INSUFFICIENT
    assert result.arms[1].without_verified_baseline == 1
    assert result.readiness is Readiness.INSUFFICIENT


def test_coverage_counts_only_valid_bound_assessments():
    manifest = {
        "suite": {"baseline_arm": "base", "seed": 1},
        "cases": [{"case_id": c} for c in "xyz"],
        "arms": [{"arm_id": "base"}, {"arm_id": "cand"}],
        "jobs": [
            {"case_id": c, "arm_id": a, "job_id": f"{a}-{c}", "seed": 1}
            for c in "xyz"
            for a in ("base", "cand")
        ],
    }
    cells = [_cell(case_id=c, arm_id=a, job_id=f"{a}-{c}") for c in "xyz" for a in ("base", "cand")]
    rows = {
        ("x", "cand", "cand-x"): _row(**COMPLETE),
        ("y", "cand", "cand-y"): {"source_fidelity_1_to_5": "5"},  # legacy: no digest
        ("z", "cand", "cand-z"): _row(
            **{**COMPLETE, "artifact_sha256": "b" * 64}
        ),  # bound to other bytes
    }
    summary = project_assessment(manifest, cells, rows).arms[1]
    assert summary.applicable_cases == 3
    assert summary.identity_reviewed_cases == 1
    assert summary.valid_source_fidelity == 1 and summary.source_fidelity_counts[4] == 1
    assert summary.states["legacy_unverified"] == 1 and summary.states["stale_artifact"] == 1


def test_legacy_rating_without_a_digest_is_kept_but_not_counted_as_verified():
    cell = assess_cell(_cell(), {**COMPLETE})
    assert cell.state is AssessmentState.LEGACY_UNVERIFIED and not cell.counts
    assert cell.evidence.overall == 4  # the history is still there


def test_the_page_shows_source_arms_ratings_and_escapes_operator_text(run):
    run.build()
    run.rate(
        0,
        **COMPLETE,
        failure_categories="face_or_identity_drift",
        first_failure_seconds="1.5",
        notes="<script>alert(1)</script> & worse",
    )
    run.build()
    page = (run.run_dir / REPORT_FILE).read_text(encoding="utf-8")

    assert run.source.resolve().as_uri() in page and "<img" in page
    assert "Baseline (baseline)" in page and "Candidate" in page
    assert "Face or identity drift" in page and "1.5 s" in page
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "READY FOR OWNER REVIEW" not in page  # one arm reviewed, the candidate is not
    assert "INSUFFICIENT EVIDENCE" in page and "not an approval" in page
    assert "first 120 frames" in page


def test_sfw_mode_hides_notes_prompt_and_source_image_and_says_what_it_does_not_cover(run):
    run.build()
    run.rate(0, **COMPLETE, notes="private detail")
    run.build(show_prompts=False)
    page = (run.run_dir / REPORT_FILE).read_text(encoding="utf-8")
    assert "private detail" not in page and run.prompt not in page
    assert "<img" not in page and "hidden in SFW mode" in page
    assert "does not screen the embedded clips" in page
    payload = json.loads((run.run_dir / METRICS_FILE).read_text(encoding="utf-8"))
    assert "private detail" not in json.dumps(payload) and run.prompt not in json.dumps(payload)


def test_the_assessment_never_ranks_or_promotes(run):
    run.build()
    run.rate(0, **COMPLETE)
    run.rate(1, **{**COMPLETE, "source_fidelity_1_to_5": "5"})
    run.build()
    text = (run.run_dir / METRICS_FILE).read_text(encoding="utf-8") + (
        run.run_dir / REPORT_FILE
    ).read_text(encoding="utf-8")
    text = text.lower().replace("no arm is ranked or promoted", "")
    for word in ("winner", "best arm", "promote ", "recommended arm", "approved"):
        assert word not in text


# ------------------------------------------------------------------ D. persistence


LEGACY_HEADER = "case_id,arm_id,job_id,rating_1_to_5,requested_action,notes\n"


def test_a_six_column_file_converts_without_losing_values_notes_or_unknown_columns(run):
    run.ratings_path.write_bytes(
        (
            "case_id,arm_id,job_id,rating_1_to_5,requested_action,notes,reviewer\n"
            f'portrait,base,{run.ids[0]},4,achieved,"line one\nline two, with comma",rob\n'
            f"portrait,cand,{run.ids[1]},,,,\n"
            "old,gone,job-removed,2,not_achieved,kept anyway,rob\n"
        ).encode()
    )
    original = run.ratings_path.read_bytes()

    report = run.build()

    rows = {r["job_id"]: r for r in run.rows()}
    assert rows[run.ids[0]]["notes"] == "line one\nline two, with comma"
    assert rows[run.ids[0]]["reviewer"] == "rob" and rows[run.ids[0]]["rating_1_to_5"] == "4"
    assert rows["job-removed"]["notes"] == "kept anyway"  # an orphan row is carried, not dropped
    assert list(run.rows()[0])[:6] == list(store.LEGACY_COLUMNS)  # old positions unchanged
    assert report.recovery_copy is not None and report.recovery_copy.read_bytes() == original
    # The unrated-by-digest row is legacy: kept, labelled, not counted.
    assert report.assessment.cell("portrait", "base").state is AssessmentState.LEGACY_UNVERIFIED
    assert rows[run.ids[0]]["artifact_sha256"] == ""
    assert rows[run.ids[1]]["artifact_sha256"] != ""  # an untouched row is stamped


def test_a_second_rebuild_makes_no_second_recovery_copy_and_does_not_touch_the_file(run):
    run.ratings_path.write_text(
        LEGACY_HEADER + f"portrait,base,{run.ids[0]},4,achieved,fine\n", encoding="utf-8"
    )
    run.build()
    copies = sorted(run.run_dir.glob("ratings.csv.legacy-*.bak"))
    assert len(copies) == 1
    before = (run.ratings_path.read_bytes(), run.ratings_path.stat().st_mtime_ns)
    run.build()
    assert sorted(run.run_dir.glob("ratings.csv.legacy-*.bak")) == copies
    assert (run.ratings_path.read_bytes(), run.ratings_path.stat().st_mtime_ns) == before


@pytest.mark.parametrize(
    "content",
    [
        b"\xff\xfe\x00bad",  # not UTF-8
        b"job,note\n1,2\n",  # no usable header
        b"case_id,arm_id,job_id\na,b,c,extra\n",  # more fields than the header
        b'case_id,arm_id,job_id,notes\na,b,c,"unterminated\n',
        b"case_id,arm_id,job_id\na,b,c\na,b,c\n",  # duplicate key
    ],
)
def test_a_malformed_ratings_file_is_never_overwritten(run, content):
    run.ratings_path.write_bytes(content)
    with pytest.raises(EvalReportError):
        run.build()
    assert run.ratings_path.read_bytes() == content
    assert not (run.run_dir / REPORT_FILE).exists() and not (run.run_dir / METRICS_FILE).exists()


def test_an_oversized_ratings_file_is_refused(run, monkeypatch):
    monkeypatch.setattr(store, "MAX_RATINGS_BYTES", 10)
    run.ratings_path.write_text(LEGACY_HEADER + "a,b,c,,,x\n", encoding="utf-8")
    with pytest.raises(EvalReportError, match="larger than"):
        run.build()


def test_an_interrupted_write_preserves_the_previous_valid_file(run, monkeypatch):
    run.build()
    run.rate(0, **COMPLETE)
    before = run.ratings_path.read_bytes()
    run.rate(0, notes="edit made after the first build")
    edited = run.ratings_path.read_bytes()
    assert edited != before

    run.clips[run.ids[1]].write_bytes(b"a changed clip, so a rewrite is needed")
    run.rate(1, artifact_sha256="rebind")
    pending = run.ratings_path.read_bytes()

    def broken_replace(*_args, **_kwargs):
        raise PermissionError("simulated crash during replace")

    monkeypatch.setattr("src.utils.atomic_io.os.replace", broken_replace)
    monkeypatch.setattr("src.utils.atomic_io._REPLACE_BACKOFF_S", 0)
    with pytest.raises(EvalReportError):
        run.build()
    assert run.ratings_path.read_bytes() == pending
    assert not list(run.run_dir.glob("*.tmp"))


def test_a_file_edited_during_the_rebuild_is_not_overwritten(run, monkeypatch):
    run.build()
    loaded = store.load_ratings(run.ratings_path)
    rows = store.merge_rows(
        loaded, [((r["case_id"], r["arm_id"], r["job_id"]), "c" * 64) for r in loaded.rows]
    )
    for row in rows:
        row["notes"] = "new"
    run.ratings_path.write_text(
        run.ratings_path.read_text(encoding="utf-8").replace(",,,,", ",,,edited,", 1),
        encoding="utf-8",
    )
    with pytest.raises(store.RatingsFileError, match="changed while"):
        store.write_ratings(loaded, store.output_header(loaded), rows)


def test_a_failed_read_back_is_an_error_not_a_success(run, monkeypatch):
    real = store.atomic_write_bytes

    def corrupting(path, data, **kwargs):
        return real(path, data.replace(b"portrait", b"portrai7"), **kwargs)

    monkeypatch.setattr(store, "atomic_write_bytes", corrupting)
    with pytest.raises(EvalReportError, match="read back"):
        run.build()


def test_operator_edits_to_a_rebuild_survive_a_failed_report_write(run, monkeypatch):
    run.build()
    run.rate(0, **COMPLETE, notes="kept")
    monkeypatch.setattr(
        "src.video.video_eval_report.atomic_write_bytes",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(EvalReportError):
        run.build()
    assert {r["job_id"]: r["notes"] for r in run.rows()}[run.ids[0]] == "kept"


def test_digest_stamping_rules():
    row = {"case_id": "c", "arm_id": "a", "job_id": "j"}
    assert store.bind_artifact(dict(row), "d" * 64)["artifact_sha256"] == "d" * 64
    reviewed = {**row, "source_fidelity_1_to_5": "4"}
    assert store.bind_artifact(dict(reviewed), "d" * 64).get("artifact_sha256", "") == ""
    held = {**row, "artifact_sha256": "e" * 64}
    assert store.bind_artifact(dict(held), "d" * 64)["artifact_sha256"] == "e" * 64
    assert (
        store.bind_artifact({**reviewed, "artifact_sha256": "REBIND"}, "d" * 64)["artifact_sha256"]
        == "d" * 64
    )
    assert store.bind_artifact(dict(row), None).get("artifact_sha256", "") == ""


# ------------------------------------------------------------------ E. architecture and safety


def test_building_a_report_submits_nothing_starts_nothing_and_leaves_originals_alone(run):
    guarded = {
        run.source: run.source.read_bytes(),
        **{p: p.read_bytes() for p in run.clips.values()},
    }

    class _Repo:
        """Only ``get_job`` exists: any queue, submit or runtime call would raise AttributeError."""

        def get_job(self, job_id):
            return run.repo.get_job(job_id)

    report = build_eval_report(
        run.run_dir,
        _Repo(),
        measure=lambda path, cancel=None: ClipMeasurement(
            path=path, ok=True, metrics=_metrics(3.0)
        ),
    )
    assert report.measured == 2
    assert all(path.read_bytes() == data for path, data in guarded.items())
    written = {p.name for p in run.run_dir.iterdir()}
    assert written == {RUN_MANIFEST_NAME, RATINGS_FILE, METRICS_FILE, REPORT_FILE}
    assert not (run.tmp / "learning_records.jsonl").exists()


def test_the_new_modules_have_no_learning_gui_or_network_dependencies():
    root = Path(__file__).resolve().parents[2] / "src" / "video"
    forbidden = (
        "src.learning",
        "src.gui",
        "src.controller",
        "requests",
        "urllib",
        "socket",
        "subprocess",
        "sqlite3",
    )
    for name in (
        "video_eval_rubric",
        "video_eval_ratings_store",
        "video_eval_identity",
        "video_eval_assessment",
        "video_eval_assessment_html",
    ):
        source = (root / f"{name}.py").read_text(encoding="utf-8")
        imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
        assert not [line for line in imports if any(token in line for token in forbidden)], name


def test_cancellation_stops_hashing_and_the_report(run, tmp_path):
    event = threading.Event()
    big = tmp_path / "big.bin"
    big.write_bytes(os.urandom(3 * 1024 * 1024))
    event.set()
    with pytest.raises(EvalCancelled):
        hash_artifact(big, cancel=event)
    with pytest.raises(EvalReportError, match="cancelled"):
        run.build(cancel=event)
    with pytest.raises(ArtifactUnhashable):
        hash_artifact(big, max_bytes=1024)


def test_the_report_cancels_between_clips(run):
    event = threading.Event()
    calls: list[str] = []

    def measure(path, cancel=None):
        calls.append(str(path))
        event.set()
        return ClipMeasurement(path=path, ok=True, metrics=_metrics(3.0))

    with pytest.raises(EvalReportError, match="cancelled"):
        run.build(measure=measure, cancel=event)
    assert len(calls) == 1
    assert not (run.run_dir / REPORT_FILE).exists()


def test_the_score_vocabulary_matches_the_documented_columns():
    assert SCORE_COLUMNS == (
        "source_fidelity_1_to_5",
        "subject_stability_1_to_5",
        "temporal_continuity_1_to_5",
        "anatomy_integrity_1_to_5",
        "scene_stability_1_to_5",
    )
    assert set(SCORE_COLUMNS) <= set(store.RATING_COLUMNS)
