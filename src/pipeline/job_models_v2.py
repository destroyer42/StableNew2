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
class JobUiSummary:
    """Display-friendly summary of a job for UI panels.

    This is the canonical summary for Preview/Queue panels to consume.
    All fields are simple display strings or counts, no config objects.
    """
    job_id: str
    model: str
    prompt_short: str
    negative_prompt_short: str | None
    sampler: str
    steps: int | None
    cfg_scale: float | None
    seed_display: str
    variant_label: str  # e.g., "" or "[v1/3]"
    batch_label: str    # e.g., "" or "[b2/5]"
    stages_summary: str  # e.g., "txt2img �+' upscale"
    randomizer_summary: str | None
    has_refiner: bool
    has_hires: bool
    has_upscale: bool
    output_dir: str
    total_summary: str  # e.g., "model | seed=12345 [v1/3]"

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

    def to_ui_summary(self) -> JobUiSummary:
        """Convert to a JobUiSummary for UI panel display.

        Extracts display-friendly strings from config and job metadata.
        """
        config = self.config

        def _pick(keys: list[str], default: Any = None) -> Any:
            for key in keys:
                if isinstance(config, dict):
                    value = config.get(key, None)
                else:
                    value = getattr(config, key, None)
                if value is not None:
                    return value
            return default

        model = _pick(["model", "model_name"], "unknown") or "unknown"
        prompt_full = _pick(["prompt"], "") or ""
        negative_prompt_full = _pick(["negative_prompt"], "") or ""
        sampler = _pick(["sampler", "sampler_name"], "") or ""
        steps = self._coerce_int(_pick(["steps"]))
        cfg_scale = self._coerce_float(_pick(["cfg_scale"]))
        stages = _pick(["stages"], []) or []

        prompt_short = self._truncate_text(prompt_full, 40)
        negative_prompt_short = (
            self._truncate_text(negative_prompt_full, 120) if negative_prompt_full else None
        )
        seed_display = str(self.seed) if self.seed is not None else "?"

        variant_label = ""
        if self.variant_total > 1:
            variant_label = f"[v{self.variant_index + 1}/{self.variant_total}]"

        batch_label = ""
        if self.batch_total > 1:
            batch_label = f"[b{self.batch_index + 1}/{self.batch_total}]"

        stage_labels = {
            "txt2img": "txt2img",
            "img2img": "img2img",
            "adetailer": "ADetailer",
            "upscale": "upscale",
        }
        stage_parts = [stage_labels.get(s, s) for s in stages] if stages else ["txt2img"]
        stages_summary = " → ".join(stage_parts)

        total_summary = f"{model} | seed={seed_display}"
        if variant_label:
            total_summary += f" {variant_label}"
        if batch_label:
            total_summary += f" {batch_label}"

        has_refiner = bool(_pick(["refiner_enabled"], False))
        has_hires = bool(_pick(["hires_enabled"], False) or _pick(["hires_fix"]))
        has_upscale = bool(
            _pick(["upscale_enabled"], False)
            or any(str(stage).lower() == "upscale" for stage in stages)
        )

        randomizer_text = self._format_randomizer_summary(self.randomizer_summary)

        return JobUiSummary(
            job_id=self.job_id,
            model=model,
            prompt_short=prompt_short,
            negative_prompt_short=negative_prompt_short,
            sampler=sampler,
            steps=steps,
            cfg_scale=cfg_scale,
            seed_display=seed_display,
            variant_label=variant_label,
            batch_label=batch_label,
            stages_summary=stages_summary,
            randomizer_summary=randomizer_text,
            has_refiner=has_refiner,
            has_hires=has_hires,
            has_upscale=has_upscale,
            output_dir=self.path_output_dir,
            total_summary=total_summary,
        )

    @staticmethod
    def _truncate_text(value: str, limit: int) -> str:
        if not value:
            return ""
        return value if len(value) <= limit else value[:limit] + "..."

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_randomizer_summary(summary: dict[str, Any] | None) -> str | None:
        if not summary:
            return None
        parts: list[str] = []
        max_variants = summary.get("max_variants")
        if isinstance(max_variants, int) and max_variants > 1:
            parts.append(f"{max_variants} variants")
        if isinstance(summary.get("model_choices"), int) and summary["model_choices"] > 1:
            parts.append(f"{summary['model_choices']} models")
        if isinstance(summary.get("sampler_choices"), int) and summary["sampler_choices"] > 1:
            parts.append(f"{summary['sampler_choices']} samplers")
        if isinstance(summary.get("cfg_scale_values"), int) and summary["cfg_scale_values"] > 1:
            parts.append(f"{summary['cfg_scale_values']} CFG")
        if isinstance(summary.get("steps_values"), int) and summary["steps_values"] > 1:
            parts.append(f"{summary['steps_values']} steps")
        seed_mode = summary.get("seed_mode")
        if seed_mode:
            parts.append(f"{seed_mode.replace('_', ' ').lower()} seed")
        return " � ".join(parts) if parts else None

    def to_queue_snapshot(self) -> dict[str, Any]:
        """Convert to a dict snapshot suitable for queue Job.config_snapshot.

        This produces a complete, serializable representation of the job
        for queue/history persistence.
        """
        config = self.config

        # Extract common fields from config (dict or object)
        if isinstance(config, dict):
            prompt = config.get("prompt", "")
            negative_prompt = config.get("negative_prompt", "")
            model = config.get("model", config.get("model_name", ""))
            steps = config.get("steps")
            cfg_scale = config.get("cfg_scale")
            width = config.get("width")
            height = config.get("height")
            sampler = config.get("sampler", config.get("sampler_name", ""))
            vae = config.get("vae", config.get("vae_name", ""))
        else:
            prompt = getattr(config, "prompt", "")
            negative_prompt = getattr(config, "negative_prompt", "")
            model = getattr(config, "model", "") or getattr(config, "model_name", "")
            steps = getattr(config, "steps", None)
            cfg_scale = getattr(config, "cfg_scale", None)
            width = getattr(config, "width", None)
            height = getattr(config, "height", None)
            sampler = getattr(config, "sampler", "") or getattr(config, "sampler_name", "")
            vae = getattr(config, "vae", "") or getattr(config, "vae_name", "")

        snapshot: dict[str, Any] = {
            "job_id": self.job_id,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "model": model,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "width": width,
            "height": height,
            "sampler": sampler,
            "vae": vae,
            "seed": self.seed,
            "output_dir": self.path_output_dir,
            "filename_template": self.filename_template,
            "variant_index": self.variant_index,
            "variant_total": self.variant_total,
            "batch_index": self.batch_index,
            "batch_total": self.batch_total,
            "created_ts": self.created_ts,
        }

        if self.randomizer_summary:
            snapshot["randomizer_summary"] = self.randomizer_summary

        return snapshot


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
    "JobUiSummary",
]
