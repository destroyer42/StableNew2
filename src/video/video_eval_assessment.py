"""Pure identity and continuity assessment of an eval run (PR-VID-QUALITY-351).

``project_assessment`` turns recorded facts and the operator's validated ``ratings.csv`` rows into per-cell
states, per-case baseline comparisons, per-arm summaries and a bounded readiness conclusion. It reads no
file, hashes nothing and writes nothing, so equal inputs always give equal output.

What it never does: pick a best arm, promote a workflow, write a Learning recommendation, treat a missing or
unreviewed clip as passing, or read identity out of the numeric metrics. Ratings are ordinal; differences
are counted as points on the 1-5 anchors, not as probabilities. READY FOR OWNER REVIEW is not approval.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from src.video.video_eval_identity import CellIdentity, Comparability
from src.video.video_eval_rubric import (
    ACTION_KEYS,
    CONCERN_SCORE,
    IDENTITY_COLUMNS,
    SCORE_COLUMNS,
    RatingEvidence,
    parse_rating_row,
)

#: A candidate that rates this many points (or more) below the baseline on an identity dimension is a material regression.
MATERIAL_DROP = 2


class AssessmentState(str, Enum):
    UNREVIEWED = "unreviewed"
    PARTIAL = "partial"
    REVIEWED = "reviewed"
    IDENTITY_CONCERN = "identity_concern"
    LEGACY_UNVERIFIED = "legacy_unverified"
    STALE_ARTIFACT = "stale_artifact"
    UNAVAILABLE = "unavailable"
    INCOMPARABLE = "incomparable"


class Provenance(str, Enum):
    NONE = "none"  # nothing rated
    BOUND = "bound"  # rated against the current clip bytes
    LEGACY = "legacy"  # rated, but no artifact digest was recorded
    STALE = "stale"  # rated against bytes that are no longer the recorded clip
    UNBINDABLE = "unbindable"  # the clip cannot be hashed or is not available


class Verdict(str, Enum):
    INSUFFICIENT = "insufficient_evidence"
    INCOMPARABLE = "incomparable"
    REGRESSION = "identity_regression"
    IMPROVEMENT = "identity_improvement"
    MIXED = "mixed"
    NO_DIFFERENCE = "no_identity_difference"


class Readiness(str, Enum):
    INSUFFICIENT = "INSUFFICIENT EVIDENCE"
    CONCERNS = "IDENTITY CONCERNS"
    READY = "READY FOR OWNER REVIEW"


@dataclass(frozen=True)
class CellInput:
    """What the report knows about one (case, arm) clip, independent of the ratings."""

    case_id: str
    arm_id: str
    job_id: str
    job_state: str
    clip_available: bool
    measured: bool
    duration_seconds: float | None
    current_sha256: str | None
    identity: CellIdentity
    flags: tuple[str, ...] = ()
    source_available: bool = True


@dataclass(frozen=True)
class CellAssessment:
    case_id: str
    arm_id: str
    job_id: str
    state: AssessmentState
    provenance: Provenance
    reasons: tuple[str, ...]
    evidence: RatingEvidence
    identity: CellIdentity
    measured: bool
    flags: tuple[str, ...]
    current_sha256: str | None = None
    bound_sha256: str | None = None

    @property
    def counts(self) -> bool:
        """Its individual judgments are bound to the current clip bytes and may be counted."""

        return self.provenance is Provenance.BOUND and self.state in (
            AssessmentState.REVIEWED,
            AssessmentState.PARTIAL,
            AssessmentState.IDENTITY_CONCERN,
        )

    @property
    def complete(self) -> bool:
        return self.counts and self.evidence.complete

    def score(self, column: str) -> int | None:
        return self.evidence.scores.get(column) if self.counts else None

    @property
    def critical_break(self) -> str | None:
        return self.evidence.critical_identity_break if self.counts else None


def assess_cell(cell: CellInput, row: Mapping[str, str] | None) -> CellAssessment:
    """One cell's state from its recorded facts and its ``ratings.csv`` row (already digest-stamped)."""

    row = row or {}
    evidence = parse_rating_row(row, duration_seconds=cell.duration_seconds)
    bound = (row.get("artifact_sha256") or "").strip().lower()
    current = cell.current_sha256

    def result(state: AssessmentState, provenance: Provenance, *reasons: str) -> CellAssessment:
        return CellAssessment(
            cell.case_id,
            cell.arm_id,
            cell.job_id,
            state,
            provenance,
            tuple(reasons),
            evidence,
            cell.identity,
            cell.measured,
            cell.flags,
            current,
            bound or None,
        )

    if not cell.clip_available or current is None:
        return result(
            AssessmentState.UNAVAILABLE,
            Provenance.UNBINDABLE,
            f"no reviewable clip (job {cell.job_state})",
        )
    if not cell.source_available:
        return result(
            AssessmentState.UNAVAILABLE, Provenance.UNBINDABLE, "the source image is unavailable"
        )
    if bound and bound != current:
        return result(
            AssessmentState.STALE_ARTIFACT,
            Provenance.STALE,
            "the clip bytes changed after this row was bound; watch the current clip and type "
            "'rebind' in artifact_sha256 to review it",
        )
    if evidence.has_content and not bound:
        return result(
            AssessmentState.LEGACY_UNVERIFIED,
            Provenance.LEGACY,
            "rated before artifact identity was recorded; not counted as verified identity evidence "
            "(type 'rebind' in artifact_sha256 after re-watching the current clip)",
        )
    provenance = Provenance.BOUND if evidence.has_content else Provenance.NONE
    if cell.identity.status is Comparability.INCOMPARABLE:
        return result(AssessmentState.INCOMPARABLE, provenance, *cell.identity.findings)
    if not evidence.has_content:
        return result(AssessmentState.UNREVIEWED, provenance, "not reviewed yet")
    if evidence.critical_identity_break == "yes":
        return result(AssessmentState.IDENTITY_CONCERN, provenance, *evidence.issues)
    if evidence.complete:
        return result(AssessmentState.REVIEWED, provenance)
    gaps = [f"missing: {gap}" for gap in evidence.missing()]
    return result(AssessmentState.PARTIAL, provenance, *evidence.issues, *gaps)


@dataclass(frozen=True)
class PairComparison:
    case_id: str
    baseline_arm: str
    candidate_arm: str
    verdict: Verdict
    comparability: Comparability
    differences: Mapping[str, int | None]
    requested_action: tuple[str | None, str | None]
    critical_break: tuple[str | None, str | None]
    numeric_flags: tuple[str, ...]
    material: bool
    reasons: tuple[str, ...] = ()


def _pair_comparability(
    base: CellAssessment,
    cand: CellAssessment,
    base_job: Mapping[str, Any],
    cand_job: Mapping[str, Any],
) -> tuple[Comparability, tuple[str, ...]]:
    statuses = (base.identity.status, cand.identity.status)
    findings = tuple(dict.fromkeys((*base.identity.findings, *cand.identity.findings)))
    if Comparability.INCOMPARABLE in statuses:
        return Comparability.INCOMPARABLE, findings
    seeds = (base_job.get("seed"), cand_job.get("seed"))
    if seeds[0] != seeds[1]:
        return Comparability.INCOMPARABLE, (
            *findings,
            f"the arms ran with different seeds ({seeds[0]} vs {seeds[1]})",
        )
    if Comparability.NOT_FULLY_VERIFIED in statuses:
        return Comparability.NOT_FULLY_VERIFIED, findings
    if seeds[0] is None:
        return Comparability.NOT_FULLY_VERIFIED, (
            *findings,
            "the manifest records no seed for the pair",
        )
    return Comparability.VERIFIED, ()


def compare_pair(
    base: CellAssessment,
    cand: CellAssessment,
    base_job: Mapping[str, Any],
    cand_job: Mapping[str, Any],
) -> PairComparison:
    comparability, findings = _pair_comparability(base, cand, base_job, cand_job)
    differences: dict[str, int | None] = {}
    for column in SCORE_COLUMNS:
        a, b = base.score(column), cand.score(column)
        differences[column] = None if a is None or b is None else b - a
    action = (
        base.evidence.requested_action if base.counts else None,
        cand.evidence.requested_action if cand.counts else None,
    )
    breaks = (base.critical_break, cand.critical_break)
    common: dict[str, Any] = {
        "case_id": cand.case_id,
        "baseline_arm": base.arm_id,
        "candidate_arm": cand.arm_id,
        "differences": differences,
        "requested_action": action,
        "critical_break": breaks,
        "numeric_flags": cand.flags,
    }
    if comparability is Comparability.INCOMPARABLE:
        return PairComparison(
            verdict=Verdict.INCOMPARABLE,
            comparability=comparability,
            material=False,
            reasons=findings,
            **common,
        )
    gaps = [f"{cell.arm_id}: {cell.state.value}" for cell in (base, cand) if not cell.complete]
    if comparability is not Comparability.VERIFIED:
        gaps.append("the pair is not a verified controlled comparison")
        gaps.extend(findings)
    if gaps:
        return PairComparison(
            verdict=Verdict.INSUFFICIENT,
            comparability=comparability,
            material=False,
            reasons=tuple(gaps),
            **common,
        )
    identity = [differences[column] for column in IDENTITY_COLUMNS]
    drops = [-d for d in identity if d is not None and d < 0]
    gains = [d for d in identity if d is not None and d > 0]
    new_break = breaks[1] == "yes" and breaks[0] != "yes"
    cleared_break = breaks[0] == "yes" and breaks[1] == "no"
    regression = bool(drops) or new_break
    improvement = bool(gains) or cleared_break
    material = new_break or any(drop >= MATERIAL_DROP for drop in drops)
    if regression and improvement:
        verdict = Verdict.MIXED
    elif regression:
        verdict = Verdict.REGRESSION
    elif improvement:
        verdict = Verdict.IMPROVEMENT
    else:
        verdict = Verdict.NO_DIFFERENCE
    return PairComparison(verdict=verdict, comparability=comparability, material=material, **common)


@dataclass(frozen=True)
class ArmSummary:
    arm_id: str
    label: str
    is_baseline: bool
    applicable_cases: int
    completed_cases: int
    measurable_cases: int
    identity_reviewed_cases: int
    critical_identity_failures: int
    source_fidelity_counts: Mapping[int, int]
    subject_stability_counts: Mapping[int, int]
    valid_source_fidelity: int
    valid_subject_stability: int
    motion: Mapping[str, int]
    temporal_concerns: int
    scene_concerns: int
    without_verified_baseline: int
    numeric_flagged: int
    states: Mapping[str, int]
    readiness: Readiness | None = None
    readiness_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Assessment:
    cells: tuple[CellAssessment, ...] = ()
    comparisons: tuple[PairComparison, ...] = ()
    arms: tuple[ArmSummary, ...] = ()
    readiness: Readiness = Readiness.INSUFFICIENT
    readiness_reasons: tuple[str, ...] = ()
    baseline_arm: str = ""

    def cell(self, case_id: str, arm_id: str) -> CellAssessment | None:
        return next((c for c in self.cells if (c.case_id, c.arm_id) == (case_id, arm_id)), None)

    def comparison(self, case_id: str, arm_id: str) -> PairComparison | None:
        return next(
            (c for c in self.comparisons if (c.case_id, c.candidate_arm) == (case_id, arm_id)), None
        )


def _histogram(values: Sequence[int]) -> dict[int, int]:
    return {score: sum(1 for value in values if value == score) for score in range(1, 6)}


def _summarize(
    arm: Mapping[str, Any],
    is_baseline: bool,
    cells: Sequence[CellAssessment],
    comparisons: Sequence[PairComparison],
) -> ArmSummary:
    sf = [v for c in cells if (v := c.score("source_fidelity_1_to_5")) is not None]
    ss = [v for c in cells if (v := c.score("subject_stability_1_to_5")) is not None]
    motion = dict.fromkeys(ACTION_KEYS, 0)
    for cell in cells:
        if cell.counts and cell.evidence.requested_action:
            motion[cell.evidence.requested_action] += 1
    states = {state.value: 0 for state in AssessmentState}
    for cell in cells:
        states[cell.state.value] += 1

    def concern(cell: CellAssessment, column: str, category: str) -> bool:
        if not cell.counts:
            return False
        score = cell.score(column)
        return (
            score is not None and score <= CONCERN_SCORE
        ) or category in cell.evidence.failure_categories

    temporal = sum(
        1
        for c in cells
        if concern(c, "temporal_continuity_1_to_5", "temporal_flicker")
        or (c.counts and "motion_freeze" in c.evidence.failure_categories)
    )
    scene = sum(1 for c in cells if concern(c, "scene_stability_1_to_5", "scene_background_drift"))
    unverified_pairs = sum(1 for p in comparisons if p.comparability is not Comparability.VERIFIED)
    return ArmSummary(
        arm_id=str(arm.get("arm_id")),
        label=str(arm.get("label") or arm.get("arm_id")),
        is_baseline=is_baseline,
        applicable_cases=len(cells),
        completed_cases=sum(1 for c in cells if c.current_sha256 is not None),
        measurable_cases=sum(1 for c in cells if c.measured),
        identity_reviewed_cases=sum(1 for c in cells if c.complete),
        critical_identity_failures=sum(1 for c in cells if c.critical_break == "yes"),
        source_fidelity_counts=_histogram(sf),
        subject_stability_counts=_histogram(ss),
        valid_source_fidelity=len(sf),
        valid_subject_stability=len(ss),
        motion=motion,
        temporal_concerns=temporal,
        scene_concerns=scene,
        without_verified_baseline=0 if is_baseline else unverified_pairs,
        numeric_flagged=sum(1 for c in cells if c.flags),
        states=states,
    )


def _candidate_readiness(
    summary: ArmSummary, pairs: Sequence[PairComparison]
) -> tuple[Readiness, tuple[str, ...]]:
    concerns: list[str] = []
    if summary.critical_identity_failures:
        concerns.append(
            f"{summary.critical_identity_failures} clip(s) rated with a critical identity break"
        )
    material = [p.case_id for p in pairs if p.material]
    if material:
        concerns.append(
            "material rated identity regression vs the baseline on " + ", ".join(material)
        )
    if concerns:
        return Readiness.CONCERNS, tuple(concerns)
    short = [p.case_id for p in pairs if p.verdict in (Verdict.INSUFFICIENT, Verdict.INCOMPARABLE)]
    if short or not pairs:
        reasons = (
            ["no cases to compare"]
            if not pairs
            else ["no verified, fully reviewed comparison on " + ", ".join(short)]
        )
        return Readiness.INSUFFICIENT, tuple(reasons)
    return Readiness.READY, (
        "every case has a verified, fully reviewed comparison and no critical break",
    )


def project_assessment(
    manifest: Mapping[str, Any],
    cells: Sequence[CellInput],
    rows: Mapping[tuple[str, str, str], Mapping[str, str]],
) -> Assessment:
    raw_suite = manifest.get("suite")
    suite: Mapping[str, Any] = raw_suite if isinstance(raw_suite, Mapping) else {}
    baseline_arm = str(suite.get("baseline_arm") or "")
    jobs = {
        (str(j.get("case_id")), str(j.get("arm_id"))): j
        for j in manifest.get("jobs", [])
        if isinstance(j, Mapping)
    }
    assessed = tuple(
        assess_cell(cell, rows.get((cell.case_id, cell.arm_id, cell.job_id))) for cell in cells
    )
    by_key = {(a.case_id, a.arm_id): a for a in assessed}
    comparisons: list[PairComparison] = []
    for case in manifest.get("cases", []):
        case_id = str(case.get("case_id"))
        base = by_key.get((case_id, baseline_arm))
        for arm in manifest.get("arms", []):
            arm_id = str(arm.get("arm_id"))
            cand = by_key.get((case_id, arm_id))
            if arm_id == baseline_arm or base is None or cand is None:
                continue
            comparisons.append(
                compare_pair(
                    base,
                    cand,
                    jobs.get((case_id, baseline_arm), {}),
                    jobs.get((case_id, arm_id), {}),
                )
            )
    summaries: list[ArmSummary] = []
    for arm in manifest.get("arms", []):
        arm_id = str(arm.get("arm_id"))
        is_baseline = arm_id == baseline_arm
        arm_cells = [a for a in assessed if a.arm_id == arm_id]
        arm_pairs = [p for p in comparisons if p.candidate_arm == arm_id]
        summary = _summarize(arm, is_baseline, arm_cells, arm_pairs)
        if not is_baseline:
            readiness, reasons = _candidate_readiness(summary, arm_pairs)
            summary = ArmSummary(
                **{**summary.__dict__, "readiness": readiness, "readiness_reasons": reasons}
            )
        summaries.append(summary)
    candidates = [s for s in summaries if not s.is_baseline]
    if any(s.readiness is Readiness.CONCERNS for s in candidates):
        overall = Readiness.CONCERNS
    elif not candidates or any(s.readiness is Readiness.INSUFFICIENT for s in candidates):
        overall = Readiness.INSUFFICIENT
    else:
        overall = Readiness.READY
    reasons = tuple(
        f"{s.arm_id}: {reason}" for s in candidates for reason in s.readiness_reasons
    ) or ("no candidate arm to assess",)
    return Assessment(
        cells=assessed,
        comparisons=tuple(comparisons),
        arms=tuple(summaries),
        readiness=overall,
        readiness_reasons=reasons,
        baseline_arm=baseline_arm,
    )


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(_plain(k)): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def assessment_payload(assessment: Assessment) -> dict[str, Any]:
    """JSON-ready assessment. Operator notes are deliberately left out (they stay in ``ratings.csv``)."""

    cells = []
    for cell in assessment.cells:
        evidence = cell.evidence
        cells.append(
            {
                "case_id": cell.case_id,
                "arm_id": cell.arm_id,
                "job_id": cell.job_id,
                "state": cell.state.value,
                "provenance": cell.provenance.value,
                "reasons": list(cell.reasons),
                "comparability": cell.identity.status.value,
                "comparability_findings": list(cell.identity.findings),
                "artifact_sha256": cell.current_sha256,
                "review_bound_sha256": cell.bound_sha256,
                "ratings": {
                    "overall": evidence.overall,
                    "requested_action": evidence.requested_action,
                    "scores": dict(evidence.scores),
                    "critical_identity_break": evidence.critical_identity_break,
                    "failure_categories": list(evidence.failure_categories),
                    "first_failure_seconds": evidence.first_failure_seconds,
                    "issues": list(evidence.issues),
                }
                if evidence.has_content
                else None,
            }
        )
    return {
        "baseline_arm": assessment.baseline_arm,
        "readiness": assessment.readiness.value,
        "readiness_reasons": list(assessment.readiness_reasons),
        "cells": cells,
        "comparisons": [_plain(asdict(p)) for p in assessment.comparisons],
        "arms": [_plain(asdict(a)) for a in assessment.arms],
    }


__all__ = [
    "assessment_payload",
    "MATERIAL_DROP",
    "ArmSummary",
    "Assessment",
    "AssessmentState",
    "CellAssessment",
    "CellInput",
    "PairComparison",
    "Provenance",
    "Readiness",
    "Verdict",
    "assess_cell",
    "compare_pair",
    "project_assessment",
]
