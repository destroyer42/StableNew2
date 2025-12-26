# Subsystem: Queue
# Role: Persists completed job history for inspection and learning.

"""Persistent history storage for queue jobs.

PR-CORE1-B2/C2: For v2.6 jobs, history entries should include NJR snapshots in
the 'snapshot' field. The snapshot['normalized_job'] contains the
NormalizedJobRecord data. Legacy entries on disk may still expose pipeline_config
blobs, but new entries no longer persist pipeline_config—legacy_njr_adapter
reconstructs NJRs when needed.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.cluster.worker_model import WorkerId
from src.queue.job_model import Job, JobStatus

if TYPE_CHECKING:
    from src.pipeline.run_config import RunConfig


def _utcnow() -> datetime:
    return datetime.utcnow()


@dataclass
class JobHistoryEntry:
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
    # PR-112: Prompt origin tracking
    prompt_source: str = "manual"  # "manual" | "pack"
    prompt_pack_id: str | None = None
    prompt_keys: list[str] | None = None
    snapshot: dict[str, Any] | None = None
    duration_ms: int | None = None

    def to_json(self) -> str:
        data = asdict(self)
        data["status"] = self.status.value
        data["run_mode"] = self.run_mode
        data["prompt_source"] = self.prompt_source
        data["prompt_pack_id"] = self.prompt_pack_id
        data["prompt_keys"] = self.prompt_keys
        for key in ("created_at", "started_at", "completed_at"):
            value = data.get(key)
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        if self.duration_ms is not None:
            data["duration_ms"] = self.duration_ms
        return json.dumps(data, ensure_ascii=True)

    @staticmethod
    def from_json(line: str) -> JobHistoryEntry:
        raw = json.loads(line)

        def _parse_ts(value: str | None) -> datetime | None:
            if not value:
                return None
            return datetime.fromisoformat(value)

        return JobHistoryEntry(
            job_id=raw["job_id"],
            created_at=_parse_ts(raw.get("created_at")) or _utcnow(),
            status=JobStatus(raw.get("status", JobStatus.QUEUED)),
            payload_summary=raw.get("payload_summary", ""),
            started_at=_parse_ts(raw.get("started_at")),
            completed_at=_parse_ts(raw.get("completed_at")),
            error_message=raw.get("error_message"),
            worker_id=raw.get("worker_id"),
            result=raw.get("result"),
            run_mode=raw.get("run_mode", "queue"),
            prompt_source=raw.get("prompt_source", "manual"),
            prompt_pack_id=raw.get("prompt_pack_id"),
            prompt_keys=raw.get("prompt_keys"),
            snapshot=raw.get("snapshot"),
            duration_ms=int(raw["duration_ms"]) if raw.get("duration_ms") is not None else None,
        )


def job_history_entry_from_run_config(
    job_id: str,
    run_config: RunConfig,
    *,
    status: JobStatus = JobStatus.QUEUED,
    payload_summary: str = "",
    created_at: datetime | None = None,
    **extra: Any,
) -> JobHistoryEntry:
    """Create a JobHistoryEntry from a RunConfig.

    Args:
        job_id: Unique identifier for the job.
        run_config: The RunConfig containing prompt source info.
        status: Initial job status.
        payload_summary: Summary text for the job.
        created_at: Creation timestamp (defaults to now).
        **extra: Additional fields to set on the entry.

    Returns:
        A JobHistoryEntry with prompt origin fields populated.
    """
    return JobHistoryEntry(
        job_id=job_id,
        created_at=created_at or _utcnow(),
        status=status,
        payload_summary=payload_summary,
        run_mode=run_config.run_mode,
        prompt_source=run_config.prompt_source.value
        if hasattr(run_config.prompt_source, "value")
        else str(run_config.prompt_source),
        prompt_pack_id=run_config.prompt_pack_id,
        prompt_keys=list(run_config.prompt_keys) if run_config.prompt_keys else None,
        **extra,
    )


class JobHistoryStore:
    """Abstract store interface."""

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

    def get_job(self, job_id: str) -> JobHistoryEntry | None:  # pragma: no cover - interface
        raise NotImplementedError

    def save_entry(self, entry: JobHistoryEntry) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def register_callback(self, callback: Callable[[JobHistoryEntry], None]) -> None:
        raise NotImplementedError


class JSONLJobHistoryStore(JobHistoryStore):
    """Append-only JSONL-backed job history."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._callbacks: list[Callable[[JobHistoryEntry], None]] = []
        # Performance optimization: Cache loaded entries to avoid re-reading file on every list_jobs()
        self._cached_entries: dict[str, JobHistoryEntry] | None = None
        self._cache_mtime: float | None = None

    def record_job_submission(self, job: Job) -> None:
        entry = JobHistoryEntry(
            job_id=job.job_id,
            created_at=job.created_at,
            status=job.status,
            payload_summary=self._summarize_job(job),
            worker_id=getattr(job, "worker_id", None),
            run_mode=getattr(job, "run_mode", "queue"),
            snapshot=getattr(job, "snapshot", None),
        )
        self._append(entry)

    def record_status_change(
        self,
        job_id: str,
        status: JobStatus,
        ts: datetime,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        current = self.get_job(job_id)
        created_at = current.created_at if current else ts
        started_at = current.started_at
        completed_at = current.completed_at
        if status == JobStatus.RUNNING:
            started_at = started_at or ts
        if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            completed_at = ts

        duration_ms: int | None = None
        if started_at and completed_at:
            delta = completed_at - started_at
            duration_ms = int(delta.total_seconds() * 1000)

        entry = JobHistoryEntry(
            job_id=job_id,
            created_at=created_at,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            payload_summary=current.payload_summary if current else "",
            error_message=error or (current.error_message if current else None),
            worker_id=current.worker_id if current else None,
            result=result if result is not None else (current.result if current else None),
            run_mode=current.run_mode if current else "queue",
            snapshot=current.snapshot if current else None,
            duration_ms=duration_ms,
        )
        self._append(entry)

    def list_jobs(
        self, status: JobStatus | None = None, limit: int = 50, offset: int = 0
    ) -> list[JobHistoryEntry]:
        entries = list(self._load_latest_by_job().values())
        entries.sort(key=lambda e: e.created_at, reverse=True)
        if status:
            entries = [e for e in entries if e.status == status]
        return entries[offset : offset + limit]

    def get_job(self, job_id: str) -> JobHistoryEntry | None:
        return self._load_latest_by_job().get(job_id)

    def _append(self, entry: JobHistoryEntry) -> None:
        line = entry.to_json()
        with self._lock:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            # Invalidate cache after appending - file has been modified
            self._cache_mtime = None
        self._emit(entry)

    def save_entry(self, entry: JobHistoryEntry) -> None:
        self._append(entry)

    def register_callback(self, callback: Callable[[JobHistoryEntry], None]) -> None:
        self._callbacks.append(callback)

    def _emit(self, entry: JobHistoryEntry) -> None:
        for callback in list(self._callbacks):
            try:
                callback(entry)
            except Exception:
                continue

    def _load_latest_by_job(self) -> dict[str, JobHistoryEntry]:
        """Load history entries with file mtime-based caching for performance."""
        with self._lock:
            if not self._path.exists():
                self._cached_entries = {}
                self._cache_mtime = None
                return {}
            
            try:
                # Check if file has been modified since last cache
                current_mtime = self._path.stat().st_mtime
                
                if self._cached_entries is not None and self._cache_mtime == current_mtime:
                    # Cache is valid, return it
                    return self._cached_entries
                
                # Cache miss or stale - reload from disk
                lines = self._path.read_text(encoding="utf-8").splitlines()
                latest: dict[str, JobHistoryEntry] = {}
                for line in lines:
                    try:
                        entry = JobHistoryEntry.from_json(line)
                        latest[entry.job_id] = entry
                    except Exception:
                        continue
                
                # Update cache
                self._cached_entries = latest
                self._cache_mtime = current_mtime
                return latest
                
            except Exception:
                # On error, invalidate cache and return empty
                self._cached_entries = {}
                self._cache_mtime = None
                return {}

    def _summarize_job(self, job: Job) -> str:
        result = getattr(job, "result", None) or {}
        if isinstance(result, dict) and result.get("mode") == "prompt_pack_batch":
            total = result.get("total_entries", len(result.get("results") or []))
            first_prompt = ""
            try:
                first_entry = (result.get("results") or [])[0]
                first_prompt = (first_entry.get("prompt") or "").strip()
            except Exception:
                first_prompt = ""
            summary = f"{total} entries"
            if first_prompt:
                snippet = first_prompt if len(first_prompt) <= 60 else first_prompt[:60] + "?"
                summary += f" | {snippet}"
            return summary
        return job.summary()
