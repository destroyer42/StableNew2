# Subsystem: Queue
# Role: Defines the Job domain model, statuses, and priorities.

"""Job model for single-node and future cluster execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, Enum
from typing import Any, Dict, List, Optional

from src.pipeline.pipeline_runner import PipelineConfig
from src.cluster.worker_model import WorkerId


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


def _utcnow() -> datetime:
    return datetime.utcnow()


@dataclass
class Job:
    job_id: str
    pipeline_config: PipelineConfig | None
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
    result: Optional[Dict[str, Any]] = None
    payload: Any | None = None
    worker_id: WorkerId | None = None

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
            "pipeline_config": self.pipeline_config.__dict__ if self.pipeline_config is not None else None,
            "worker_id": self.worker_id,
        }

    def summary(self) -> str:
        if self.pipeline_config:
            prompt = getattr(self.pipeline_config, "prompt", "") or ""
            model = getattr(self.pipeline_config, "model", "") or getattr(self.pipeline_config, "model_name", "")
            return f"{prompt[:64]} | {model}"
        if self.payload:
            return str(self.payload)[:64]
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
