# Subsystem: Queue
# Role: Defines controller-facing history projections for repository jobs.

"""History projection contracts implemented by the SQLite job repository."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.cluster.worker_model import WorkerId
from src.queue.job_model import Job, JobExecutionMetadata, JobStatus
from src.utils.error_envelope_v2 import UnifiedErrorEnvelope

if TYPE_CHECKING:
    from src.pipeline.run_config import RunConfig


INTERRUPTED_RESTART_ACTION_REQUIRED = "INTERRUPTED_RESTART_ACTION_REQUIRED"


def _utcnow() -> datetime:
    return datetime.utcnow()


@dataclass
class JobHistoryEntry:
    """Read model for one repository-backed job."""

    job_id: str
    created_at: datetime
    status: JobStatus
    payload_summary: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    worker_id: WorkerId | None = None
    run_mode: str = "queue"
    result: dict[str, Any] | None = None
    prompt_source: str = "manual"
    prompt_pack_id: str | None = None
    prompt_keys: list[str] | None = None
    snapshot: dict[str, Any] | None = None
    duration_ms: int | None = None
    error_envelope: UnifiedErrorEnvelope | None = None


@dataclass(frozen=True)
class BatchCandidateRow:
    """Raw persisted facts of a job that *may* belong to a batch (PR-BATCH-OPS-201).

    The repository returns every job whose immutable snapshot mentions a ``batch_id``; whether that is a
    valid, unambiguous batch identity is decided by ``src.queue.batch_membership``, not here.
    """

    job_id: str
    status: JobStatus
    priority: int
    queue_order: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    error_envelope: UnifiedErrorEnvelope | None
    result: dict[str, Any] | None
    execution_metadata: JobExecutionMetadata
    snapshot: dict[str, Any]
    #: Stable insertion cursor (SQLite ``rowid``). ``queue_order`` is renumbered by queue reordering, so it
    #: cannot page a scan.
    cursor: int = 0


@dataclass(frozen=True)
class ReplayChildRow:
    """A persisted job whose recorded lineage parent is another job and whose source is a history replay."""

    job_id: str
    parent_job_id: str
    status: JobStatus
    created_at: datetime
    snapshot: dict[str, Any]


def job_history_entry_from_run_config(
    job_id: str,
    run_config: RunConfig,
    *,
    status: JobStatus = JobStatus.QUEUED,
    payload_summary: str = "",
    created_at: datetime | None = None,
    **extra: Any,
) -> JobHistoryEntry:
    """Create a history projection from a run configuration."""
    return JobHistoryEntry(
        job_id=job_id,
        created_at=created_at or _utcnow(),
        status=status,
        payload_summary=payload_summary,
        run_mode=run_config.run_mode,
        prompt_source=(
            run_config.prompt_source.value
            if hasattr(run_config.prompt_source, "value")
            else str(run_config.prompt_source)
        ),
        prompt_pack_id=run_config.prompt_pack_id,
        prompt_keys=list(run_config.prompt_keys) if run_config.prompt_keys else None,
        **extra,
    )


class JobHistoryStore:
    """Projection interface implemented by the authoritative JobRepository."""

    def record_job_submission(self, job: Job) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def record_status_change(
        self,
        job_id: str,
        status: JobStatus,
        ts: datetime,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def list_jobs(
        self, status: JobStatus | None = None, limit: int = 50, offset: int = 0
    ) -> list[JobHistoryEntry]:  # pragma: no cover - interface
        raise NotImplementedError

    def list_recent_jobs(
        self,
        *,
        statuses: set[JobStatus] | None = None,
        limit: int = 50,
    ) -> list[JobHistoryEntry]:  # pragma: no cover - interface
        raise NotImplementedError

    def get_job(self, job_id: str) -> JobHistoryEntry | None:  # pragma: no cover - interface
        raise NotImplementedError

    def save_entry(self, entry: JobHistoryEntry) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def register_callback(self, callback: Callable[[JobHistoryEntry], None]) -> None:
        raise NotImplementedError
