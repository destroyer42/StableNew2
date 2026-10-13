# Subsystem: Queue
# Role: Pure derivation of batch summaries from repository rows (PR-BATCH-OPS-201).

"""Derive display-level batch state from canonical persisted job rows.

Everything here is computed, never stored: counts come from canonical ``JobStatus`` values, the aggregate
state is a pure function of those counts, and the WebUI-held annotation is a transient eligibility flag
supplied by the caller from the *current* ``JobQueue`` (it is not a sixth ``JobStatus`` and is never
inferred from an old incident). No function here performs I/O or mutates a row, job or record.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Container, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from pathlib import PurePath
from typing import Any

from src.pipeline.result_contract_v26 import collect_canonical_artifacts
from src.queue.batch_membership import (
    BatchKey,
    BatchKind,
    MembershipState,
    ReplayOrigin,
    replay_origin_of,
    resolve_batch_membership,
)
from src.queue.failure_triage import FailureTriage, TriageCategory, triage_failure
from src.queue.job_history_store import BatchCandidateRow, ReplayChildRow
from src.queue.job_model import JobPriority, JobStatus

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"})
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".mkv", ".avi", ".webm"})
#: Kinds whose declared ``source_count`` equals the number of jobs (one job per source).
_ONE_JOB_PER_SOURCE = frozenset({BatchKind.VIDEO_WORKFLOW, BatchKind.SELECTED_RETRY})
_ACTIVE_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)


class OutputKind(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    OTHER = "other"


class BatchAggregateState(str, Enum):
    """Display-only; never persisted and never used to change a job."""

    ACTIVE = "Active"
    WAITING = "Waiting"
    COMPLETED = "Completed"
    COMPLETED_WITH_FAILURES = "Completed with failures"
    COMPLETED_WITH_CANCELLATIONS = "Completed with cancellations"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


@dataclass(frozen=True, slots=True)
class StatusCounts:
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0

    @property
    def total(self) -> int:
        return self.queued + self.running + self.completed + self.failed + self.cancelled

    @classmethod
    def of(cls, statuses: Iterable[JobStatus]) -> StatusCounts:
        counted = Counter(statuses)
        return cls(
            queued=counted[JobStatus.QUEUED],
            running=counted[JobStatus.RUNNING],
            completed=counted[JobStatus.COMPLETED],
            failed=counted[JobStatus.FAILED],
            cancelled=counted[JobStatus.CANCELLED],
        )


def derive_aggregate_state(counts: StatusCounts) -> BatchAggregateState:
    if counts.running:
        return BatchAggregateState.ACTIVE
    if counts.queued:
        return BatchAggregateState.WAITING
    if counts.failed:
        return (
            BatchAggregateState.COMPLETED_WITH_FAILURES
            if counts.completed
            else BatchAggregateState.FAILED
        )
    if counts.cancelled:
        return (
            BatchAggregateState.COMPLETED_WITH_CANCELLATIONS
            if counts.completed
            else BatchAggregateState.CANCELLED
        )
    return BatchAggregateState.COMPLETED


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    path: str
    kind: OutputKind
    stage: str | None
    #: ``result`` (canonical result), ``checkpoint`` (stage checkpoint) or ``partial`` (failure metadata).
    origin: str
    #: ``None`` until a caller verifies the file system off the Tk thread.
    available: bool | None = None


@dataclass(frozen=True, slots=True)
class CheckpointView:
    stage_name: str
    output_count: int


@dataclass(frozen=True, slots=True)
class RetryChildRef:
    job_id: str
    status: JobStatus
    #: The new selected-retry batch the child belongs to, when it was submitted as part of one.
    batch: BatchKey | None


@dataclass(frozen=True, slots=True)
class BatchJobView:
    job_id: str
    key: BatchKey
    status: JobStatus
    priority: int
    queue_order: int
    cursor: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    source_index: int | None
    workload_kind: str
    source_paths: tuple[str, ...]
    source_label: str
    model_label: str
    #: Transient: queued AND currently held by the live WebUI outage hold.
    held_by_webui: bool
    failure: FailureTriage | None
    artifacts: tuple[ArtifactRef, ...]
    checkpoints: tuple[CheckpointView, ...]
    parent_job_id: str | None
    replay_origin: ReplayOrigin | None
    retry_children: tuple[RetryChildRef, ...] = ()
    last_control_action: str | None = None
    hydration_error: str | None = None
    #: Transient: queued AND currently held by the GPU device-loss quarantine (PR-QUEUE-GPU-180).
    held_by_gpu_loss: bool = False
    #: Classification inputs for the shared content-visibility policy (prompts, pack name, recorded rating).
    #: Never displayed; a presentation layer hands it to ``ContentVisibilityResolver``.
    visibility_subject: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def priority_label(self) -> str:
        try:
            return JobPriority(self.priority).name.title()
        except ValueError:
            return str(self.priority)

    @property
    def is_failed(self) -> bool:
        return self.status is JobStatus.FAILED

    @property
    def has_outputs(self) -> bool:
        return bool(self.artifacts)


@dataclass(frozen=True, slots=True)
class BatchSummary:
    key: BatchKey
    jobs: tuple[BatchJobView, ...]
    counts: StatusCounts
    state: BatchAggregateState
    declared_source_count: int | None
    #: Sum of per-job source images; may differ from the declared count and from the job count.
    covered_source_count: int
    held_count: int
    first_created_at: datetime
    last_activity_at: datetime
    workload_kinds: tuple[str, ...]
    origin_batch: BatchKey | None
    failure_categories: tuple[tuple[TriageCategory, int], ...]
    conflicting: bool
    notes: tuple[str, ...]
    #: Queued members held by the GPU device-loss quarantine (``held_count`` is the WebUI hold's).
    gpu_held_count: int = 0

    @property
    def job_count(self) -> int:
        return self.counts.total

    @property
    def missing_member_count(self) -> int:
        """Declared one-job-per-source members absent from the repository (never inferred for Review)."""

        if self.key.kind not in _ONE_JOB_PER_SOURCE or self.declared_source_count is None:
            return 0
        return max(0, self.declared_source_count - self.job_count)

    def job(self, job_id: str) -> BatchJobView | None:
        return next((job for job in self.jobs if job.job_id == job_id), None)


@dataclass(frozen=True, slots=True)
class BatchCatalog:
    summaries: tuple[BatchSummary, ...]
    #: Jobs whose identifiers contradict each other; they belong to no batch.
    ambiguous_job_ids: tuple[str, ...] = ()
    candidates_scanned: int = 0
    truncated: bool = False
    #: Replays recorded before replay stopped inheriting batch membership: they carry copied batch markers
    #: but are retries of a member, never members themselves.
    legacy_replay_job_ids: tuple[str, ...] = ()

    def get(self, key: BatchKey | None) -> BatchSummary | None:
        return next((summary for summary in self.summaries if summary.key == key), None)


# ---------------------------------------------------------------------------------------------------------------
# Row -> job view
# ---------------------------------------------------------------------------------------------------------------


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def snapshot_metadata(snapshot: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """``provenance.metadata`` of a persisted snapshot, read without hydrating the NJR."""

    data = _mapping(snapshot)
    normalized = _mapping(data.get("normalized_job")) or data
    return _mapping(_mapping(normalized.get("provenance")).get("metadata"))


def snapshot_source_kind(snapshot: Mapping[str, Any] | None) -> str:
    data = _mapping(snapshot)
    normalized = _mapping(data.get("normalized_job")) or data
    return str(_mapping(normalized.get("source")).get("kind") or "")


def classify_output(path: str, artifact_type: str | None = None) -> OutputKind:
    suffix = PurePath(path).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return OutputKind.IMAGE
    if suffix in VIDEO_SUFFIXES:
        return OutputKind.VIDEO
    if str(artifact_type or "").lower() == "video":
        return OutputKind.VIDEO
    return OutputKind.OTHER


def collect_artifact_refs(
    result: Mapping[str, Any] | None,
    checkpoints: Sequence[Any] = (),
) -> tuple[ArtifactRef, ...]:
    """Deterministic, de-duplicated output references: result artifacts first, then checkpoint/partial paths.

    A FAILED job's result and checkpoints are inspected too, because failure is not proof of no output.
    """

    refs: list[ArtifactRef] = []
    seen: set[str] = set()

    def add(path: Any, artifact_type: str | None, stage: str | None, origin: str) -> None:
        text = str(path or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        refs.append(ArtifactRef(text, classify_output(text, artifact_type), stage, origin))

    for artifact in collect_canonical_artifacts(result):
        stage = str(artifact.get("stage") or "") or None
        paths = list(artifact.get("output_paths") or []) or [artifact.get("primary_path")]
        for path in paths:
            add(path, artifact.get("artifact_type"), stage, "result")
        add(artifact.get("thumbnail_path"), None, stage, "thumbnail")
    for checkpoint in checkpoints:
        stage = str(getattr(checkpoint, "stage_name", "") or "") or None
        for path in getattr(checkpoint, "output_paths", ()) or ():
            add(path, None, stage, "checkpoint")
    metadata = _mapping(_mapping(result).get("metadata"))
    for path in metadata.get("completed_output_paths") or ():
        add(path, None, None, "partial")
    return tuple(refs)


def _hydrated_facts(
    snapshot: Mapping[str, Any],
) -> tuple[str, tuple[str, ...], str, str, str | None, dict[str, Any]]:
    """``(workload_kind, source_paths, source_label, model_label, error, visibility_subject)`` from the NJR."""

    from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot

    try:
        record = normalized_job_from_snapshot(dict(snapshot))
    except Exception as exc:  # noqa: BLE001 - one corrupt snapshot must not hide the rest of the batch
        return "unknown", (), "", "", f"Stored job record cannot be reconstructed: {exc}", {}
    if record is None:
        return "unknown", (), "", "", "Stored job record cannot be reconstructed.", {}
    metadata = record.extra_metadata
    workflow = _mapping(metadata.get("video_workflow"))
    identity = _mapping(workflow.get("source_identity"))
    original = str(identity.get("original_path") or "").strip()
    sources = (original,) if original else tuple(str(p) for p in record.input_image_paths)
    label = PurePath(sources[0]).name if sources else ""
    if len(sources) > 1:
        label = f"{label} (+{len(sources) - 1} more)"
    if workflow:
        model = str(workflow.get("display_name") or workflow.get("workflow_id") or "")
    else:
        model = str(record.base_model or "")
    subject = {
        "name": str(record.prompt_pack_name or ""),
        "positive_prompt": record.positive_prompt,
        "negative_prompt": record.negative_prompt,
        "content_visibility": metadata.get("content_visibility"),
    }
    return record.workload_kind.value, sources, label, model, None, subject


def job_view_from_row(
    row: BatchCandidateRow,
    key: BatchKey,
    *,
    source_index: int | None,
    held_job_ids: Container[str] = (),
    gpu_held_job_ids: Container[str] = (),
) -> BatchJobView:
    metadata = snapshot_metadata(row.snapshot)
    workload, sources, label, model, error, subject = _hydrated_facts(row.snapshot)
    checkpoints = tuple(row.execution_metadata.stage_checkpoints)
    normalized = _mapping(_mapping(row.snapshot).get("normalized_job"))
    parent_job_id = str(_mapping(normalized.get("source")).get("parent_job_id") or "") or None
    failure = None
    if row.status is JobStatus.FAILED:
        failure = triage_failure(
            error_message=row.error_message,
            envelope=row.error_envelope,
            result=row.result,
            last_control_action=row.execution_metadata.last_control_action,
        )
    return BatchJobView(
        job_id=row.job_id,
        key=key,
        status=row.status,
        priority=row.priority,
        queue_order=row.queue_order,
        cursor=row.cursor,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        source_index=source_index,
        workload_kind=workload,
        source_paths=sources,
        source_label=label,
        model_label=model,
        held_by_webui=row.status is JobStatus.QUEUED and row.job_id in held_job_ids,
        failure=failure,
        artifacts=collect_artifact_refs(row.result, checkpoints),
        checkpoints=tuple(
            CheckpointView(item.stage_name, len(item.output_paths)) for item in checkpoints
        ),
        parent_job_id=parent_job_id,
        replay_origin=replay_origin_of(metadata),
        last_control_action=row.execution_metadata.last_control_action,
        hydration_error=error,
        held_by_gpu_loss=row.status is JobStatus.QUEUED and row.job_id in gpu_held_job_ids,
        visibility_subject=subject,
    )


# ---------------------------------------------------------------------------------------------------------------
# Rows -> catalog
# ---------------------------------------------------------------------------------------------------------------


def _sort_key(job: BatchJobView) -> tuple[int, int, int, str]:
    # Declared source order when present, otherwise insertion order; the job id breaks every tie.
    return (
        0 if job.source_index is not None else 1,
        job.source_index if job.source_index is not None else 0,
        job.cursor,
        job.job_id,
    )


def _summarize(key: BatchKey, jobs: list[BatchJobView], declared: list[int | None]) -> BatchSummary:
    ordered = tuple(sorted(jobs, key=_sort_key))
    counts = StatusCounts.of(job.status for job in ordered)
    notes: list[str] = []
    declared_values = sorted({value for value in declared if value is not None})
    if len(declared_values) > 1:
        notes.append(
            "Jobs declare different source counts "
            f"({', '.join(str(value) for value in declared_values)}); membership is uncertain."
        )
    indexes = [job.source_index for job in ordered if job.source_index is not None]
    if len(indexes) != len(set(indexes)):
        notes.append("More than one job claims the same source position; membership is uncertain.")
    conflicting = bool(notes)
    declared_count = declared_values[0] if len(declared_values) == 1 else None
    origins = {job.replay_origin.key for job in ordered if job.replay_origin is not None}
    origin_batch = next(iter(origins)) if len(origins) == 1 and None not in origins else None
    if key.kind is BatchKind.SELECTED_RETRY and len(origins) > 1:
        notes.append("Retried jobs came from more than one original batch.")
    failures = Counter(job.failure.category for job in ordered if job.failure is not None)
    summary = BatchSummary(
        key=key,
        jobs=ordered,
        counts=counts,
        state=derive_aggregate_state(counts),
        declared_source_count=declared_count,
        covered_source_count=sum(len(job.source_paths) for job in ordered),
        held_count=sum(1 for job in ordered if job.held_by_webui),
        first_created_at=min(job.created_at for job in ordered),
        last_activity_at=max(job.completed_at or job.started_at or job.created_at for job in ordered),
        workload_kinds=tuple(sorted({job.workload_kind for job in ordered})),
        origin_batch=origin_batch,
        failure_categories=tuple(sorted(failures.items(), key=lambda item: item[0].value)),
        conflicting=conflicting,
        notes=tuple(notes),
        gpu_held_count=sum(1 for job in ordered if job.held_by_gpu_loss),
    )
    missing = summary.missing_member_count
    if missing:
        summary = replace(
            summary,
            notes=(*summary.notes, f"{missing} declared job(s) are not present in the repository."),
        )
    return summary


def build_catalog(
    rows: Iterable[BatchCandidateRow],
    *,
    held_job_ids: Container[str] = (),
    gpu_held_job_ids: Container[str] = (),
    truncated: bool = False,
) -> BatchCatalog:
    """Group candidate rows by composite ``(kind, batch_id)``; ordinary and ambiguous jobs join no batch."""

    grouped: dict[BatchKey, list[BatchJobView]] = {}
    declared: dict[BatchKey, list[int | None]] = {}
    ambiguous: list[str] = []
    legacy_replays: list[str] = []
    scanned = 0
    for row in rows:
        scanned += 1
        resolution = resolve_batch_membership(snapshot_metadata(row.snapshot))
        if resolution.state is MembershipState.AMBIGUOUS:
            ambiguous.append(row.job_id)
            continue
        membership = resolution.membership
        if membership is None:
            continue
        if (
            snapshot_source_kind(row.snapshot) == "history_replay"
            and membership.key.kind is not BatchKind.SELECTED_RETRY
        ):
            # A replay is a new submission. Only a selected-retry batch is a legitimate replay membership;
            # any other batch marker on a replay was copied by the pre-201 compiler, so it is a retry
            # child of its parent (found through lineage), never a member of the parent's batch.
            legacy_replays.append(row.job_id)
            continue
        grouped.setdefault(membership.key, []).append(
            job_view_from_row(
                row,
                membership.key,
                source_index=membership.source_index,
                held_job_ids=held_job_ids,
                gpu_held_job_ids=gpu_held_job_ids,
            )
        )
        declared.setdefault(membership.key, []).append(membership.declared_source_count)
    summaries = [_summarize(key, jobs, declared[key]) for key, jobs in grouped.items()]
    summaries.sort(key=lambda item: (item.first_created_at, item.key.to_token()), reverse=True)
    return BatchCatalog(
        summaries=tuple(summaries),
        ambiguous_job_ids=tuple(ambiguous),
        candidates_scanned=scanned,
        truncated=truncated,
        legacy_replay_job_ids=tuple(legacy_replays),
    )


def retry_children_from_rows(children: Iterable[ReplayChildRow]) -> dict[str, tuple[RetryChildRef, ...]]:
    """Index replay children by the parent they replayed; a child's own batch is its retry batch."""

    by_parent: dict[str, list[RetryChildRef]] = {}
    for child in children:
        resolution = resolve_batch_membership(snapshot_metadata(child.snapshot))
        key = resolution.membership.key if resolution.membership is not None else None
        by_parent.setdefault(child.parent_job_id, []).append(
            RetryChildRef(child.job_id, child.status, key)
        )
    return {parent: tuple(items) for parent, items in by_parent.items()}


def attach_retry_children(
    summary: BatchSummary, children: Mapping[str, Sequence[RetryChildRef]]
) -> BatchSummary:
    """Annotate members with their retry children. Counts are unchanged: a child is never an original member."""

    if not children:
        return summary
    return replace(
        summary,
        jobs=tuple(replace(job, retry_children=tuple(children.get(job.job_id, ()))) for job in summary.jobs),
    )


def with_artifact_availability(
    summary: BatchSummary, availability: Mapping[str, bool]
) -> BatchSummary:
    """Stamp verified file availability onto artifact references (the caller did the file I/O off Tk)."""

    return replace(
        summary,
        jobs=tuple(
            replace(
                job,
                artifacts=tuple(
                    replace(ref, available=availability.get(ref.path, ref.available))
                    for ref in job.artifacts
                ),
            )
            for job in summary.jobs
        ),
    )


__all__ = [
    "IMAGE_SUFFIXES",
    "VIDEO_SUFFIXES",
    "ArtifactRef",
    "BatchAggregateState",
    "BatchCatalog",
    "BatchJobView",
    "BatchSummary",
    "CheckpointView",
    "OutputKind",
    "RetryChildRef",
    "StatusCounts",
    "attach_retry_children",
    "build_catalog",
    "classify_output",
    "collect_artifact_refs",
    "derive_aggregate_state",
    "job_view_from_row",
    "retry_children_from_rows",
    "snapshot_metadata",
    "snapshot_source_kind",
    "with_artifact_availability",
]
