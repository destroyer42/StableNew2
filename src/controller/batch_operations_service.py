"""Unified Review / Video Workflow batch operations (PR-BATCH-OPS-201).

Orchestrates the existing authorities and owns no state of its own beyond a single-use retry token:

* discovery and progress are *derived* from bounded reads of the SQLite ``JobRepository``
  (``src.queue.batch_projection``); nothing about a batch is persisted;
* Cancel Remaining acts through the guarded ``JobQueue.cancel_queued_jobs`` (QUEUED at the transition only);
* Retry compiles each selected FAILED job with the existing ``compile_replay_intent`` and crosses
  ``JobService.submit_njrs`` exactly once, so admission stays all-or-none;
* output navigation resolves persisted artifact references against the file system.

Every public method is blocking and thread-agnostic: call it from a worker, never from the Tk thread.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.image_backends.operation_compatibility import (
    OperationNotSupportedError,
    require_njr_operation,
)
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.replay_input_verification import frozen_input_checks, verify_inputs
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.batch_membership import BatchKey, build_selected_retry_descriptor
from src.queue.batch_projection import (
    BatchCatalog,
    BatchJobView,
    BatchSummary,
    OutputKind,
    RetryChildRef,
    attach_retry_children,
    build_catalog,
    retry_children_from_rows,
    with_artifact_availability,
)
from src.queue.job_history_store import BatchCandidateRow
from src.queue.job_model import JobStatus
from src.queue.job_queue import QueuedCancelOutcome

_PAGE_SIZE = 200
_MAX_CANDIDATES = 20_000
#: A retry child in one of these states means the failure was already retried (or is being retried).
_BLOCKING_CHILD_STATUSES = frozenset({JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.COMPLETED})


class BatchOperationRefused(RuntimeError):
    """An operation was refused before it changed anything; the message is operator-facing."""


@dataclass(frozen=True)
class BatchSnapshot:
    """One canonical refresh: the catalog plus the selected batch's detail, both derived, never stored."""

    catalog: BatchCatalog
    selected: BatchSummary | None
    webui_hold: dict[str, Any] | None
    queue_paused: bool
    loaded_at: datetime


@dataclass(frozen=True)
class CancelPlan:
    key: BatchKey
    target_job_ids: tuple[str, ...]
    #: Members that are not queued right now (running, finished or cancelled); never touched.
    untouched_count: int


@dataclass(frozen=True)
class CancelRemainingResult:
    key: BatchKey
    cancelled: tuple[str, ...]
    skipped: tuple[QueuedCancelOutcome, ...]
    errors: tuple[QueuedCancelOutcome, ...]

    @property
    def message(self) -> str:
        text = f"Cancelled {len(self.cancelled)} queued job(s) of {self.key.label}."
        if self.skipped:
            text += f" {len(self.skipped)} had already started or finished and were left untouched."
        if self.errors:
            text += f" {len(self.errors)} could not be cancelled: " + "; ".join(
                f"{item.job_id[:8]} ({item.detail})" for item in self.errors[:3]
            )
        return text


@dataclass(frozen=True)
class RetryItem:
    job_id: str
    source_label: str
    failure_label: str
    reasons: tuple[str, ...]
    acknowledgement_text: str | None

    @property
    def eligible(self) -> bool:
        return not self.reasons

    @property
    def acknowledgement_required(self) -> bool:
        return self.acknowledgement_text is not None


@dataclass(frozen=True)
class RetryPlan:
    token: str
    key: BatchKey
    items: tuple[RetryItem, ...]

    @property
    def ineligible(self) -> tuple[RetryItem, ...]:
        return tuple(item for item in self.items if not item.eligible)

    @property
    def acknowledgements(self) -> tuple[RetryItem, ...]:
        return tuple(item for item in self.items if item.acknowledgement_required)

    @property
    def submittable(self) -> bool:
        return bool(self.items) and not self.ineligible


@dataclass(frozen=True)
class RetrySubmission:
    #: (source job id, new job id) pairs in selection order; empty when nothing became durable.
    admitted: tuple[tuple[str, str], ...]
    retry_batch: BatchKey | None
    #: Observations after durable admission (auto-run off, paused, worker not running, follow-up error).
    notes: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        text = f"Admitted {len(self.admitted)} new retry job(s)"
        if self.retry_batch is not None:
            text += f" as {self.retry_batch.label}"
        text += ". The original failed jobs are unchanged."
        return text + (" " + " ".join(self.notes) if self.notes else "")


@dataclass(frozen=True)
class OutputResolution:
    images: tuple[str, ...] = ()
    videos: tuple[str, ...] = ()
    folders: tuple[str, ...] = ()
    #: ``(job_id, path, reason)`` for every referenced output that is missing, moved or not a valid image.
    unavailable: tuple[tuple[str, str, str], ...] = ()
    jobs_without_outputs: tuple[str, ...] = ()
    messages: tuple[str, ...] = field(default=())


class BatchOperationsService:
    def __init__(
        self,
        *,
        job_service: Any,
        page_size: int = _PAGE_SIZE,
        max_candidates: int = _MAX_CANDIDATES,
        replay_id_fn: Callable[[], str] | None = None,
        batch_id_fn: Callable[[], str] | None = None,
    ) -> None:
        self._job_service = job_service
        self._page_size = max(1, int(page_size))
        self._max_candidates = max(1, int(max_candidates))
        self._replay_id_fn = replay_id_fn
        self._batch_id_fn = batch_id_fn or (lambda: uuid.uuid4().hex)
        self._lock = threading.Lock()
        self._consumed_tokens: set[str] = set()
        self._retry_in_flight = False

    # -- authorities ----------------------------------------------------------------------------------------

    @property
    def _queue(self) -> Any:
        return self._job_service.job_queue

    @property
    def _repository(self) -> Any:
        return self._queue.repository

    # -- discovery / progress ---------------------------------------------------------------------------------

    def _scan(self) -> BatchCatalog:
        rows: list[BatchCandidateRow] = []
        cursor = 0
        truncated = False
        while True:
            page = self._repository.list_batch_candidate_rows(
                after_cursor=cursor, limit=self._page_size
            )
            rows.extend(page)
            if len(page) < self._page_size:
                break
            cursor = page[-1].cursor
            if len(rows) >= self._max_candidates:
                truncated = True
                break
        # The WebUI hold is the live queue's current annotation, read now - never remembered from an incident.
        held = {
            row.job_id
            for row in rows
            if row.status is JobStatus.QUEUED and self._queue.is_job_held(row.job_id)
        }
        return build_catalog(rows, held_job_ids=held, truncated=truncated)

    def refresh(self, selected: BatchKey | None = None) -> BatchSnapshot:
        """One bounded read of the repository plus, for the selected batch, its retry children and files."""

        catalog = self._scan()
        detail = catalog.get(selected)
        if detail is not None:
            detail = self._describe(detail)
        return BatchSnapshot(
            catalog=catalog,
            selected=detail,
            webui_hold=self._queue.webui_hold_info(),
            queue_paused=bool(self._queue.is_paused()),
            loaded_at=datetime.utcnow(),
        )

    def _describe(self, summary: BatchSummary) -> BatchSummary:
        children = retry_children_from_rows(
            self._repository.list_replay_child_rows([job.job_id for job in summary.jobs])
        )
        summary = attach_retry_children(summary, children)
        paths = {ref.path for job in summary.jobs for ref in job.artifacts}
        return with_artifact_availability(summary, {path: Path(path).is_file() for path in paths})

    def _require(self, key: BatchKey) -> BatchSummary:
        summary = self._scan().get(key)
        if summary is None:
            raise BatchOperationRefused(f"{key.label} was not found in the job repository.")
        if summary.conflicting:
            raise BatchOperationRefused(
                f"{key.label} has conflicting membership records, so no operation is offered: "
                + " ".join(summary.notes)
            )
        return summary

    # -- Cancel Remaining -----------------------------------------------------------------------------------

    def plan_cancel_remaining(self, key: BatchKey) -> CancelPlan:
        summary = self._require(key)
        targets = tuple(job.job_id for job in summary.jobs if job.status is JobStatus.QUEUED)
        return CancelPlan(key, targets, len(summary.jobs) - len(targets))

    def cancel_remaining(
        self, key: BatchKey, *, confirmed_job_ids: Sequence[str] | None = None
    ) -> CancelRemainingResult:
        """Re-resolve the batch from the repository, then cancel only members still QUEUED right now.

        ``confirmed_job_ids`` (what the operator confirmed) bounds the targets: a member that has since
        returned to the queue is not cancelled unconfirmed. Each cancel re-checks QUEUED at the transition.
        """

        plan = self.plan_cancel_remaining(key)
        targets = list(plan.target_job_ids)
        skipped: list[QueuedCancelOutcome] = []
        if confirmed_job_ids is not None:
            confirmed = list(dict.fromkeys(confirmed_job_ids))
            targets = [job_id for job_id in confirmed if job_id in plan.target_job_ids]
            skipped.extend(
                QueuedCancelOutcome(job_id, "skipped", None, "no longer queued")
                for job_id in confirmed
                if job_id not in plan.target_job_ids
            )
        outcomes = self._queue.cancel_queued_jobs(
            targets, reason=f"batch cancel remaining ({key.label})"
        )
        return CancelRemainingResult(
            key=key,
            cancelled=tuple(item.job_id for item in outcomes if item.outcome == "cancelled"),
            skipped=(*skipped, *(item for item in outcomes if item.outcome == "skipped")),
            errors=tuple(item for item in outcomes if item.outcome == "error"),
        )

    # -- Retry Selected Failed ------------------------------------------------------------------------------

    def _assess_retry(
        self, job: BatchJobView | None, job_id: str, children: Sequence[RetryChildRef]
    ) -> tuple[RetryItem, NormalizedJobRecord | None]:
        reasons: list[str] = []
        record: NormalizedJobRecord | None = None
        label = job.source_label if job is not None else job_id[:8]
        failure_label = job.failure.label if job is not None and job.failure is not None else ""
        if job is None:
            reasons.append("Not a member of this batch.")
        elif job.status is not JobStatus.FAILED:
            reasons.append(f"The job is {job.status.value}; only FAILED jobs can be retried.")
        for child in children:
            if child.status in _BLOCKING_CHILD_STATUSES:
                reasons.append(
                    f"Already retried as {child.job_id[:8]} ({child.status.value}); "
                    "retrying again would duplicate it."
                )
        if job is not None and job.status is JobStatus.FAILED:
            record = self._source_record(job_id, reasons)
        if record is not None:
            reasons.extend(self._admission_problems(record))
        acknowledgement = (
            job.failure.acknowledgement_text
            if job is not None and job.failure is not None
            else None
        )
        return RetryItem(job_id, label, failure_label, tuple(reasons), acknowledgement), record

    def _source_record(self, job_id: str, reasons: list[str]) -> NormalizedJobRecord | None:
        try:
            persisted = self._repository.get_job_model(job_id)
            record = getattr(persisted, "_normalized_record", None)
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"The stored job record cannot be reconstructed ({type(exc).__name__}).")
            return None
        if not isinstance(record, NormalizedJobRecord):
            reasons.append("The stored job record cannot be reconstructed.")
            return None
        return record

    def _admission_problems(self, record: NormalizedJobRecord) -> list[str]:
        """Would today's policy admit this replay, and are its frozen inputs still intact?"""

        problems = [issue.describe() for issue in verify_inputs(frozen_input_checks(record))]
        replay = compile_replay_intent(ReplayIntent(record))
        validator = getattr(self._job_service, "_validate_normalized_record", None)
        if callable(validator):
            ok, details = validator(replay)
            if not ok:
                problems.append(str(details.get("message") or "Rejected by submission validation."))
        if replay.workload_kind.value == "image":
            try:
                require_njr_operation(replay)
            except OperationNotSupportedError as exc:
                problems.append(str(exc).splitlines()[0])
        return problems

    def preflight_retry(self, key: BatchKey, job_ids: Sequence[str]) -> RetryPlan:
        """Assess EVERY selected job; ineligible ones are listed, never silently dropped."""

        return self._preflight(key, job_ids)[0]

    def _preflight(
        self, key: BatchKey, job_ids: Sequence[str]
    ) -> tuple[RetryPlan, list[NormalizedJobRecord | None]]:
        summary = self._require(key)
        ordered = list(dict.fromkeys(job_ids))
        children = retry_children_from_rows(self._repository.list_replay_child_rows(ordered))
        items: list[RetryItem] = []
        records: list[NormalizedJobRecord | None] = []
        for job_id in ordered:
            item, record = self._assess_retry(summary.job(job_id), job_id, children.get(job_id, ()))
            items.append(item)
            records.append(record)
        return RetryPlan(uuid.uuid4().hex, key, tuple(items)), records

    def submit_retry(
        self, plan: RetryPlan, *, acknowledged_job_ids: Sequence[str] = ()
    ) -> RetrySubmission:
        """Re-verify the selection against current repository truth, then admit it with ONE submit_njrs call."""

        with self._lock:
            if plan.token in self._consumed_tokens:
                raise BatchOperationRefused("This retry selection was already submitted.")
            if self._retry_in_flight:
                raise BatchOperationRefused("A retry is already being submitted; please wait.")
            self._retry_in_flight = True
        try:
            if not plan.submittable:
                raise BatchOperationRefused(
                    "Some selected jobs cannot be retried. Revise the selection: "
                    + "; ".join(f"{i.source_label}: {' '.join(i.reasons)}" for i in plan.ineligible)
                    if plan.items
                    else "No failed jobs are selected."
                )
            acknowledged = set(acknowledged_job_ids)
            missing = [item for item in plan.acknowledgements if item.job_id not in acknowledged]
            if missing:
                raise BatchOperationRefused(
                    "Acknowledgement required before generating again: "
                    + "; ".join(f"{item.source_label}: {item.acknowledgement_text}" for item in missing)
                )
            fresh, records = self._preflight(plan.key, [item.job_id for item in plan.items])
            if not fresh.submittable:
                raise BatchOperationRefused(
                    "The selection changed since it was reviewed; review it again: "
                    + "; ".join(f"{i.source_label}: {' '.join(i.reasons)}" for i in fresh.ineligible)
                )
            return self._admit(plan, [record for record in records if record is not None])
        finally:
            with self._lock:
                self._retry_in_flight = False

    def _admit(self, plan: RetryPlan, sources: list[NormalizedJobRecord]) -> RetrySubmission:
        count = len(sources)
        batch_key: BatchKey | None = None
        batch_id = None
        if count > 1:
            batch_id = self._batch_id_fn()
            batch_key = BatchKey.from_token(f"selected_retry:{batch_id}")
        replays = [
            compile_replay_intent(
                ReplayIntent(
                    source,
                    batch=build_selected_retry_descriptor(batch_id, source_index=index, source_count=count)
                    if batch_id
                    else None,
                ),
                id_fn=self._replay_id_fn,
            )
            for index, source in enumerate(sources)
        ]
        with self._lock:
            self._consumed_tokens.add(plan.token)
        pairs = tuple((source.job_id, replay.job_id) for source, replay in zip(sources, replays, strict=True))
        notes: list[str] = []
        existing = self._repository.identities()
        try:
            self._job_service.submit_njrs(replays, SubmissionPolicy())
        except Exception as exc:  # noqa: BLE001
            # Only identities that did not exist before this call can be this call's durable admissions.
            durable = self._repository.identities() - existing
            admitted = tuple(pair for pair in pairs if pair[1] in durable)
            if not admitted:
                raise BatchOperationRefused(
                    f"Nothing was admitted: {type(exc).__name__}: {exc}"
                ) from exc
            notes.append(
                f"The jobs were durably admitted but a follow-up step raised {type(exc).__name__}: {exc}."
            )
            return RetrySubmission(admitted, batch_key if len(admitted) == count else None, tuple(notes))
        notes.extend(self._queue_notes())
        return RetrySubmission(pairs, batch_key, tuple(notes))

    def _queue_notes(self) -> list[str]:
        service, notes = self._job_service, []
        if self._queue.is_paused():
            notes.append("The queue is paused; the retries wait until you resume it.")
        elif not getattr(service, "auto_run_enabled", True):
            notes.append("Auto-run is off; start the queue to run them.")
        elif not service.runner.is_running():
            notes.append("The queue worker is not running (it may have failed to start); use Resume.")
        return notes

    # -- Output navigation ----------------------------------------------------------------------------------

    def resolve_outputs(
        self, key: BatchKey, job_ids: Sequence[str], *, hash_images: bool = True
    ) -> OutputResolution:
        """Existing, usable output files of the selected jobs, in selection order then artifact order."""

        summary = self._scan().get(key)
        if summary is None:
            raise BatchOperationRefused(f"{key.label} was not found in the job repository.")
        images: list[str] = []
        videos: list[str] = []
        folders: list[str] = []
        unavailable: list[tuple[str, str, str]] = []
        without: list[str] = []
        for job_id in dict.fromkeys(job_ids):
            job = summary.job(job_id)
            if job is None or not job.artifacts:
                without.append(job_id)
                continue
            for ref in job.artifacts:
                path = Path(ref.path)
                if not path.is_file():
                    unavailable.append((job_id, ref.path, "missing or moved"))
                    continue
                folder = str(path.parent)
                if folder not in folders:
                    folders.append(folder)
                if ref.kind is OutputKind.VIDEO and ref.path not in videos:
                    videos.append(ref.path)
                elif ref.kind is OutputKind.IMAGE and ref.path not in images:
                    if not hash_images or _is_valid_image(path):
                        images.append(ref.path)
                    else:
                        unavailable.append((job_id, ref.path, "not a readable image"))
        messages: list[str] = []
        if without:
            messages.append(f"{len(without)} selected job(s) have no recorded output.")
        if unavailable:
            messages.append(f"{len(unavailable)} recorded output file(s) are missing or unreadable.")
        return OutputResolution(
            tuple(images), tuple(videos), tuple(folders), tuple(unavailable), tuple(without), tuple(messages)
        )


def _is_valid_image(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.verify()
    except Exception:  # noqa: BLE001 - any decode failure means "not a usable image"
        return False
    return True


__all__ = [
    "BatchOperationRefused",
    "BatchOperationsService",
    "BatchSnapshot",
    "CancelPlan",
    "CancelRemainingResult",
    "OutputResolution",
    "RetryItem",
    "RetryPlan",
    "RetrySubmission",
]
