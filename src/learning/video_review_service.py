"""Open, rate and reopen a Video Workflow experiment review (PR-VID-QUALITY-211).

The single seam the review window talks to.  It composes three things that already own their truth:

* the canonical job repository (through ``src.video.video_review_group``) for which jobs exist and what
  state they are in;
* the artifact bytes (hashed here, bounded and cancellable) for *which clip* a rating belongs to;
* the Learning record writer (through ``VideoReviewStore``) for the durable review evidence.

Everything here does file and database I/O, so callers run it on a worker thread, never on Tk.  The service
holds no state between calls (restarting it loses nothing: evidence is re-read from the evidence file), makes
no job, queues nothing, and writes nothing but review evidence.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from src.learning.video_quality_review import (
    ClipReviewDraft,
    ReviewSaveError,
    ReviewTarget,
    SaveOutcome,
    StoredReviews,
    VideoReviewStore,
)
from src.video.video_review_group import (
    ArmState,
    RepositoryReader,
    ReviewArm,
    ReviewGroup,
    ReviewGroupError,
    build_review_group,
)

HASH_CHUNK_BYTES = 1024 * 1024
#: Larger outputs are not identified (and so not rated) rather than hashed for minutes on a worker.
MAX_HASH_BYTES = 2 * 1024 * 1024 * 1024


class ReviewCancelled(RuntimeError):
    """The caller abandoned the load (a newer request replaced it)."""


class ArtifactTooLarge(RuntimeError):
    pass


def file_sha256(path: str | Path, *, cancel: threading.Event | None = None) -> str:
    """SHA-256 of a file in bounded chunks; cooperative cancel; refuses files above ``MAX_HASH_BYTES``."""

    target = Path(path)
    if target.stat().st_size > MAX_HASH_BYTES:
        raise ArtifactTooLarge(f"{target.name} is larger than {MAX_HASH_BYTES // (1024**3)} GiB")
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_BYTES), b""):
            if cancel is not None and cancel.is_set():
                raise ReviewCancelled("hashing was cancelled")
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class LoadedReview:
    group: ReviewGroup
    stored: StoredReviews


class VideoReviewService:
    def __init__(
        self,
        repository: RepositoryReader,
        records_path: str | Path,
        *,
        is_file: Callable[[str], bool] = os.path.isfile,
        hash_file: Callable[..., str] = file_sha256,
    ) -> None:
        self._repository = repository
        self._store = VideoReviewStore(records_path)
        self._is_file = is_file
        self._hash_file = hash_file

    # ------------------------------------------------------------------ open

    def load(self, job_id: str, *, cancel: threading.Event | None = None) -> LoadedReview:
        """Rebuild the group from persisted jobs, identify each playable clip, attach saved reviews."""

        try:
            group = build_review_group(self._repository, job_id, is_file=self._is_file)
        except sqlite3.Error as exc:
            raise ReviewGroupError(
                "storage", f"The job history could not be read right now ({exc}). Try again."
            ) from exc
        arms = []
        for arm in group.arms:
            if cancel is not None and cancel.is_set():
                raise ReviewCancelled("the review load was superseded")
            arms.append(self._identify(arm, cancel))
        group = replace(group, arms=tuple(arms))
        return LoadedReview(group=group, stored=self._store.load(group.experiment_id))

    def _identify(self, arm: ReviewArm, cancel: threading.Event | None) -> ReviewArm:
        if not arm.playable or not arm.artifact_path:
            return arm
        try:
            digest = self._hash_file(arm.artifact_path, cancel=cancel)
            size = Path(arm.artifact_path).stat().st_size
        except ReviewCancelled:
            raise
        except ArtifactTooLarge as exc:
            return replace(
                arm,
                state=ArmState.UNSUPPORTED,
                state_text=f"Too large to identify for review ({exc}); open the original instead.",
            )
        except OSError as exc:
            return replace(
                arm,
                state=ArmState.MISSING,
                state_text=f"The output file cannot be read: {exc.strerror or type(exc).__name__}.",
            )
        return replace(arm, artifact_sha256=digest, artifact_bytes=size)

    # ------------------------------------------------------------------ save

    def save_clip_review(
        self, group: ReviewGroup, job_id: str, draft: ClipReviewDraft
    ) -> SaveOutcome:
        arm = self._reviewable_arm(group, job_id)
        target = ReviewTarget(
            experiment_id=group.experiment_id,
            experiment_name=group.experiment_name,
            job_id=arm.job_id,
            arm_index=arm.index,
            arm_label=arm.label,
            variable_name=group.variable_name,
            tested_value=arm.value,
            workflow_id=group.overview.workflow_id,
            workflow_version=group.overview.workflow_version,
            backend_id=group.overview.backend_id,
            artifact_path=arm.artifact_path or "",
            artifact_sha256=arm.artifact_sha256,
            identities=self._identities(group, arm),
        )
        return self._store.save_clip(target, draft)

    def save_preference(
        self, group: ReviewGroup, preferred_job_id: str | None, reason: Any = ""
    ) -> SaveOutcome:
        if not preferred_job_id:
            return self._store.save_preference(
                experiment_id=group.experiment_id, preferred_job_id=None
            )
        arm = self._reviewable_arm(group, preferred_job_id)
        return self._store.save_preference(
            experiment_id=group.experiment_id,
            preferred_job_id=arm.job_id,
            preferred_arm_label=arm.label,
            preferred_artifact_sha256=arm.artifact_sha256,
            reason=reason,
        )

    def _reviewable_arm(self, group: ReviewGroup, job_id: str) -> ReviewArm:
        arm = group.arm_for_job(job_id)
        if arm is None:
            raise ReviewSaveError(
                f"Job {job_id} is not an arm of experiment {group.experiment_id}."
            )
        if not arm.playable or not arm.artifact_sha256 or not arm.artifact_path:
            raise ReviewSaveError(
                f"Arm {arm.label} has no completed, identified video to review ({arm.state_text})."
            )
        try:
            current = self._hash_file(arm.artifact_path)
        except (OSError, ArtifactTooLarge) as exc:
            raise ReviewSaveError(f"Arm {arm.label}'s video can no longer be read: {exc}") from exc
        if current != arm.artifact_sha256:
            raise ReviewSaveError(
                f"Arm {arm.label}'s video file changed after this review opened, so it would no longer "
                "be the clip you looked at. Reload the review and assess the current file."
            )
        return arm

    @staticmethod
    def _identities(group: ReviewGroup, arm: ReviewArm) -> dict[str, Any]:
        overview = group.overview
        derived = (overview.motion_source_preparation.get("derived") or {}) if overview else {}
        return {
            "njr_fingerprint": arm.njr_fingerprint,
            "seed": overview.seed,
            "source_image_path": overview.source_image_path,
            "prepared_source_path": overview.prepared_source_path,
            "driving_video_sha256": overview.driving_video_sha256,
            "prepared_motion_source_sha256": str(derived.get("sha256") or ""),
        }


__all__ = [
    "HASH_CHUNK_BYTES",
    "MAX_HASH_BYTES",
    "ArtifactTooLarge",
    "LoadedReview",
    "ReviewCancelled",
    "VideoReviewService",
    "file_sha256",
]
