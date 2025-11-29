# Subsystem: Queue
# Role: Persists completed job history for inspection and learning.

"""Persistent history storage for queue jobs."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.queue.job_model import Job, JobStatus
from src.cluster.worker_model import WorkerId


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

    def to_json(self) -> str:
        data = asdict(self)
        data["status"] = self.status.value
        for key in ("created_at", "started_at", "completed_at"):
            value = data.get(key)
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return json.dumps(data, ensure_ascii=True)

    @staticmethod
    def from_json(line: str) -> "JobHistoryEntry":
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
        )


class JobHistoryStore:
    """Abstract store interface."""

    def record_job_submission(self, job: Job) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def record_status_change(
        self, job_id: str, status: JobStatus, ts: datetime, error: str | None = None
    ) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def list_jobs(
        self, status: JobStatus | None = None, limit: int = 50, offset: int = 0
    ) -> List[JobHistoryEntry]:  # pragma: no cover - interface
        raise NotImplementedError

    def get_job(self, job_id: str) -> Optional[JobHistoryEntry]:  # pragma: no cover - interface
        raise NotImplementedError


class JSONLJobHistoryStore(JobHistoryStore):
    """Append-only JSONL-backed job history."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record_job_submission(self, job: Job) -> None:
        entry = JobHistoryEntry(
            job_id=job.job_id,
            created_at=job.created_at,
            status=job.status,
            payload_summary=self._summarize_job(job),
            worker_id=getattr(job, "worker_id", None),
        )
        self._append(entry)

    def record_status_change(
        self, job_id: str, status: JobStatus, ts: datetime, error: str | None = None
    ) -> None:
        current = self.get_job(job_id)
        created_at = current.created_at if current else ts
        started_at = current.started_at
        completed_at = current.completed_at
        if status == JobStatus.RUNNING:
            started_at = started_at or ts
        if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            completed_at = ts

        entry = JobHistoryEntry(
            job_id=job_id,
            created_at=created_at,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            payload_summary=current.payload_summary if current else "",
            error_message=error or (current.error_message if current else None),
            worker_id=current.worker_id if current else None,
        )
        self._append(entry)

    def list_jobs(
        self, status: JobStatus | None = None, limit: int = 50, offset: int = 0
    ) -> List[JobHistoryEntry]:
        entries = list(self._load_latest_by_job().values())
        entries.sort(key=lambda e: e.created_at, reverse=True)
        if status:
            entries = [e for e in entries if e.status == status]
        return entries[offset : offset + limit]

    def get_job(self, job_id: str) -> Optional[JobHistoryEntry]:
        return self._load_latest_by_job().get(job_id)

    def _append(self, entry: JobHistoryEntry) -> None:
        line = entry.to_json()
        with self._lock:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def _load_latest_by_job(self) -> dict[str, JobHistoryEntry]:
        with self._lock:
            if not self._path.exists():
                return {}
            try:
                lines = self._path.read_text(encoding="utf-8").splitlines()
            except Exception:
                return {}
        latest: dict[str, JobHistoryEntry] = {}
        for line in lines:
            try:
                entry = JobHistoryEntry.from_json(line)
                latest[entry.job_id] = entry
            except Exception:
                continue
        return latest

    def _summarize_job(self, job: Job) -> str:
        cfg = getattr(job, "pipeline_config", None)
        if cfg:
            prompt = getattr(cfg, "prompt", "") or ""
            model = getattr(cfg, "model", "") or getattr(cfg, "model_name", "")
            return f"{prompt[:64]} | {model}"
        payload = getattr(job, "payload", None)
        if callable(payload):
            return "callable payload"
        return str(payload)[:80]
