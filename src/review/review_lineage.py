"""Read-only lookup of the jobs derived from reviewed images (PR-REVIEW-LIFECYCLE-621).

A re-work job records ``parent_job_id`` and ``parent_artifact_id = sha256:<bytes>`` of the image it came from. This
module finds those children for a set of review items and describes them; it stores nothing and owns no queue, runner or
lifecycle. The job repository is the only authority: whether a child is queued, failed or finished is read from it each
time, never remembered.

A child is **verified** when it names the digest of the image's bytes and **unverified** when it names only the image's
embedded job id (the same vocabulary Compare with Parent uses). A child that names a different artifact digest is not a
child of this image, even when it shares the job. Outputs come from the existing ``resolve_job_outputs``.

Every function here is blocking (it reads the repository and the file system): call it from a worker, never from Tk.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from src.controller.batch_output_resolution import resolve_job_outputs
from src.queue.batch_membership import BatchKey, BatchKind, MembershipState, resolve_batch_membership
from src.queue.batch_projection import (
    BatchJobView,
    BatchSummary,
    StatusCounts,
    derive_aggregate_state,
    job_view_from_row,
    snapshot_metadata,
)
from src.queue.job_history_store import BatchCandidateRow
from src.queue.job_model import JobStatus
from src.queue.job_repository import REVIEW_CHILD_LIMIT, JobRepository

VERIFIED = "verified"
UNVERIFIED = "unverified"

VERIFIED_NOTE = "Verified: the job recorded the SHA-256 of this image as its source."
UNVERIFIED_NOTE = (
    "Not independently verified: the job records its parent job but no matching image digest."
)
_LINEAGE_KEY = BatchKey(BatchKind.REVIEW, "review-lineage")


@dataclass(frozen=True)
class LineageSource:
    """One reviewed image: ``key`` is the caller's identity for it, ``digest`` the SHA-256 of its bytes (hex)."""

    key: str
    digest: str = ""
    job_id: str = ""


@dataclass(frozen=True)
class ReviewChild:
    source_key: str
    job_id: str
    status: JobStatus
    relation: str
    created_at: datetime
    completed_at: datetime | None = None
    #: The review batch the job was submitted in, when it was submitted as one.
    batch_id: str = ""
    parent_job_id: str = ""
    parent_artifact_id: str = ""
    #: Existing, readable image outputs of a COMPLETED job (empty for every other status).
    outputs: tuple[str, ...] = ()
    #: A short, typed reason for a FAILED job (empty otherwise).
    failure: str = ""

    @property
    def verified(self) -> bool:
        return self.relation == VERIFIED

    @property
    def active(self) -> bool:
        return self.status in (JobStatus.QUEUED, JobStatus.RUNNING)


@dataclass(frozen=True)
class LineageResult:
    by_source: Mapping[str, tuple[ReviewChild, ...]] = field(default_factory=dict)
    #: True when the bounded read stopped before every matching row was returned.
    truncated: bool = False

    def children_of(self, source_key: str) -> tuple[ReviewChild, ...]:
        return self.by_source.get(source_key, ())

    def of_batch(self, batch_id: str) -> tuple[ReviewChild, ...]:
        """Every found child that was submitted in review batch ``batch_id``."""

        return tuple(
            child
            for children in self.by_source.values()
            for child in children
            if batch_id and child.batch_id == batch_id
        )


def repository_of(controller: Any) -> JobRepository | None:
    """The controller's job repository (the same authority the Batches view reads), or ``None`` when absent."""

    for source in (controller, getattr(controller, "pipeline_controller", None)):
        job_service = getattr(source, "job_service", None)
        getter = getattr(source, "get_job_service", None)
        if job_service is None and callable(getter):
            job_service = getter()
        repository = getattr(getattr(job_service, "job_queue", None), "repository", None)
        if isinstance(repository, JobRepository):
            return repository
    return None


def _batch_id(row: BatchCandidateRow) -> str:
    resolution = resolve_batch_membership(snapshot_metadata(row.snapshot))
    if resolution.state is MembershipState.MEMBER and resolution.membership is not None:
        return resolution.membership.key.batch_id
    return ""


def _claims(row: BatchCandidateRow) -> tuple[str, str]:
    normalized = row.snapshot.get("normalized_job") if isinstance(row.snapshot, dict) else None
    source = normalized.get("source") if isinstance(normalized, dict) else None
    if not isinstance(source, dict):
        return "", ""
    return str(source.get("parent_job_id") or ""), str(source.get("parent_artifact_id") or "")


def _relation(source: LineageSource, parent_job: str, parent_artifact: str) -> str | None:
    """``verified`` (digest match), ``unverified`` (job only), or ``None`` (not a child of this image)."""

    if parent_artifact:
        wanted = f"sha256:{source.digest}" if source.digest else ""
        return VERIFIED if wanted and parent_artifact.lower() == wanted else None
    if source.job_id and parent_job == source.job_id:
        return UNVERIFIED
    return None


def _failure_text(job: BatchJobView) -> str:
    if job.failure is None:
        return "failed"
    return job.failure.label or "failed"


def _outputs(views: Sequence[BatchJobView]) -> dict[str, tuple[str, ...]]:
    """Image outputs of finished jobs through the existing resolver (result artifacts only, never checkpoints)."""

    if not views:
        return {}
    trimmed = tuple(
        replace(job, artifacts=tuple(ref for ref in job.artifacts if ref.origin == "result"))
        for job in views
    )
    counts = StatusCounts.of(job.status for job in trimmed)
    created = min(job.created_at for job in trimmed)
    summary = BatchSummary(
        key=_LINEAGE_KEY,
        jobs=trimmed,
        counts=counts,
        state=derive_aggregate_state(counts),
        declared_source_count=None,
        covered_source_count=0,
        held_count=0,
        first_created_at=created,
        last_activity_at=created,
        workload_kinds=(),
        origin_batch=None,
        failure_categories=(),
        conflicting=False,
        notes=(),
    )
    return {
        job.job_id: tuple(resolve_job_outputs(summary, [job.job_id]).images) for job in trimmed
    }


def find_review_children(
    repository: JobRepository | None,
    sources: Sequence[LineageSource],
    *,
    limit: int | None = None,
) -> LineageResult:
    """Children (verified, then job-only) of every source, derived from the repository on every call."""

    if repository is None or not sources:
        return LineageResult()
    bound = REVIEW_CHILD_LIMIT if limit is None else int(limit)
    rows = repository.read_review_child_rows(
        parent_artifact_ids=[f"sha256:{item.digest}" for item in sources if item.digest],
        parent_job_ids=[item.job_id for item in sources if item.job_id],
        limit=bound,
    )
    matched: list[tuple[LineageSource, BatchCandidateRow, str]] = []
    for row in rows:
        parent_job, parent_artifact = _claims(row)
        for source in sources:
            relation = _relation(source, parent_job, parent_artifact)
            if relation is not None:
                matched.append((source, row, relation))
    views = {
        row.job_id: job_view_from_row(row, _LINEAGE_KEY, source_index=None)
        for _source, row, _relation_name in matched
    }
    finished = [view for view in views.values() if view.status is JobStatus.COMPLETED]
    outputs = _outputs(finished)
    grouped: dict[str, list[ReviewChild]] = {}
    for source, row, relation in matched:
        parent_job, parent_artifact = _claims(row)
        view = views[row.job_id]
        grouped.setdefault(source.key, []).append(
            ReviewChild(
                source_key=source.key,
                job_id=row.job_id,
                status=row.status,
                relation=relation,
                created_at=row.created_at,
                completed_at=row.completed_at,
                batch_id=_batch_id(row),
                parent_job_id=parent_job,
                parent_artifact_id=parent_artifact,
                outputs=outputs.get(row.job_id, ()),
                failure=_failure_text(view) if row.status is JobStatus.FAILED else "",
            )
        )
    truncated = len(rows) >= bound
    return LineageResult(
        by_source={key: tuple(children) for key, children in grouped.items()}, truncated=truncated
    )


__all__ = [
    "LineageResult",
    "LineageSource",
    "ReviewChild",
    "UNVERIFIED",
    "UNVERIFIED_NOTE",
    "VERIFIED",
    "VERIFIED_NOTE",
    "find_review_children",
    "repository_of",
]
