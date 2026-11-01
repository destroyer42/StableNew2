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
    ("cannot_assess", "Cannot assess"),
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
    ("motion_freeze", "Motion freeze"),
    ("other", "Other (explain in notes)"),
)
CATEGORY_KEYS = tuple(value for value, _label in FAILURE_CATEGORIES)
CATEGORY_LABELS = dict(FAILURE_CATEGORIES)

#: Judgments a review must contain before it counts as complete; everything else is optional.
REQUIRED_SCORE_COLUMNS = IDENTITY_COLUMNS

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


def row_has_content(row: Mapping[str, str]) -> bool:
    """True when the operator typed any judgment (notes alone are not a rating)."""

    columns = (OVERALL_COLUMN, ACTION_COLUMN, BREAK_COLUMN, CATEGORIES_COLUMN, FIRST_FAILURE_COLUMN)
    return any((row.get(column) or "").strip() for column in (*SCORE_COLUMNS, *columns))


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
    )


__all__ = [
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
