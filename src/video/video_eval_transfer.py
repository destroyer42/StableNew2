"""Transferability evidence summaries for a controlled-motion eval run (PR-VID-MOTION-410).

How well did a motion transfer? This answers it as counts with their denominators, at the levels the roadmap names
(motion asset, motion category, workflow id and version, source compatibility category, conditioning configuration, arm,
cross-subject group), from the assessed cells of ONE run. It is decision support, never a verdict:

* every percentage names its numerator, its denominator and what the denominator is;
* a missing review is *not rated*, never a failed action; a runtime failure stays in the planned/completed counts;
* one source subject generated repeatedly is repeated generation, not cross-subject transfer: distinct source subjects and
  seeds are counted separately and a group of fewer than ``MIN_DISTINCT_SUBJECTS`` is called out;
* a replay or duplicate (the same inputs and settings, or the same artifact bytes, under two cells) is counted once toward
  rated evidence and listed as excluded, so it cannot raise confidence;
* the readiness states reuse the existing decision-support vocabulary and never promote, rank or qualify anything.

Nothing here writes the Motion Library, a Learning record or a recommendation.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.video.video_eval_assessment import Assessment, CellAssessment, Readiness
from src.video.video_eval_motion import as_mapping, record_identity
from src.video.video_eval_rubric import ACTION_OBSERVED_KEYS, ATTACHMENT_OBSERVED_KEYS

#: Fewest distinct source subjects before a group can be called ready for owner review as transfer evidence.
MIN_DISTINCT_SUBJECTS = 2
LEVELS = (
    "motion_asset",
    "motion_category",
    "workflow",
    "source_compatibility",
    "conditioning",
    "arm",
    "cross_subject",
)
LEVEL_LABELS = {
    "motion_asset": "Motion asset",
    "motion_category": "Motion category",
    "workflow": "Workflow id and version",
    "source_compatibility": "Source compatibility category",
    "conditioning": "Conditioning configuration",
    "arm": "Evaluation arm",
    "cross_subject": "Cross-subject group (one motion, one arm)",
}


@dataclass(frozen=True)
class Ratio:
    """A percentage with its definition. ``value`` is ``None`` (unavailable, not zero) when the denominator is 0."""

    name: str
    numerator: int
    denominator: int
    basis: str

    @property
    def value(self) -> float | None:
        return None if self.denominator == 0 else round(self.numerator / self.denominator, 4)

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "basis": self.basis,
            "value": self.value,
        }


@dataclass(frozen=True)
class TransferGroup:
    level: str
    key: str
    label: str
    planned: int
    completed: int
    failed_or_incomplete: int
    duplicates_excluded: int
    verified_comparable: int
    rated: int
    action: Mapping[str, int]
    attachment: Mapping[str, int]
    fidelity: Mapping[int, int]
    critical_breaks: int
    break_assessed: int
    subjects_evaluated: int
    subjects_rated: int
    seeds: int
    ratios: tuple[Ratio, ...]
    readiness: Readiness
    readiness_reasons: tuple[str, ...]
    notes: tuple[str, ...] = ()
    integrity: Mapping[str, int] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "key": self.key,
            "label": self.label,
            "planned_attempts": self.planned,
            "completed_attempts": self.completed,
            "failed_or_incomplete_attempts": self.failed_or_incomplete,
            "duplicates_excluded": self.duplicates_excluded,
            "verified_comparable": self.verified_comparable,
            "rated": self.rated,
            "action": dict(self.action),
            "subject_attachment": dict(self.attachment),
            "motion_fidelity": {str(score): count for score, count in self.fidelity.items()},
            "critical_identity_breaks": self.critical_breaks,
            "critical_identity_break_assessed": self.break_assessed,
            "distinct_subjects_evaluated": self.subjects_evaluated,
            "distinct_subjects_rated": self.subjects_rated,
            "distinct_seeds": self.seeds,
            "integrity": dict(self.integrity),
            "ratios": [ratio.to_payload() for ratio in self.ratios],
            "readiness": self.readiness.value,
            "readiness_reasons": list(self.readiness_reasons),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class TransferSummary:
    groups: tuple[TransferGroup, ...] = ()
    #: ``case/arm`` of every cell excluded from rated evidence as a replay or duplicate.
    duplicates: tuple[str, ...] = ()

    def level(self, name: str) -> tuple[TransferGroup, ...]:
        return tuple(group for group in self.groups if group.level == name)

    def to_payload(self) -> dict[str, Any]:
        return {
            "min_distinct_subjects": MIN_DISTINCT_SUBJECTS,
            "levels": {name: [g.to_payload() for g in self.level(name)] for name in LEVELS},
            "duplicates_excluded": list(self.duplicates),
            "notes": [
                "Counts come from this run only. Every percentage lists its denominator.",
                "A cell without a review is not rated; it is never counted as a failed action.",
                "Failed, cancelled and incomplete jobs stay in the planned and completed counts.",
                "These are decision-support summaries, not a qualification, ranking or recommendation.",
            ],
        }


@dataclass(frozen=True)
class _Attempt:
    cell: CellAssessment
    asset_key: str
    asset_label: str
    category: str
    workflow: str
    source_compat: str
    conditioning: str
    cross_subject: str
    source_sha: str
    seed: Any
    duplicate: bool = False

    @property
    def completed(self) -> bool:
        return self.cell.current_sha256 is not None

    @property
    def comparable(self) -> bool:
        return self.cell.integrity is not None and self.cell.integrity.comparable

    @property
    def judged(self) -> bool:
        """Unique, counted against the current context and verified comparable: the evidence the ratios use."""

        return not self.duplicate and self.completed and self.cell.motion_counts and self.comparable


def _controls_key(controls: Mapping[str, Any]) -> str:
    items = sorted((str(k), controls[k]) for k in controls if k != "pose_prompt")
    return (
        ", ".join(
            f"{name}={value:g}" if isinstance(value, float) else f"{name}={value}"
            for name, value in items
        )
        or "defaults"
    )


def _attempts(manifest: Mapping[str, Any], assessment: Assessment) -> list[_Attempt]:
    cases = {str(c.get("case_id")): c for c in manifest.get("cases", []) if isinstance(c, Mapping)}
    found: list[_Attempt] = []
    for cell in sorted(assessment.cells, key=lambda c: (c.case_id, c.arm_id, c.job_id)):
        ctx = cell.motion
        if ctx is None:
            continue
        record = cases.get(cell.case_id, {}).get("motion")
        record = record if isinstance(record, Mapping) else {}
        settings = ctx.settings
        controls = as_mapping(settings.get("controls"))
        driving = as_mapping(record.get("driving"))
        library = as_mapping(driving.get("library_asset"))
        notes = as_mapping(record.get("annotations"))
        sha = str(settings.get("driver_original_sha256") or driving.get("sha256") or "")
        label = str(library.get("asset_id") or Path(str(driving.get("path") or "driver")).name)
        found.append(
            _Attempt(
                cell=cell,
                asset_key=sha or label,
                asset_label=label,
                category=str(record.get("category") or "unspecified"),
                workflow=f"{settings.get('workflow_id') or '?'}@{settings.get('workflow_version') or '?'}",
                source_compat=str(notes.get("source_compatibility") or "") or "unannotated",
                conditioning=_controls_key(controls),
                cross_subject=f"{record_identity(record)[:12]}|{cell.arm_id}"
                if record
                else cell.arm_id,
                source_sha=ctx.source_sha256 or cell.case_id,
                seed=settings.get("seed"),
            )
        )
    return _mark_duplicates(found)


def _mark_duplicates(attempts: list[_Attempt]) -> list[_Attempt]:
    """Same inputs and settings, or the same artifact bytes, under two cells: the first counts, the rest are excluded."""

    seen_inputs: set[str] = set()
    seen_artifacts: set[str] = set()
    marked: list[_Attempt] = []
    for attempt in attempts:
        settings = attempt.cell.motion.settings if attempt.cell.motion else {}
        key = hashlib.sha256(
            repr((attempt.source_sha, sorted((k, repr(v)) for k, v in settings.items()))).encode()
        ).hexdigest()
        artifact = attempt.cell.current_sha256
        duplicate = attempt.completed and (
            key in seen_inputs or (artifact in seen_artifacts if artifact else False)
        )
        if attempt.completed:
            seen_inputs.add(key)
            if artifact:
                seen_artifacts.add(artifact)
        marked.append(_Attempt(**{**attempt.__dict__, "duplicate": duplicate}))
    return marked


def _count(values: Sequence[str | int | None], keys: Sequence[Any]) -> dict[Any, int]:
    return {key: sum(1 for value in values if value == key) for key in keys}


def _group(level: str, key: str, label: str, members: Sequence[_Attempt]) -> TransferGroup:
    completed = [m for m in members if m.completed]
    unique = [m for m in completed if not m.duplicate]
    judged = [m for m in members if m.judged]
    action_cells = [m for m in judged if m.cell.evidence.requested_action in ACTION_OBSERVED_KEYS]
    attach_cells = [
        m for m in judged if m.cell.evidence.subject_attachment in ATTACHMENT_OBSERVED_KEYS
    ]
    fidelity_cells = [m for m in judged if m.cell.evidence.motion_fidelity is not None]
    break_cells = [m for m in judged if m.cell.evidence.critical_identity_break in ("yes", "no")]
    rated = [m for m in judged if m.cell.motion_state.value == "reviewed"]
    breaks = sum(1 for m in break_cells if m.cell.evidence.critical_identity_break == "yes")
    subjects_eval = {m.source_sha for m in unique}
    subjects_rated = {m.source_sha for m in judged}
    comparable = [m for m in unique if m.comparable]
    integrity: dict[str, int] = defaultdict(int)
    for member in members:
        if member.cell.integrity is not None:
            integrity[member.cell.integrity.value] += 1
    ratios = (
        Ratio("Attempts completed", len(completed), len(members), "planned attempts in this group"),
        Ratio(
            "Results rated (all three motion judgments)",
            len(rated),
            len(unique),
            "completed, non-duplicate attempts",
        ),
        Ratio(
            "Action achieved",
            sum(1 for m in action_cells if m.cell.evidence.requested_action == "achieved"),
            len(action_cells),
            "rated results with an observed action judgment",
        ),
        Ratio(
            "Action achieved or partially achieved",
            sum(
                1
                for m in action_cells
                if m.cell.evidence.requested_action in ("achieved", "partially_achieved")
            ),
            len(action_cells),
            "rated results with an observed action judgment",
        ),
        Ratio(
            "Intended subject performs the motion",
            sum(1 for m in attach_cells if m.cell.evidence.subject_attachment == "correct_subject"),
            len(attach_cells),
            "rated results with an observed subject-attachment judgment",
        ),
        Ratio(
            "Critical identity break",
            breaks,
            len(break_cells),
            "rated results with a Yes or No identity-break answer",
        ),
    )
    reasons: list[str] = []
    notes: list[str] = []
    failed = len(members) - len(completed)
    if breaks:
        readiness = Readiness.CONCERNS
        reasons.append(f"{breaks} rated result(s) recorded a critical identity break")
    else:
        if failed:
            reasons.append(f"{failed} attempt(s) failed, were cancelled or are not finished")
        if len(comparable) < len(unique):
            reasons.append(
                f"{len(unique) - len(comparable)} result(s) are not verified and comparable"
            )
        if len(rated) < len(unique):
            reasons.append(
                f"{len(unique) - len(rated)} completed result(s) are not fully rated for the current context"
            )
        if len(subjects_rated) < MIN_DISTINCT_SUBJECTS:
            reasons.append(
                f"{len(subjects_rated)} distinct rated source subject(s); at least {MIN_DISTINCT_SUBJECTS} are needed "
                "before this is cross-subject evidence"
            )
        readiness = Readiness.INSUFFICIENT if reasons else Readiness.READY
        if not reasons:
            reasons.append(
                "every attempt completed, verified, rated and no critical break was recorded"
            )
    if len(subjects_eval) < MIN_DISTINCT_SUBJECTS:
        notes.append("one source subject: repeated generation, not cross-subject transfer evidence")
    dupes = sum(1 for m in members if m.duplicate)
    if dupes:
        notes.append(f"{dupes} replay or duplicate result(s) excluded from rated evidence")
    return TransferGroup(
        level=level,
        key=key,
        label=label,
        planned=len(members),
        completed=len(completed),
        failed_or_incomplete=failed,
        duplicates_excluded=dupes,
        verified_comparable=len(comparable),
        rated=len(rated),
        action=_count(
            [m.cell.evidence.requested_action for m in action_cells], ACTION_OBSERVED_KEYS
        ),
        attachment=_count(
            [m.cell.evidence.subject_attachment for m in attach_cells], ATTACHMENT_OBSERVED_KEYS
        ),
        fidelity=_count([m.cell.evidence.motion_fidelity for m in fidelity_cells], (1, 2, 3, 4, 5)),
        critical_breaks=breaks,
        break_assessed=len(break_cells),
        subjects_evaluated=len(subjects_eval),
        subjects_rated=len(subjects_rated),
        seeds=len({m.seed for m in unique if m.seed is not None}),
        ratios=ratios,
        readiness=readiness,
        readiness_reasons=tuple(reasons),
        notes=tuple(notes),
        integrity=dict(integrity),
    )


def summarize_transfer(manifest: Mapping[str, Any], assessment: Assessment) -> TransferSummary:
    """Transferability summaries of every motion cell in ``assessment`` (empty for an ordinary run)."""

    attempts = _attempts(manifest, assessment)
    if not attempts:
        return TransferSummary()
    pick = {
        "motion_asset": lambda a: (a.asset_key, a.asset_label),
        "motion_category": lambda a: (a.category, a.category),
        "workflow": lambda a: (a.workflow, a.workflow),
        "source_compatibility": lambda a: (a.source_compat, a.source_compat),
        "conditioning": lambda a: (a.conditioning, a.conditioning),
        "arm": lambda a: (a.cell.arm_id, a.cell.arm_id),
        "cross_subject": lambda a: (a.cross_subject, a.cross_subject),
    }
    groups: list[TransferGroup] = []
    for level in LEVELS:
        buckets: dict[str, tuple[str, list[_Attempt]]] = {}
        for attempt in attempts:
            key, label = pick[level](attempt)
            buckets.setdefault(key, (label, []))[1].append(attempt)
        groups.extend(
            _group(level, key, label, members) for key, (label, members) in buckets.items()
        )
    duplicates = tuple(f"{a.cell.case_id}/{a.cell.arm_id}" for a in attempts if a.duplicate)
    return TransferSummary(tuple(groups), duplicates)


__all__ = [
    "LEVELS",
    "LEVEL_LABELS",
    "MIN_DISTINCT_SUBJECTS",
    "Ratio",
    "TransferGroup",
    "TransferSummary",
    "summarize_transfer",
]
