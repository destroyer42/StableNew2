"""Identity and continuity rubric for eval-suite ratings (PR-VID-QUALITY-351).

Pure vocabulary and validation for the operator-typed columns of ``ratings.csv``. Nothing here reads a file,
a clip or the repository, and nothing is inferred from the numeric metrics: every value is something the
operator wrote after watching the recorded clip beside its source image.

Source fidelity (does the generated subject resemble the input?) and subject stability (does it stay that
same subject across the clip?) are separate judgments, and both are separate from whether the requested
movement happened. Blank means *not assessed*; it is never zero, a failure or a pass.

The wording of the continuity dimensions follows PR-VID-QUALITY-211 (``src/learning/video_quality_review.py``)
without importing the Learning layer or creating a second rating store.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

#: ``(column, label, question)``; 1-5, higher is better, blank is not assessed.
SCORE_DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    (
        "source_fidelity_1_to_5",
        "Source fidelity",
        "Does the generated subject still resemble the original source image?",
    ),
    (
        "subject_stability_1_to_5",
        "Subject stability",
        "Does that same subject stay recognizable from the first frame to the last?",
    ),
    (
        "temporal_continuity_1_to_5",
        "Temporal continuity",
        "Is the movement smooth and coherent rather than flickering, freezing or morphing?",
    ),
    (
        "anatomy_integrity_1_to_5",
        "Anatomy / object integrity",
        "Are faces, clothing, proportions and important objects stable and plausible?",
    ),
    (
        "scene_stability_1_to_5",
        "Scene stability",
        "Does the background stay coherent?",
    ),
)
SCORE_COLUMNS = tuple(column for column, _label, _question in SCORE_DIMENSIONS)
SCORE_LABELS = {column: label for column, label, _question in SCORE_DIMENSIONS}
OVERALL_COLUMN = "rating_1_to_5"
ACTION_COLUMN = "requested_action"
BREAK_COLUMN = "critical_identity_break"
CATEGORIES_COLUMN = "failure_categories"
FIRST_FAILURE_COLUMN = "first_failure_seconds"
NOTES_COLUMN = "notes"

#: Dimensions that carry the identity judgment (source fidelity and temporal subject stability).
IDENTITY_COLUMNS = ("source_fidelity_1_to_5", "subject_stability_1_to_5")

SCORE_ANCHORS: tuple[tuple[int, str], ...] = (
    (5, "Stable and convincing; no meaningful defect observed."),
    (4, "Minor imperfection; identity and interpretation preserved."),
    (3, "Noticeable issue, but the subject or scene is still interpretable."),
    (2, "Major inconsistency that materially reduces usefulness."),
    (1, "Severe failure; the subject or intended result is no longer trustworthy."),
)
#: A score at or below this is "major inconsistency" on the anchors above.
CONCERN_SCORE = 2

ACTION_VALUES: tuple[tuple[str, str], ...] = (
    ("achieved", "Achieved"),
    ("partially_achieved", "Partially achieved"),
    ("not_achieved", "Not achieved"),
    # PR-VID-MOTION-410: a lively clip that does a different or contradictory action is not "no motion".
    ("incorrect_or_contradictory", "Incorrect or contradictory action"),
    ("cannot_assess", "Cannot assess"),
)
#: ``cannot_assess`` (or a blank cell) is the not-assessed state; every other value is an observed outcome.
ACTION_OBSERVED_KEYS = (
    "achieved",
    "partially_achieved",
    "not_achieved",
    "incorrect_or_contradictory",
)
ACTION_KEYS = tuple(value for value, _label in ACTION_VALUES)
ACTION_LABELS = dict(ACTION_VALUES)

BREAK_VALUES: tuple[tuple[str, str], ...] = (
    ("yes", "Yes"),
    ("no", "No"),
    ("cannot_assess", "Cannot assess"),
)
BREAK_KEYS = tuple(value for value, _label in BREAK_VALUES)
BREAK_LABELS = dict(BREAK_VALUES)

FAILURE_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("face_or_identity_drift", "Face or identity drift"),
    ("clothing_or_appearance_change", "Clothing or appearance change"),
    ("body_proportion_change", "Body proportion change"),
    ("important_object_change", "Important object change"),
    ("subject_disappearance", "Subject disappearance"),
    ("scene_background_drift", "Scene or background drift"),
    ("temporal_flicker", "Temporal flicker"),
    ("motion_freeze", "Frozen or insufficient motion"),
    # VID-A14B-SVI-375: a visible jump (pose, colour, identity) where one segment of a sequence hands over to the next.
    ("segment_seam", "Seam between sequence segments"),
    # PR-VID-MOTION-410: controlled-motion failure taxonomy (identity drift, anatomy and continuity reuse the
    # categories above wherever they already name the same failure).
    ("wrong_action", "Wrong action"),
    ("wrong_direction", "Wrong direction"),
    ("incomplete_action", "Incomplete action"),
    ("unwanted_action_repetition", "Unwanted action repetition"),
    ("incorrect_timing", "Incorrect timing"),
    ("subject_not_performing_motion", "Intended subject not performing the motion"),
    ("duplicate_or_ghost_subject", "Duplicate or ghost subject"),
    ("unintended_appearance_transfer", "Unintended appearance transfer from the driver"),
    ("anatomy_distortion", "Anatomy distortion"),
    ("background_motion_or_contamination", "Background motion or contamination"),
    ("temporal_discontinuity", "Temporal discontinuity"),
    ("excessive_jitter", "Excessive jitter"),
    ("start_end_pose_mismatch", "Start or end pose mismatch"),
    ("other", "Other (explain in notes)"),
)
CATEGORY_KEYS = tuple(value for value, _label in FAILURE_CATEGORIES)
CATEGORY_LABELS = dict(FAILURE_CATEGORIES)

#: Judgments a review must contain before it counts as complete; everything else is optional.
REQUIRED_SCORE_COLUMNS = IDENTITY_COLUMNS

# --------------------------------------------------------------------------------- controlled motion (PR-VID-MOTION-410)
#
# Whether the requested action happened, whether the intended subject performed it, and how closely it followed the
# driving reference are three judgments, each separate from the visual-quality and identity scores above. Blank (or the
# explicit ``not_assessed`` / ``cannot_assess`` token) means not assessed; it is never zero, a failure or a pass.

#: Version stamped beside motion ratings so a later change to this vocabulary stays identifiable.
MOTION_RUBRIC_VERSION = "stablenew.video-eval-motion-rubric.v1"
ATTACHMENT_COLUMN = "subject_attachment"
FIDELITY_COLUMN = "motion_fidelity_1_to_5"
MOTION_COMMENTS_COLUMN = "motion_comments"

ATTACHMENT_VALUES: tuple[tuple[str, str], ...] = (
    ("correct_subject", "Correct subject"),
    ("partially_attached", "Partially attached or ambiguous"),
    ("incorrect_subject", "Incorrect subject"),
    ("duplicate_or_ghost", "Duplicate or ghost subject performs the movement"),
    ("cannot_assess", "Cannot assess"),
)
ATTACHMENT_KEYS = tuple(value for value, _label in ATTACHMENT_VALUES)
ATTACHMENT_LABELS = dict(ATTACHMENT_VALUES)
#: Values that are an observed judgment (everything but the not-assessed state).
ATTACHMENT_OBSERVED_KEYS = tuple(key for key in ATTACHMENT_KEYS if key != "cannot_assess")

#: Motion fidelity is rated against the *effective driving reference*, not motion magnitude or aesthetics.
FIDELITY_ANCHORS: tuple[tuple[int, str], ...] = (
    (5, "Highly faithful reproduction of the intended movement."),
    (4, "Close reproduction with minor differences."),
    (3, "Recognizable movement with significant inaccuracies."),
    (2, "Some resemblance, but major action or timing differences."),
    (1, "No meaningful resemblance to the intended movement."),
)

NOT_APPLICABLE = "not_applicable"
#: ``(column, label, question, ((value, label), ...))``. Every field also accepts explicit ``not_applicable`` and
#: ``cannot_assess`` answers: a head turn is not marked down for failing to travel through the scene.
OBSERVATION_FIELDS: tuple[tuple[str, str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "action_direction",
        "Action direction",
        "Does the movement go the way the driving reference goes?",
        (("correct", "Correct"), ("reversed", "Reversed"), ("incorrect", "Incorrect")),
    ),
    (
        "action_timing",
        "Action timing",
        "Do the phases happen at the driving reference's pace and moment?",
        (
            ("matches", "Matches"),
            ("minor_difference", "Minor difference"),
            ("major_difference", "Major difference"),
        ),
    ),
    (
        "action_completion",
        "Completion of the intended movement",
        "Does the movement run to completion?",
        (("complete", "Complete"), ("partial", "Partial"), ("not_completed", "Not completed")),
    ),
    (
        "root_displacement",
        "Root displacement or locomotion",
        "Does the subject travel through the scene as the driver does? (not applicable for in-place actions)",
        (("matches", "Matches"), ("partial", "Partial"), ("absent", "Absent")),
    ),
    (
        "start_end_pose",
        "Starting and ending pose",
        "Do the first and last poses match the driving reference?",
        (
            ("matches", "Both match"),
            ("start_mismatch", "Start differs"),
            ("end_mismatch", "End differs"),
            ("both_mismatch", "Both differ"),
        ),
    ),
    (
        "driver_contamination",
        "Driver contamination",
        "Is the driving video's person, clothing or background visible in the result?",
        (("none_observed", "None observed"), ("observed", "Observed")),
    ),
)
OBSERVATION_COLUMNS = tuple(column for column, _l, _q, _v in OBSERVATION_FIELDS)
OBSERVATION_LABELS = {column: label for column, label, _q, _v in OBSERVATION_FIELDS}
OBSERVATION_VALUE_LABELS: dict[str, dict[str, str]] = {
    column: {**dict(values), NOT_APPLICABLE: "Not applicable", "cannot_assess": "Cannot assess"}
    for column, _label, _question, values in OBSERVATION_FIELDS
}
MOTION_COLUMNS = (ATTACHMENT_COLUMN, FIDELITY_COLUMN, *OBSERVATION_COLUMNS, MOTION_COMMENTS_COLUMN)

_WHOLE_NUMBER = re.compile(r"[0-9]+")
_CATEGORY_SPLIT = re.compile(r"[;,|]")
#: A first-failure time may sit this far past the measured duration before it is called out of range.
_DURATION_SLACK_SECONDS = 0.5


def _token(text: str) -> str:
    return re.sub(r"[\s\-]+", "_", text.strip().lower())


@dataclass(frozen=True)
class RatingEvidence:
    """One row's operator judgments, parsed. ``issues`` lists every value that was typed but is not valid."""

    overall: int | None = None
    requested_action: str | None = None
    scores: Mapping[str, int | None] = field(default_factory=dict)
    critical_identity_break: str | None = None
    failure_categories: tuple[str, ...] = ()
    first_failure_seconds: float | None = None
    notes: str = ""
    issues: tuple[str, ...] = ()
    has_content: bool = False
    #: PR-VID-MOTION-410: subject attachment, fidelity (1-5) and per-field observations; ``None`` is not assessed.
    subject_attachment: str | None = None
    motion_fidelity: int | None = None
    observations: Mapping[str, str | None] = field(default_factory=dict)
    motion_comments: str = ""
    has_motion_content: bool = False

    @property
    def motion_complete(self) -> bool:
        """The three motion judgments are each an observed answer (``cannot_assess`` is not evidence)."""

        return (
            not self.issues
            and self.requested_action in ACTION_OBSERVED_KEYS
            and self.subject_attachment in ATTACHMENT_OBSERVED_KEYS
            and self.motion_fidelity is not None
        )

    def motion_missing(self) -> tuple[str, ...]:
        gaps: list[str] = []
        if self.requested_action not in ACTION_OBSERVED_KEYS:
            gaps.append("Requested action (an observed outcome)")
        if self.subject_attachment not in ATTACHMENT_OBSERVED_KEYS:
            gaps.append("Subject attachment")
        if self.motion_fidelity is None:
            gaps.append("Motion fidelity")
        return tuple(gaps)

    @property
    def complete(self) -> bool:
        """Every required judgment is present and valid (a ``cannot_assess`` answer is not evidence)."""

        return (
            not self.issues
            and all(self.scores.get(column) is not None for column in REQUIRED_SCORE_COLUMNS)
            and self.critical_identity_break in ("yes", "no")
            and self.requested_action in ACTION_KEYS
        )

    def missing(self) -> tuple[str, ...]:
        gaps = [
            SCORE_LABELS[column]
            for column in REQUIRED_SCORE_COLUMNS
            if self.scores.get(column) is None
        ]
        if self.critical_identity_break not in ("yes", "no"):
            gaps.append("Critical identity break (Yes or No)")
        if self.requested_action not in ACTION_KEYS:
            gaps.append("Requested action")
        return tuple(gaps)


def _score(raw: str, column: str, issues: list[str]) -> int | None:
    text = raw.strip()
    if not text:
        return None
    if _WHOLE_NUMBER.fullmatch(text) and 1 <= int(text) <= 5:
        return int(text)
    issues.append(f"{column}: {text!r} is not a whole number from 1 to 5")
    return None


def _choice(
    row: Mapping[str, str], column: str, allowed: tuple[str, ...], issues: list[str]
) -> str | None:
    """A controlled value, or ``None`` for blank and the explicit not-assessed token. Invalid values become issues."""

    raw = (row.get(column) or "").strip()
    if not raw:
        return None
    key = _token(raw)
    if key == "not_assessed":
        return None
    if key not in allowed:
        issues.append(f"{column}: {raw!r} is not one of {' | '.join(allowed)}")
        return None
    return key


def row_has_motion_content(row: Mapping[str, str]) -> bool:
    """True when the operator typed any controlled-motion judgment (comments alone are not a rating)."""

    return any(
        (row.get(column) or "").strip()
        for column in (ATTACHMENT_COLUMN, FIDELITY_COLUMN, *OBSERVATION_COLUMNS)
    )


def row_has_content(row: Mapping[str, str]) -> bool:
    """True when the operator typed any judgment (notes alone are not a rating)."""

    columns = (OVERALL_COLUMN, ACTION_COLUMN, BREAK_COLUMN, CATEGORIES_COLUMN, FIRST_FAILURE_COLUMN)
    return any(
        (row.get(column) or "").strip() for column in (*SCORE_COLUMNS, *columns)
    ) or row_has_motion_content(row)


def parse_rating_row(
    row: Mapping[str, str], *, duration_seconds: float | None = None
) -> RatingEvidence:
    """Parse and validate one ``ratings.csv`` row. Never raises; invalid values become ``issues``."""

    issues: list[str] = []
    overall = _score(row.get(OVERALL_COLUMN) or "", OVERALL_COLUMN, issues)
    scores = {column: _score(row.get(column) or "", column, issues) for column in SCORE_COLUMNS}

    action_raw = (row.get(ACTION_COLUMN) or "").strip()
    action = _token(action_raw) if action_raw else None
    if action is not None and action not in ACTION_KEYS:
        issues.append(f"{ACTION_COLUMN}: {action_raw!r} is not one of {' | '.join(ACTION_KEYS)}")
        action = None

    break_raw = (row.get(BREAK_COLUMN) or "").strip()
    critical = _token(break_raw) if break_raw else None
    if critical is not None and critical not in BREAK_KEYS:
        issues.append(f"{BREAK_COLUMN}: {break_raw!r} is not one of {' | '.join(BREAK_KEYS)}")
        critical = None

    categories: list[str] = []
    for part in _CATEGORY_SPLIT.split(row.get(CATEGORIES_COLUMN) or ""):
        if not part.strip():
            continue
        key = _token(part)
        if key not in CATEGORY_KEYS:
            issues.append(f"{CATEGORIES_COLUMN}: unknown category {part.strip()!r}")
        elif key not in categories:
            categories.append(key)

    seconds: float | None = None
    seconds_raw = (row.get(FIRST_FAILURE_COLUMN) or "").strip()
    if seconds_raw:
        try:
            seconds = float(seconds_raw)
        except ValueError:
            seconds = None
        if seconds is None or not math.isfinite(seconds) or seconds < 0:
            issues.append(f"{FIRST_FAILURE_COLUMN}: {seconds_raw!r} is not a time in seconds")
            seconds = None
        elif duration_seconds is not None and seconds > duration_seconds + _DURATION_SLACK_SECONDS:
            issues.append(
                f"{FIRST_FAILURE_COLUMN}: {seconds_raw} s is past the end of the "
                f"{duration_seconds:.3g} s clip"
            )
            seconds = None

    attachment = _choice(row, ATTACHMENT_COLUMN, ATTACHMENT_KEYS, issues)
    fidelity = _score(row.get(FIDELITY_COLUMN) or "", FIDELITY_COLUMN, issues)
    observations: dict[str, str | None] = {}
    for column, _label, _question, values in OBSERVATION_FIELDS:
        allowed = (*(value for value, _ in values), NOT_APPLICABLE, "cannot_assess")
        observations[column] = _choice(row, column, allowed, issues)

    return RatingEvidence(
        overall=overall,
        requested_action=action,
        scores=scores,
        critical_identity_break=critical,
        failure_categories=tuple(categories),
        first_failure_seconds=seconds,
        notes=row.get(NOTES_COLUMN) or "",
        issues=tuple(issues),
        has_content=row_has_content(row),
        subject_attachment=attachment,
        motion_fidelity=fidelity,
        observations=observations,
        motion_comments=row.get(MOTION_COMMENTS_COLUMN) or "",
        has_motion_content=row_has_motion_content(row),
    )


__all__ = [
    "ACTION_OBSERVED_KEYS",
    "ATTACHMENT_COLUMN",
    "ATTACHMENT_KEYS",
    "ATTACHMENT_LABELS",
    "ATTACHMENT_OBSERVED_KEYS",
    "ATTACHMENT_VALUES",
    "FIDELITY_ANCHORS",
    "FIDELITY_COLUMN",
    "MOTION_COLUMNS",
    "MOTION_COMMENTS_COLUMN",
    "MOTION_RUBRIC_VERSION",
    "NOT_APPLICABLE",
    "OBSERVATION_COLUMNS",
    "OBSERVATION_FIELDS",
    "OBSERVATION_LABELS",
    "OBSERVATION_VALUE_LABELS",
    "row_has_motion_content",
    "ACTION_KEYS",
    "ACTION_LABELS",
    "ACTION_VALUES",
    "BREAK_KEYS",
    "BREAK_LABELS",
    "BREAK_VALUES",
    "CATEGORY_KEYS",
    "CATEGORY_LABELS",
    "CONCERN_SCORE",
    "FAILURE_CATEGORIES",
    "IDENTITY_COLUMNS",
    "REQUIRED_SCORE_COLUMNS",
    "SCORE_ANCHORS",
    "SCORE_COLUMNS",
    "SCORE_DIMENSIONS",
    "SCORE_LABELS",
    "RatingEvidence",
    "parse_rating_row",
    "row_has_content",
]
