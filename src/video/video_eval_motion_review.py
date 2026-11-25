"""Read-only data for reviewing a controlled-motion eval run (PR-VID-MOTION-410).

Builds, from a run's ``run.json`` (what admission froze) and the ``metrics.json`` the report builder wrote (what the files
looked like when it ran), everything the Motion Review window shows for each case: the verified source image, the
**effective driving reference** (the file the model actually consumed, with the original and whether it was prepared) and
each generated result, with its frozen settings, integrity class and rating state.

Nothing is decoded, hashed beyond the small source image, written or queued here. Where the effective driving input cannot
be established, the case says so; the original binding is never substituted for it as if it were verified.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.video.video_eval_identity import SourceStatus, verify_source
from src.video.video_eval_integrity import INTEGRITY_LABELS, IntegrityClass
from src.video.video_eval_motion import MOTION_BLOCK, MOTION_CATEGORY_LABELS, as_mapping
from src.video.video_eval_report import METRICS_FILE, EvalReportError, load_run_manifest

ROLE_SOURCE = "source"
ROLE_DRIVER = "driver"
ROLE_RESULT = "result"


class MotionReviewError(ValueError):
    """The run cannot be reviewed as a motion run (no report yet, no motion cases, unreadable files)."""


@dataclass(frozen=True)
class ReviewRole:
    """One of the three media roles on screen."""

    role: str
    label: str
    path: str | None = None
    #: What "Open original" hands to the system viewer (for a prepared driver, the original clip).
    original_path: str | None = None
    #: The identity statement shown with the media (digests, preparation, limitation).
    note: str = ""
    #: ``True`` only when the file is known to be exactly what was admitted / consumed.
    verified: bool = False


@dataclass(frozen=True)
class ReviewCell:
    arm_id: str
    arm_label: str
    job_id: str
    clip_path: str | None
    state: str
    artifact_sha256: str | None
    integrity: str | None
    integrity_label: str
    motion_state: str
    settings_lines: tuple[str, ...]
    rating_lines: tuple[str, ...]
    flags: tuple[str, ...]
    diagnostic_status: str
    is_baseline: bool = False

    @property
    def playable(self) -> bool:
        return bool(self.clip_path) and self.state == "playable"


@dataclass(frozen=True)
class ReviewCase:
    case_id: str
    category: str
    action: str
    expected_outcome: str
    motion_prompt: str
    source: ReviewRole
    driver: ReviewRole
    cells: tuple[ReviewCell, ...]

    def cell(self, arm_id: str | None) -> ReviewCell | None:
        return next((cell for cell in self.cells if cell.arm_id == arm_id), None)


@dataclass(frozen=True)
class MotionReviewData:
    run_id: str
    suite_id: str
    baseline_arm: str
    generated_at: str
    cases: tuple[ReviewCase, ...]

    def case(self, case_id: str | None) -> ReviewCase | None:
        return next((case for case in self.cases if case.case_id == case_id), None)


def _settings_lines(motion: Mapping[str, Any]) -> tuple[str, ...]:
    controls = as_mapping(motion.get("controls"))
    shown = ", ".join(
        f"{k}={controls[k]:g}" if isinstance(controls[k], float) else f"{k}={controls[k]}"
        for k in sorted(controls)
        if k != "pose_prompt"
    )
    lines = [
        f"{motion.get('workflow_id')} {motion.get('workflow_version')}",
        f"{motion.get('frame_count')} frames at {motion.get('fps')} fps, seed {motion.get('seed')}",
        f"controls: {shown or 'defaults'}",
    ]
    if motion.get("interpolation"):
        lines.append("smoothing (interpolation) was enabled")
    return tuple(lines)


def _rating_lines(entry: Mapping[str, Any] | None) -> tuple[str, ...]:
    ratings = (entry or {}).get("ratings")
    if not isinstance(ratings, Mapping):
        return ("not reviewed",)
    parts = [
        f"action: {ratings.get('requested_action') or 'not assessed'}",
        f"attachment: {ratings.get('subject_attachment') or 'not assessed'}",
        f"fidelity: {ratings.get('motion_fidelity') or 'not assessed'}",
    ]
    return tuple(parts)


def _driver_role(
    case: Mapping[str, Any],
    job_motion: Mapping[str, Any] | None,
    changed: bool,
    missing: bool = False,
) -> ReviewRole:
    motion = as_mapping(case.get(MOTION_BLOCK))
    driving = as_mapping(motion.get("driving"))
    original = str(driving.get("path") or "") or None
    if job_motion is None:
        return ReviewRole(
            ROLE_DRIVER,
            "Driving reference (original binding only)",
            original,
            original,
            "The admitted job recorded no effective driving input, so only the original binding is shown. It is "
            "not verified as what the model consumed.",
            False,
        )
    effective = str(job_motion.get("driver_effective_path") or "") or original
    prepared = bool(job_motion.get("prepared"))
    eff_sha = str(job_motion.get("driver_effective_sha256") or "")[:12]
    orig_sha = str(job_motion.get("driver_original_sha256") or "")[:12]
    note = (
        f"Effective input: the prepared derivative {eff_sha}... (original {orig_sha}...), the file the model consumed."
        if prepared
        else f"Effective input: the original file {orig_sha}... used as bound (not prepared)."
    )
    alignment = job_motion.get("alignment_detail")
    if prepared and alignment:
        note += (
            f" Spatially aligned to this source image: scale {alignment.get('scale')}, shift "
            f"({alignment.get('translate_x')}, {alignment.get('translate_y')}) px"
            + (", mirrored" if alignment.get("mirror") else "")
            + f" (transform {str(alignment.get('transform_sha256') or '')[:12]}...). A preview of the alignment is "
            "not evidence that the generated motion succeeded."
        )
    if changed:
        note += " The file on disk changed after admission; it is not the admitted input."
    if missing:
        note += " The file is missing or unreadable now, so it cannot be shown or verified."
    return ReviewRole(
        ROLE_DRIVER,
        "Driving reference (aligned effective input)"
        if prepared and alignment
        else "Driving reference (effective input)"
        if prepared
        else "Driving reference (original, unprepared)",
        effective,
        str(job_motion.get("driver_original_path") or original) or None,
        note,
        not (changed or missing),
    )


def load_motion_review(
    run_dir: str | Path, cancel: threading.Event | None = None
) -> MotionReviewData:
    """Everything the review window needs, from the files the admission and the report already wrote."""

    folder = Path(run_dir).expanduser()
    try:
        manifest = load_run_manifest(folder)
    except EvalReportError as exc:
        raise MotionReviewError(str(exc)) from exc
    cases = [
        c
        for c in manifest.get("cases", [])
        if isinstance(c, Mapping) and isinstance(c.get(MOTION_BLOCK), Mapping)
    ]
    if not cases:
        raise MotionReviewError("This run has no driving-motion cases; use the ordinary report.")
    try:
        metrics = json.loads((folder / METRICS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MotionReviewError(
            "Build the report for this run first; it records what the files looked like."
        ) from exc
    assessment = metrics.get("identity_assessment") if isinstance(metrics, Mapping) else None
    assessed = {
        (str(c.get("case_id")), str(c.get("arm_id"))): c
        for c in (assessment or {}).get("cells", [])
        if isinstance(c, Mapping)
    }
    reported = {
        (str(c.get("case_id")), str(c.get("arm_id"))): c
        for c in metrics.get("cells", [])
        if isinstance(c, Mapping)
    }
    arms = {str(a.get("arm_id")): a for a in manifest.get("arms", []) if isinstance(a, Mapping)}
    jobs = [j for j in manifest.get("jobs", []) if isinstance(j, Mapping)]
    baseline = str((manifest.get("suite") or {}).get("baseline_arm") or "")
    built: list[ReviewCase] = []
    for case in cases:
        if cancel is not None and cancel.is_set():
            raise MotionReviewError("the review was cancelled")
        case_id = str(case.get("case_id"))
        motion = case[MOTION_BLOCK]
        source_ref = verify_source(case, cancel=cancel)
        source = ReviewRole(
            ROLE_SOURCE,
            "Source image",
            source_ref.path if source_ref.status is SourceStatus.VERIFIED else None,
            source_ref.path or None,
            "Digest matches the admitted suite." if source_ref.displayable else source_ref.message,
            source_ref.displayable,
        )
        case_jobs = [j for j in jobs if str(j.get("case_id")) == case_id]
        job_motion = next(
            (j.get(MOTION_BLOCK) for j in case_jobs if isinstance(j.get(MOTION_BLOCK), Mapping)),
            None,
        )
        driver_labels = ("driving video", "prepared driving video")
        changed = any(
            label in (entry.get("motion") or {}).get("changed_inputs", [])
            for (case_key, _arm), entry in assessed.items()
            if case_key == case_id
            for label in driver_labels
        )
        missing = any(
            label in (entry.get("motion") or {}).get("missing_inputs", [])
            for (case_key, _arm), entry in assessed.items()
            if case_key == case_id
            for label in driver_labels
        )
        cells: list[ReviewCell] = []
        for job in case_jobs:
            arm_id = str(job.get("arm_id"))
            entry = assessed.get((case_id, arm_id))
            cell = reported.get((case_id, arm_id), {})
            motion_entry = as_mapping((entry or {}).get("motion"))
            integrity = motion_entry.get("integrity")
            diagnostic = cell.get("motion_diagnostic")
            cells.append(
                ReviewCell(
                    arm_id=arm_id,
                    arm_label=str(arms.get(arm_id, {}).get("label") or arm_id),
                    job_id=str(job.get("job_id")),
                    clip_path=str(cell.get("path") or "") or None,
                    state=str(cell.get("state") or "unknown"),
                    artifact_sha256=cell.get("artifact_sha256"),
                    integrity=str(integrity) if integrity else None,
                    integrity_label=INTEGRITY_LABELS[IntegrityClass(integrity)]
                    if integrity
                    else "unknown",
                    motion_state=str(motion_entry.get("state") or "unknown"),
                    settings_lines=_settings_lines(job.get(MOTION_BLOCK) or {}),
                    rating_lines=_rating_lines(motion_entry or entry),
                    flags=tuple(str(f) for f in cell.get("flags") or ()),
                    diagnostic_status=str((diagnostic or {}).get("status") or "unavailable"),
                    is_baseline=arm_id == baseline,
                )
            )
        built.append(
            ReviewCase(
                case_id=case_id,
                category=MOTION_CATEGORY_LABELS.get(
                    str(motion.get("category")), str(motion.get("category"))
                ),
                action=str(motion.get("action") or ""),
                expected_outcome=str(motion.get("expected_outcome") or ""),
                motion_prompt=str(motion.get("motion_prompt") or ""),
                source=source,
                driver=_driver_role(
                    case, job_motion if isinstance(job_motion, Mapping) else None, changed, missing
                ),
                cells=tuple(cells),
            )
        )
    return MotionReviewData(
        run_id=str(manifest.get("run_id") or folder.name),
        suite_id=str((manifest.get("suite") or {}).get("suite_id") or ""),
        baseline_arm=baseline,
        generated_at=str(metrics.get("generated_at") or ""),
        cases=tuple(built),
    )


__all__ = [
    "ROLE_DRIVER",
    "ROLE_RESULT",
    "ROLE_SOURCE",
    "MotionReviewData",
    "MotionReviewError",
    "ReviewCase",
    "ReviewCell",
    "ReviewRole",
    "load_motion_review",
]
