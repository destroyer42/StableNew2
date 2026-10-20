"""Durable video quality-review evidence (PR-VID-QUALITY-211).

Human review of finished Video Workflow experiment clips, kept as append-only Learning evidence.  This is
*review evidence*, not execution authority: it is written through the canonical ``LearningRecordWriter`` to
the canonical ``learning_records.jsonl`` and never touches a job, an NJR or an artifact.

Isolation from image Learning is structural, not a filter someone has to remember:

* the record kind is ``video_workflow_quality_rating``, which ``RecommendationEngine`` ignores because it is
  not one of the kinds it accepts;
* every video field lives in the namespaced object ``metadata.video_quality_review``; the record carries none
  of the image-rating keys other readers key on (``user_rating``, ``image_path``, ``experiment_id``,
  ``learning_context``, ``variant_value``, ``variable_under_test``), so ``LearningRecordWriter``'s
  per-experiment readers and ``LearningAnalytics`` cannot see it.

Two entry types share the kind:

* ``clip_review``: one reviewed output, identified by ``(job_id, artifact_sha256)`` -- never by an editable
  path alone.  Editing appends a higher ``revision``; reading resolves the latest *valid* revision and keeps
  the earlier lines as history.
* ``manual_preference``: the operator's own pick (or explicit "no preference") for one experiment.  It is a
  recorded human choice, never a computed winner or a recommendation.

An unchanged save appends nothing.  A failed write raises ``ReviewSaveError`` so no caller can report "Saved"
for an attempted write.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.learning.learning_record import LearningRecord, LearningRecordWriter

RECORD_KIND = "video_workflow_quality_rating"
REVIEW_KEY = "video_quality_review"
SCHEMA = "stablenew.video-quality-review.v1"
SCHEMA_VERSION = 1
ENTRY_CLIP = "clip_review"
ENTRY_PREFERENCE = "manual_preference"

NOTES_MAX_CHARS = 2000
REASON_MAX_CHARS = 1000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TAIL_CONFIRM_BYTES = 512 * 1024

#: ``(key, label, question)`` -- every dimension is 1-5 with a higher value meaning better.
DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    (
        "directed_motion_fidelity",
        "Directed-motion fidelity",
        "Does the subject follow the intended movement?",
    ),
    (
        "temporal_continuity",
        "Temporal continuity",
        "Are transitions, timing and motion progression coherent?",
    ),
    (
        "subject_consistency",
        "Character/subject consistency",
        "Does the intended subject remain recognizable and stable?",
    ),
    (
        "anatomy_object_integrity",
        "Anatomy/object integrity",
        "Are people, limbs and important objects physically plausible?",
    ),
    ("scene_stability", "Scene/background stability", "Does the environment remain coherent?"),
)
DIMENSION_KEYS = tuple(key for key, _label, _question in DIMENSIONS)

#: ``(value, label)``; whether the requested action happened is separate from how good the clip looks.
ACTION_OUTCOMES: tuple[tuple[str, str], ...] = (
    ("achieved", "Achieved"),
    ("partially_achieved", "Partially achieved"),
    ("not_achieved", "Not achieved"),
    ("cannot_assess", "Cannot assess"),
)
ACTION_OUTCOME_VALUES = frozenset(value for value, _label in ACTION_OUTCOMES)

SAVED = "saved"
UNCHANGED = "unchanged"


class ReviewValidationError(ValueError):
    """The draft is not a valid review; nothing was written."""


class ReviewSaveError(RuntimeError):
    """The evidence could not be written (or read back); the operator's edits must be kept."""


def _rating(value: Any, name: str, *, required: bool) -> int | None:
    if value is None or value == "":
        if required:
            raise ReviewValidationError(f"{name} is required (1 to 5).")
        return None
    if isinstance(value, bool):
        raise ReviewValidationError(f"{name} must be a whole number from 1 to 5.")
    if isinstance(value, float):
        if not value.is_integer():
            raise ReviewValidationError(f"{name} must be a whole number from 1 to 5.")
        value = int(value)
    if isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"[0-9]+", text):
            raise ReviewValidationError(f"{name} must be a whole number from 1 to 5.")
        value = int(text)
    if not isinstance(value, int) or not 1 <= value <= 5:
        raise ReviewValidationError(f"{name} must be a whole number from 1 to 5.")
    return value


def _text(value: Any, name: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ReviewValidationError(f"{name} must be text.")
    cleaned = "".join(ch for ch in value if ch in "\n\t" or ch.isprintable()).strip()
    if len(cleaned) > limit:
        raise ReviewValidationError(
            f"{name} is limited to {limit} characters (it has {len(cleaned)})."
        )
    return cleaned


@dataclass(frozen=True)
class ClipReviewDraft:
    """The operator's assessment of one clip.  ``validate`` is the only way to a savable value."""

    overall_rating: Any = None
    action_outcome: Any = None
    dimensions: Mapping[str, Any] = field(default_factory=dict)
    notes: Any = ""

    def validate(self) -> ClipReviewDraft:
        overall = _rating(self.overall_rating, "Overall rating", required=True)
        outcome = self.action_outcome
        if outcome not in ACTION_OUTCOME_VALUES:
            raise ReviewValidationError(
                "Choose whether the requested action was achieved, partially achieved, not achieved "
                "or cannot be assessed."
            )
        unknown = sorted(set(self.dimensions) - set(DIMENSION_KEYS))
        if unknown:
            raise ReviewValidationError(f"Unknown rating dimension: {unknown[0]}.")
        dimensions: dict[str, int] = {}
        for key, label, _question in DIMENSIONS:
            value = _rating(self.dimensions.get(key), label, required=False)
            if value is not None:
                dimensions[key] = value
        return ClipReviewDraft(
            overall_rating=overall,
            action_outcome=outcome,
            dimensions=dimensions,
            notes=_text(self.notes, "Notes", NOTES_MAX_CHARS),
        )

    def comparable(self) -> tuple[Any, ...]:
        valid = self.validate()
        return (
            valid.overall_rating,
            valid.action_outcome,
            tuple(sorted(dict(valid.dimensions).items())),
            valid.notes,
        )


@dataclass(frozen=True)
class ReviewTarget:
    """What is being reviewed: the job, its tested value and the exact artifact bytes (by hash)."""

    experiment_id: str
    experiment_name: str
    job_id: str
    arm_index: int
    arm_label: str
    variable_name: str
    tested_value: Any
    workflow_id: str
    workflow_version: str
    backend_id: str
    artifact_path: str
    artifact_sha256: str
    identities: Mapping[str, Any] = field(default_factory=dict)

    def check(self) -> None:
        if not (self.experiment_id and self.job_id):
            raise ReviewValidationError("A review needs an experiment id and a job id.")
        if not _SHA256.match(self.artifact_sha256 or ""):
            raise ReviewValidationError(
                "The artifact has no content hash, so a review cannot be tied to these exact bytes."
            )


@dataclass(frozen=True)
class SavedClipReview:
    draft: ClipReviewDraft
    revision: int
    reviewed_at: str
    review_id: str
    job_id: str
    artifact_sha256: str
    artifact_path: str


@dataclass(frozen=True)
class SavedPreference:
    preferred_job_id: str | None
    preferred_arm_label: str
    preferred_artifact_sha256: str
    reason: str
    revision: int
    reviewed_at: str
    review_id: str


@dataclass(frozen=True)
class StoredReviews:
    clips: Mapping[tuple[str, str], SavedClipReview] = field(default_factory=dict)
    preference: SavedPreference | None = None

    def clip_for(self, job_id: str, artifact_sha256: str) -> SavedClipReview | None:
        """The latest valid review of exactly this job *and* these bytes; a replaced file gets none."""

        return self.clips.get((job_id, artifact_sha256))


@dataclass(frozen=True)
class SaveOutcome:
    status: str  # SAVED | UNCHANGED
    revision: int
    review_id: str = ""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _record(payload: dict[str, Any], review_id: str, reviewed_at: str) -> LearningRecord:
    return LearningRecord(
        run_id=f"video-review-{review_id}",
        timestamp=reviewed_at,
        base_config={},
        variant_configs=[],
        randomizer_mode="video_quality_review",
        randomizer_plan_size=0,
        primary_model="",
        primary_sampler="",
        primary_scheduler="",
        primary_steps=0,
        primary_cfg_scale=0.0,
        metadata={"record_kind": RECORD_KIND, REVIEW_KEY: payload},
    )


def _base_payload(
    entry_type: str, experiment_id: str, revision: int, review_id: str, reviewed_at: str
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "entry_type": entry_type,
        "experiment_id": experiment_id,
        "revision": revision,
        "review_id": review_id,
        "reviewed_at": reviewed_at,
    }


def build_clip_record(
    target: ReviewTarget, draft: ClipReviewDraft, *, revision: int, review_id: str, reviewed_at: str
) -> LearningRecord:
    target.check()
    valid = draft.validate()
    payload = _base_payload(ENTRY_CLIP, target.experiment_id, revision, review_id, reviewed_at)
    payload.update(
        experiment_name=target.experiment_name,
        job_id=target.job_id,
        arm_index=target.arm_index,
        arm_label=target.arm_label,
        variable_name=target.variable_name,
        tested_value=target.tested_value,
        workflow={
            "id": target.workflow_id,
            "version": target.workflow_version,
            "backend_id": target.backend_id,
        },
        artifact={"path": target.artifact_path, "sha256": target.artifact_sha256},
        identities=dict(target.identities),
        overall_rating=valid.overall_rating,
        action_outcome=valid.action_outcome,
        dimensions=dict(valid.dimensions),
        notes=valid.notes,
    )
    return _record(payload, review_id, reviewed_at)


def build_preference_record(
    *,
    experiment_id: str,
    preferred_job_id: str | None,
    preferred_arm_label: str,
    preferred_artifact_sha256: str,
    reason: Any,
    revision: int,
    review_id: str,
    reviewed_at: str,
) -> LearningRecord:
    if not experiment_id:
        raise ReviewValidationError("A preference needs an experiment id.")
    if preferred_job_id and not _SHA256.match(preferred_artifact_sha256 or ""):
        raise ReviewValidationError("The preferred clip has no content hash.")
    payload = _base_payload(ENTRY_PREFERENCE, experiment_id, revision, review_id, reviewed_at)
    payload.update(
        preferred_job_id=preferred_job_id or None,
        preferred_arm_label=preferred_arm_label if preferred_job_id else "",
        preferred_artifact_sha256=preferred_artifact_sha256 if preferred_job_id else "",
        reason=_text(reason, "Reason", REASON_MAX_CHARS) if preferred_job_id else "",
    )
    return _record(payload, review_id, reviewed_at)


# ------------------------------------------------------------------------------------ reading


def _payload_of(line: str) -> dict[str, Any] | None:
    if RECORD_KIND not in line:
        return None  # cheap prefilter: most lines are large image records that are never parsed
    try:
        record = json.loads(line)
    except ValueError:
        return None
    metadata = record.get("metadata") if isinstance(record, dict) else None
    if not isinstance(metadata, dict) or metadata.get("record_kind") != RECORD_KIND:
        return None
    payload = metadata.get(REVIEW_KEY)
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") != SCHEMA or payload.get("schema_version") != SCHEMA_VERSION:
        return None
    revision = payload.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        return None
    if not isinstance(payload.get("experiment_id"), str) or not payload["experiment_id"]:
        return None
    return payload


def _clip_from_payload(payload: dict[str, Any]) -> SavedClipReview | None:
    artifact = payload.get("artifact")
    if not isinstance(artifact, dict) or not _SHA256.match(str(artifact.get("sha256") or "")):
        return None
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        return None
    dimensions = payload.get("dimensions")
    try:
        draft = ClipReviewDraft(
            overall_rating=payload.get("overall_rating"),
            action_outcome=payload.get("action_outcome"),
            dimensions=dimensions if isinstance(dimensions, dict) else {},
            notes=payload.get("notes") or "",
        ).validate()
    except ReviewValidationError:
        return (
            None  # a record that breaks the rubric is skipped; an earlier valid revision still wins
        )
    return SavedClipReview(
        draft=draft,
        revision=payload["revision"],
        reviewed_at=str(payload.get("reviewed_at") or ""),
        review_id=str(payload.get("review_id") or ""),
        job_id=job_id,
        artifact_sha256=artifact["sha256"],
        artifact_path=str(artifact.get("path") or ""),
    )


def _preference_from_payload(payload: dict[str, Any]) -> SavedPreference | None:
    preferred = payload.get("preferred_job_id")
    sha = str(payload.get("preferred_artifact_sha256") or "")
    if preferred is not None and (
        not isinstance(preferred, str) or not preferred or not _SHA256.match(sha)
    ):
        return None
    try:
        reason = _text(payload.get("reason") or "", "Reason", REASON_MAX_CHARS)
    except ReviewValidationError:
        return None
    return SavedPreference(
        preferred_job_id=preferred,
        preferred_arm_label=str(payload.get("preferred_arm_label") or ""),
        preferred_artifact_sha256=sha,
        reason=reason,
        revision=payload["revision"],
        reviewed_at=str(payload.get("reviewed_at") or ""),
        review_id=str(payload.get("review_id") or ""),
    )


class VideoReviewStore:
    """Reads and appends video quality-review evidence through the canonical record writer."""

    def __init__(self, records_path: str | Path) -> None:
        self._writer = LearningRecordWriter(records_path)

    @property
    def records_path(self) -> Path:
        return self._writer.records_path

    def load(self, experiment_id: str) -> StoredReviews:
        """Latest valid revision per reviewed artifact (and the latest preference) of one experiment."""

        clips: dict[tuple[str, str], SavedClipReview] = {}
        preference: SavedPreference | None = None
        path = self._writer.records_path
        if not path.exists():
            return StoredReviews()
        try:
            handle = open(path, encoding="utf-8", errors="replace")  # noqa: SIM115 - closed below
        except OSError:
            return StoredReviews()
        with handle:
            for line in handle:
                payload = _payload_of(line)
                if payload is None or payload["experiment_id"] != experiment_id:
                    continue
                entry_type = payload.get("entry_type")
                if entry_type == ENTRY_CLIP:
                    saved = _clip_from_payload(payload)
                    if saved is None:
                        continue
                    key = (saved.job_id, saved.artifact_sha256)
                    current = clips.get(key)
                    if current is None or saved.revision >= current.revision:
                        clips[key] = saved
                elif entry_type == ENTRY_PREFERENCE:
                    candidate = _preference_from_payload(payload)
                    if candidate is not None and (
                        preference is None or candidate.revision >= preference.revision
                    ):
                        preference = candidate
        return StoredReviews(clips=clips, preference=preference)

    # -------------------------------------------------------------------------------- writing

    def save_clip(self, target: ReviewTarget, draft: ClipReviewDraft) -> SaveOutcome:
        target.check()
        valid = draft.validate()
        latest = self.load(target.experiment_id).clip_for(target.job_id, target.artifact_sha256)
        if latest is not None and latest.draft.comparable() == valid.comparable():
            return SaveOutcome(UNCHANGED, latest.revision, latest.review_id)
        revision = (latest.revision + 1) if latest is not None else 1
        review_id = uuid.uuid4().hex
        record = build_clip_record(
            target, valid, revision=revision, review_id=review_id, reviewed_at=_now()
        )
        self._append(record, review_id)
        return SaveOutcome(SAVED, revision, review_id)

    def save_preference(
        self,
        *,
        experiment_id: str,
        preferred_job_id: str | None,
        preferred_arm_label: str = "",
        preferred_artifact_sha256: str = "",
        reason: Any = "",
    ) -> SaveOutcome:
        probe = build_preference_record(
            experiment_id=experiment_id,
            preferred_job_id=preferred_job_id,
            preferred_arm_label=preferred_arm_label,
            preferred_artifact_sha256=preferred_artifact_sha256,
            reason=reason,
            revision=1,
            review_id="probe",
            reviewed_at=_now(),
        )
        new = probe.metadata[REVIEW_KEY]
        latest = self.load(experiment_id).preference
        if latest is not None and (
            latest.preferred_job_id,
            latest.preferred_artifact_sha256,
            latest.reason,
        ) == (new["preferred_job_id"], new["preferred_artifact_sha256"], new["reason"]):
            return SaveOutcome(UNCHANGED, latest.revision, latest.review_id)
        if latest is None and new["preferred_job_id"] is None:
            return SaveOutcome(UNCHANGED, 0)  # clearing a preference that was never set
        revision = (latest.revision + 1) if latest is not None else 1
        review_id = uuid.uuid4().hex
        record = build_preference_record(
            experiment_id=experiment_id,
            preferred_job_id=preferred_job_id,
            preferred_arm_label=preferred_arm_label,
            preferred_artifact_sha256=preferred_artifact_sha256,
            reason=reason,
            revision=revision,
            review_id=review_id,
            reviewed_at=_now(),
        )
        self._append(record, review_id)
        return SaveOutcome(SAVED, revision, review_id)

    def _append(self, record: LearningRecord, review_id: str) -> None:
        try:
            written = self._writer.append_record(record)
        except Exception as exc:  # noqa: BLE001 - surfaced as a save failure, never swallowed
            raise ReviewSaveError(f"The review could not be written: {exc}") from exc
        if not written:
            raise ReviewSaveError(
                f"The review could not be written to {self._writer.records_path}. Your edits are kept."
            )
        if not self._confirm_tail(review_id):
            raise ReviewSaveError(
                "The review was written but could not be read back from the evidence file. "
                "Your edits are kept; check the file and save again."
            )

    def _confirm_tail(self, review_id: str) -> bool:
        path = self._writer.records_path
        try:
            size = path.stat().st_size
            with open(path, "rb") as handle:
                handle.seek(max(0, size - _TAIL_CONFIRM_BYTES))
                tail = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return False
        for line in reversed(tail.splitlines()):
            if review_id in line:
                payload = _payload_of(line)
                return payload is not None and payload.get("review_id") == review_id
        return False


__all__ = [
    "ACTION_OUTCOMES",
    "ACTION_OUTCOME_VALUES",
    "DIMENSIONS",
    "DIMENSION_KEYS",
    "ENTRY_CLIP",
    "ENTRY_PREFERENCE",
    "NOTES_MAX_CHARS",
    "RECORD_KIND",
    "REVIEW_KEY",
    "SAVED",
    "SCHEMA",
    "UNCHANGED",
    "ClipReviewDraft",
    "ReviewSaveError",
    "ReviewTarget",
    "ReviewValidationError",
    "SaveOutcome",
    "SavedClipReview",
    "SavedPreference",
    "StoredReviews",
    "VideoReviewStore",
    "build_clip_record",
    "build_preference_record",
]
