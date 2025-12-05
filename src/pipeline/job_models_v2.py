"""Job models for V2 queue system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import uuid


class JobStatusV2(str, Enum):
    """Status of a queue job."""
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Job Builder Data Classes (PR-204B)
# ---------------------------------------------------------------------------


@dataclass
class BatchSettings:
    """Settings for batch expansion in job building.

    Attributes:
        batch_size: Images per job for WebUI (passed through to executor).
        batch_runs: Number of times to repeat each variant config as separate jobs.
    """
    batch_size: int = 1
    batch_runs: int = 1


@dataclass
class OutputSettings:
    """Settings for job output directory and filename.

    Attributes:
        base_output_dir: Base directory for job outputs.
        filename_template: Template string for output filenames (e.g., "{seed}_{steps}").
    """
    base_output_dir: str = "output"
    filename_template: str = "{seed}"


@dataclass
class NormalizedJobRecord:
    """A fully normalized job record ready for queue/preview/executor.

    This is the canonical job representation produced by JobBuilderV2.
    All fields are explicit - no hidden defaults or missing values.

    Attributes:
        job_id: Unique identifier for this job.
        config: Fully merged pipeline config (PipelineConfig or dict).
        path_output_dir: Resolved output directory for this job.
        filename_template: Filename template for outputs.
        seed: Seed value (may be adjusted by seed mode).
        variant_index: Index within randomizer variants (0-based).
        variant_total: Total number of variants.
        batch_index: Index within batch runs (0-based).
        batch_total: Total number of batch runs.
        created_ts: Timestamp when job was created.
        randomizer_summary: Optional summary of randomization applied.
    """
    job_id: str
    config: Any  # PipelineConfig or dict - fully merged
    path_output_dir: str
    filename_template: str
    seed: int | None = None
    variant_index: int = 0
    variant_total: int = 1
    batch_index: int = 0
    batch_total: int = 1
    created_ts: float = 0.0
    randomizer_summary: dict[str, Any] | None = None

    def get_display_summary(self) -> str:
        """Get a short display string for the job."""
        config = self.config
        if isinstance(config, dict):
            model = config.get("model", "unknown")
            prompt = config.get("prompt", "")[:30]
            if len(config.get("prompt", "")) > 30:
                prompt += "..."
        else:
            model = getattr(config, "model", "unknown")
            prompt_val = getattr(config, "prompt", "")
            prompt = prompt_val[:30] if prompt_val else ""
            if len(prompt_val) > 30:
                prompt += "..."

        seed_str = str(self.seed) if self.seed is not None else "?"
        variant_info = ""
        if self.variant_total > 1:
            variant_info = f" [v{self.variant_index + 1}/{self.variant_total}]"
        batch_info = ""
        if self.batch_total > 1:
            batch_info = f" [b{self.batch_index + 1}/{self.batch_total}]"

        return f"{model} | seed={seed_str}{variant_info}{batch_info}"


# ---------------------------------------------------------------------------
# Queue Job V2 (existing)
# ---------------------------------------------------------------------------


@dataclass
class QueueJobV2:
    """A job entry in the V2 queue system."""

    job_id: str
    config_snapshot: dict[str, Any]
    status: JobStatusV2 = JobStatusV2.QUEUED
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: float = 0.0
    eta_seconds: Optional[float] = None
    error_message: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        config_snapshot: dict[str, Any],
        metadata: Optional[dict[str, Any]] = None,
    ) -> "QueueJobV2":
        """Create a new job with a unique ID."""
        return cls(
            job_id=str(uuid.uuid4()),
            config_snapshot=config_snapshot,
            metadata=metadata or {},
        )

    def get_display_summary(self) -> str:
        """Get a short display string for the job."""
        config = self.config_snapshot
        stage = config.get("stage", "txt2img")
        model = config.get("model", config.get("model_name", "unknown"))
        seed = config.get("seed", "?")
        prompt = config.get("prompt", "")[:30]
        if len(config.get("prompt", "")) > 30:
            prompt += "..."
        return f"{stage} | {model} | seed={seed}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize job to dictionary for persistence."""
        return {
            "job_id": self.job_id,
            "config_snapshot": self.config_snapshot,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "eta_seconds": self.eta_seconds,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QueueJobV2":
        """Deserialize job from dictionary."""
        status_str = data.get("status", "queued")
        try:
            status = JobStatusV2(status_str)
        except ValueError:
            status = JobStatusV2.QUEUED

        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        else:
            created_at = datetime.now()

        started_at = data.get("started_at")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)

        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)

        return cls(
            job_id=data.get("job_id", str(uuid.uuid4())),
            config_snapshot=data.get("config_snapshot", {}),
            status=status,
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            progress=float(data.get("progress", 0.0)),
            eta_seconds=data.get("eta_seconds"),
            error_message=data.get("error_message"),
            metadata=data.get("metadata", {}),
        )


__all__ = [
    "JobStatusV2",
    "QueueJobV2",
    "BatchSettings",
    "OutputSettings",
    "NormalizedJobRecord",
]
