# Subsystem: Queue
# Role: Defines the Job domain model, statuses, and priorities.

"""Job model for single-node and future cluster execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional

import time

from src.cluster.worker_model import WorkerId
from src.utils.error_envelope_v2 import serialize_envelope, UnifiedErrorEnvelope


class JobPriority(IntEnum):
    LOW = 0
    NORMAL = 1
    HIGH = 2


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RetryAttempt:
    stage: str
    attempt_index: int
    max_attempts: int
    reason: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class JobExecutionMetadata:
    """Metadata used to track external processes spawned for a job."""

    external_pids: list[int] = field(default_factory=list)
    retry_attempts: list[RetryAttempt] = field(default_factory=list)


def _utcnow() -> datetime:
    return datetime.utcnow()


@dataclass
class Job:
    job_id: str
    priority: JobPriority = JobPriority.NORMAL
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    learning_enabled: bool = False
    randomizer_metadata: Optional[Dict[str, Any]] = None
    lora_settings: Optional[Dict[str, Dict[str, Any]]] = None
    error_message: Optional[str] = None
    error_envelope: UnifiedErrorEnvelope | None = None
    result: Optional[Dict[str, Any]] = None
    payload: Any | None = None
    worker_id: WorkerId | None = None
    run_mode: str = "queue"
    # PR-106: Metadata fields for provenance tracking
    source: str = "unknown"
    prompt_source: str = "manual"
    prompt_pack_id: Optional[str] = None
    config_snapshot: Optional[Dict[str, Any]] = None
    # PR-044: Variant metadata for randomizer tracking
    variant_index: Optional[int] = None
    variant_total: Optional[int] = None
    snapshot: Optional[Dict[str, Any]] = None
    execution_metadata: JobExecutionMetadata = field(default_factory=JobExecutionMetadata)

    def mark_status(self, status: JobStatus, error_message: str | None = None) -> None:
        self.status = status
        self.updated_at = _utcnow()
        if status == JobStatus.RUNNING and self.started_at is None:
            self.started_at = self.updated_at
        if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            self.completed_at = self.updated_at
        if error_message:
            self.error_message = error_message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "priority": int(self.priority),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "learning_enabled": self.learning_enabled,
            "randomizer_metadata": self.randomizer_metadata or {},
            "error_message": self.error_message,
            "result": self.result,
            "worker_id": self.worker_id,
            "run_mode": self.run_mode,
            "source": self.source,
            "prompt_source": self.prompt_source,
            "prompt_pack_id": self.prompt_pack_id,
            "config_snapshot": self.config_snapshot,
            "variant_index": self.variant_index,
            "variant_total": self.variant_total,
            "snapshot": self.snapshot,
            "error_envelope": serialize_envelope(self.error_envelope),
        }

    def summary(self) -> str:
        snapshot = self.snapshot or {}
        prompt = snapshot.get("positive_prompt") or snapshot.get("prompt") or ""
        model = (
            snapshot.get("base_model")
            or snapshot.get("model_name")
            or snapshot.get("model")
            or snapshot.get("prompt_model")
            or ""
        )
        if prompt or model:
            return f"{prompt[:64]} | {model}"
        config_snapshot = self.config_snapshot or {}
        prompt = prompt or config_snapshot.get("prompt", "")
        model = model or config_snapshot.get("model", "")
        if prompt or model:
            return f"{prompt[:64]} | {model}"
        payload = getattr(self, "payload", None)
        if callable(payload):
            return "callable payload"
        if payload:
            return str(payload)[:64]
        return self.job_id


@dataclass
class PromptPackEntryResult:
    pack_id: str
    pack_name: str
    variant_index: int | None
    status: str
    error: str | None
    prompt: str
    negative_prompt: str
    pipeline_mode: str | None
    params: Dict[str, Any]
    outputs: List[Dict[str, Any]]
    raw_result: Any | None


@dataclass
class PromptPackBatchResult:
    job_id: str
    status: str
    mode: str
    total_entries: int
    results: List[PromptPackEntryResult]
