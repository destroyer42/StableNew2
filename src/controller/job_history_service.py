"""Controller-facing service for job history and queue introspection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_history_store import JobHistoryEntry, JobHistoryStore


@dataclass
class JobViewModel:
    job_id: str
    status: JobStatus
    created_at: str
    started_at: str | None
    completed_at: str | None
    payload_summary: str
    is_active: bool
    last_error: str | None = None
    worker_id: str | None = None
    result: Dict[str, Any] | None = None


class JobHistoryService:
    """Combine live queue state with persisted history for controller/GUI consumers."""

    def __init__(
        self,
        queue: JobQueue,
        history_store: JobHistoryStore,
        job_controller: Any | None = None,
    ) -> None:
        self._queue = queue
        self._history = history_store
        self._job_controller = job_controller
        self._callbacks: list[Callable[[JobHistoryEntry], None]] = []
        try:
            self._history.register_callback(self._on_history_update)
        except Exception:
            pass

    def register_callback(self, callback: Callable[[JobHistoryEntry], None]) -> None:
        self._callbacks.append(callback)

    def _on_history_update(self, entry: JobHistoryEntry) -> None:
        for callback in list(self._callbacks):
            try:
                callback(entry)
            except Exception:
                continue

    def record(self, job: Job, *, result: dict | None = None) -> None:
        try:
            entry = self._build_entry(job, status=JobStatus.COMPLETED, result=result)
            self._history.save_entry(entry)
        except Exception:
            pass

    def record_failure(self, job: Job, error: str | None = None) -> None:
        try:
            entry = self._build_entry(job, status=JobStatus.FAILED, error=error)
            self._history.save_entry(entry)
        except Exception:
            pass

    def list_active_jobs(self) -> List[JobViewModel]:
        active_statuses = {JobStatus.QUEUED, JobStatus.RUNNING}
        jobs = [j for j in self._queue.list_jobs() if j.status in active_statuses]
        return [self._from_job(j) for j in jobs]

    def list_recent_jobs(self, limit: int = 50, status: JobStatus | None = None) -> List[JobViewModel]:
        history_entries = self._history.list_jobs(status=status, limit=limit)
        active_by_id = {j.job_id: j for j in self._queue.list_jobs()}
        view_models: list[JobViewModel] = []
        for entry in history_entries:
            active_job = active_by_id.get(entry.job_id)
            if active_job:
                view_models.append(self._from_job(active_job))
            else:
                view_models.append(self._from_history(entry))
        return view_models

    def get_job(self, job_id: str) -> Optional[JobViewModel]:
        active = next((j for j in self._queue.list_jobs() if j.job_id == job_id), None)
        if active:
            return self._from_job(active)
        entry = self._history.get_job(job_id)
        if entry:
            return self._from_history(entry)
        return None

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a queued/running job via controller."""

        vm = self.get_job(job_id)
        if vm is None:
            return False
        if vm.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        cancel = getattr(self._job_controller, "cancel_job", None)
        if callable(cancel):
            try:
                cancel(job_id)
                return True
            except Exception:
                return False
        return False

    def retry_job(self, job_id: str) -> Optional[str]:
        """Retry a completed/failed job by re-submitting its payload."""

        vm = self.get_job(job_id)
        if vm is None or vm.status not in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return None

        original = self._queue.get_job(job_id)
        if original is None:
            return None

        submit = getattr(self._job_controller, "submit_pipeline_run", None)
        if callable(submit):
            try:
                return submit(original.payload, priority=original.priority)
            except Exception:
                return None
        return None

    def _from_job(self, job: Job) -> JobViewModel:
        is_active = job.status in {JobStatus.QUEUED, JobStatus.RUNNING}
        return JobViewModel(
            job_id=job.job_id,
            status=job.status,
            created_at=job.created_at.isoformat(),
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            payload_summary=self._summarize(job),
            is_active=is_active,
            last_error=job.error_message,
            worker_id=getattr(job, "worker_id", None),
            result=job.result,
        )

    def _from_history(self, entry: JobHistoryEntry) -> JobViewModel:
        return JobViewModel(
            job_id=entry.job_id,
            status=entry.status,
            created_at=entry.created_at.isoformat(),
            started_at=entry.started_at.isoformat() if entry.started_at else None,
            completed_at=entry.completed_at.isoformat() if entry.completed_at else None,
            payload_summary=entry.payload_summary,
            is_active=False,
            last_error=entry.error_message,
            worker_id=entry.worker_id,
            result=entry.result,
        )

    def _summarize(self, job: Job) -> str:
        cfg = getattr(job, "pipeline_config", None)
        if cfg:
            prompt = getattr(cfg, "prompt", "") or ""
            model = getattr(cfg, "model", "") or getattr(cfg, "model_name", "")
            return f"{prompt[:64]} | {model}"
        payload = getattr(job, "payload", None)
        if callable(payload):
            return "callable payload"
        return str(payload)[:80]

    def _build_entry(
        self,
        job: Job,
        *,
        status: JobStatus,
        result: dict | None = None,
        error: str | None = None,
    ) -> JobHistoryEntry:
        prompt_keys = None
        snapshot = getattr(job, "config_snapshot", None) or {}
        raw_keys = snapshot.get("prompt_keys")
        if isinstance(raw_keys, list):
            prompt_keys = raw_keys
        return JobHistoryEntry(
            job_id=job.job_id,
            created_at=job.created_at,
            status=status,
            payload_summary=self._summarize(job),
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=error or job.error_message,
            worker_id=getattr(job, "worker_id", None),
            run_mode=getattr(job, "run_mode", "queue"),
            result=result if result is not None else job.result,
            prompt_source=getattr(job, "prompt_source", "manual"),
            prompt_pack_id=getattr(job, "prompt_pack_id", None),
            prompt_keys=prompt_keys,
            snapshot=getattr(job, "snapshot", None),
        )


class NullHistoryService(JobHistoryService):
    """No-op history service for tests that don't care about history.

    PR-0114C-T(x): This class provides a safe, no-op implementation of
    JobHistoryService for test fixtures that:
    - Don't need to verify history recording.
    - Want to avoid real disk I/O or store dependencies.
    - Need a lightweight history stub for controller/GUI tests.

    Production code should never use this. It is strictly for test fixtures.
    """

    def __init__(self) -> None:
        """Initialize without queue or history store dependencies."""
        # Don't call super().__init__ - we don't need real dependencies
        self._queue = None
        self._history = None
        self._job_controller = None
        self._callbacks: list[Callable[[JobHistoryEntry], None]] = []

    def register_callback(self, callback: Callable[[JobHistoryEntry], None]) -> None:
        """Register callback (stored but never invoked)."""
        self._callbacks.append(callback)

    def _on_history_update(self, entry: JobHistoryEntry) -> None:
        """No-op history update handler."""
        pass

    def record(self, job: Job, *, result: dict | None = None) -> None:
        """No-op record for completed jobs."""
        pass

    def record_failure(self, job: Job, error: str | None = None) -> None:
        """No-op record for failed jobs."""
        pass

    def list_active_jobs(self) -> List[JobViewModel]:
        """Return empty list - no active jobs tracked."""
        return []

    def list_recent_jobs(self, limit: int = 50, status: JobStatus | None = None) -> List[JobViewModel]:
        """Return empty list - no history tracked."""
        return []

    def get_job(self, job_id: str) -> Optional[JobViewModel]:
        """Return None - no jobs tracked."""
        return None

    def cancel_job(self, job_id: str) -> bool:
        """Return False - cancellation not supported."""
        return False

    def retry_job(self, job_id: str) -> Optional[str]:
        """Return None - retry not supported."""
        return None
