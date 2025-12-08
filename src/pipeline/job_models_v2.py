"""Job models for V2 queue system."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Literal, Optional, Sequence
import uuid

from src.pipeline.resolution_layer import (
    ResolvedPipelineConfig,
    ResolvedPrompt,
    UnifiedConfigResolver,
    UnifiedPromptResolver,
)


@dataclass(frozen=True)
class JobBundleSummaryDTO:
    num_parts: int
    estimated_images: int
    positive_preview: str
    negative_preview: str | None
    stage_summary: str
    batch_summary: str
    label: str

    @classmethod
    def from_job_bundle(cls, bundle: "JobBundle") -> "JobBundleSummaryDTO":
        num_parts = len(bundle.parts)
        estimated = bundle.total_image_count()
        first_part = bundle.parts[-1] if bundle.parts else None
        positive = cls._extract_positive_preview(first_part)
        negative = cls._extract_negative_preview(first_part)
        batch_summary = (
            f"{first_part.config_snapshot.batch_size}×{first_part.config_snapshot.batch_count}"
            if first_part
            else "1×1"
        )
        stage_summary = cls._stage_summary_from_part(first_part)
        return cls(
            num_parts=num_parts,
            estimated_images=estimated,
            positive_preview=positive,
            negative_preview=negative or None,
            stage_summary=stage_summary,
            batch_summary=batch_summary,
            label=bundle.summary_label(),
        )

    @staticmethod
    def _extract_positive_preview(part: "JobPart" | None) -> str:
        if part and part.resolved_prompt:
            return part.resolved_prompt.positive_preview
        if part:
            return (part.positive_prompt or "")[:120]
        return ""

    @staticmethod
    def _extract_negative_preview(part: "JobPart" | None) -> str:
        if part and part.resolved_prompt:
            return part.resolved_prompt.negative_preview
        if part:
            return part.negative_prompt or ""
        return ""

    @staticmethod
    def _stage_summary_from_part(part: "JobPart" | None) -> str:
        if part and part.resolved_config:
            stages = part.resolved_config.enabled_stage_names()
            if stages:
                return " + ".join(stages)
        return "txt2img"


@dataclass(frozen=True)
class JobQueueItemDTO:
    job_id: str
    label: str
    status: str
    estimated_images: int
    created_at: datetime

    @classmethod
    def from_job(cls, job: "Job") -> "JobQueueItemDTO":
        return cls(
            job_id=job.job_id,
            label=getattr(job, "label", job.job_id) or job.job_id,
            status=job.status.value if hasattr(job.status, "value") else str(job.status),
            estimated_images=getattr(job, "total_images", 1),
            created_at=getattr(job, "created_at", datetime.utcnow()),
        )


@dataclass(frozen=True)
class JobHistoryItemDTO:
    job_id: str
    label: str
    completed_at: datetime
    total_images: int
    stages: str

    @classmethod
    def from_job(cls, job: "Job") -> "JobHistoryItemDTO":
        return cls(
            job_id=job.job_id,
            label=getattr(job, "label", job.job_id) or job.job_id,
            completed_at=getattr(job, "completed_at", datetime.utcnow()) or datetime.utcnow(),
            total_images=getattr(job, "total_images", 1),
            stages="txt2img",
        )


class JobStatusV2(str, Enum):
    """Status of a queue job."""
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Prompt metadata helpers
# ---------------------------------------------------------------------------


@dataclass
class StagePromptInfo:
    """Prompt-level metadata captured for a pipeline stage."""

    original_prompt: str
    final_prompt: str
    original_negative_prompt: str
    final_negative_prompt: str
    global_negative_applied: bool
    global_negative_terms: str | None = None


@dataclass
class PackUsageInfo:
    """Describes how a prompt pack contributed to a job."""

    pack_name: str
    pack_path: str | None = None
    prompt_index: int | None = None
    used_for_stage: str = "txt2img"


# ---------------------------------------------------------------------------
# Job Builder Data Classes (PR-204B)
# ---------------------------------------------------------------------------


@dataclass
class PipelineConfigSnapshot:
    """Canonical snapshot of pipeline-level config used before building jobs."""

    model_name: str
    sampler_name: str
    scheduler_name: str
    steps: int
    cfg_scale: float
    width: int
    height: int
    seed_mode: Literal["fixed", "random", "per_prompt"] = "fixed"
    seed_value: int | None = None
    batch_size: int = 1
    batch_count: int = 1
    enable_img2img: bool = False
    enable_adetailer: bool = False
    enable_hires_fix: bool = False
    enable_upscale: bool = False
    randomizer_config: dict[str, Any] | None = None
    output_dir: str = "output"
    filename_template: str = "{seed}"
    metadata: dict[str, Any] | None = None

    def copy_with_overrides(self, **overrides: Any) -> "PipelineConfigSnapshot":
        data = {**self.__dict__, **overrides}
        return PipelineConfigSnapshot(**data)

    @staticmethod
    def default() -> "PipelineConfigSnapshot":
        return PipelineConfigSnapshot(
            model_name="stable-diffusion-v1-5",
            sampler_name="Euler a",
            scheduler_name="ddim",
            steps=20,
            cfg_scale=7.5,
            width=512,
            height=512,
        )


@dataclass
class JobPart:
    """Represents a single prompt/negative + config to run."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    positive_prompt: str = ""
    negative_prompt: str = ""
    prompt_source: Literal["single", "pack", "preset", "other"] = "single"
    pack_name: str | None = None
    config_snapshot: PipelineConfigSnapshot = field(default_factory=PipelineConfigSnapshot.default)
    resolved_prompt: ResolvedPrompt | None = None
    resolved_config: ResolvedPipelineConfig | None = None
    estimated_image_count: int = 1

    def __post_init__(self) -> None:
        self.estimated_image_count = max(
            1, self.config_snapshot.batch_size * self.config_snapshot.batch_count
        )


@dataclass
class JobBundle:
    """Collection of JobParts that together represent user intent."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    label: str = ""
    parts: list[JobPart] = field(default_factory=list)
    global_negative_text: str = ""
    run_mode: Literal["queue", "direct"] = "queue"
    created_at: datetime = field(default_factory=datetime.utcnow)
    tags: list[str] = field(default_factory=list)

    def total_image_count(self) -> int:
        return sum(part.estimated_image_count for part in self.parts)

    def summary_label(self) -> str:
        if self.label:
            return self.label
        return f"{len(self.parts)} parts, {self.total_image_count()} images"


class JobBundleBuilder:
    """Builds canonical JobBundles from prompts/packs."""

    def __init__(
        self,
        base_config: PipelineConfigSnapshot,
        *,
        global_negative_text: str = "",
        apply_global_negative: bool = True,
        prompt_resolver: UnifiedPromptResolver | None = None,
        config_resolver: UnifiedConfigResolver | None = None,
        stage_flags: dict[str, bool] | None = None,
        batch_runs: int = 1,
        randomizer_summary: dict[str, Any] | None = None,
    ) -> None:
        self._base_config = base_config
        self._global_negative_text = global_negative_text.strip()
        self._apply_global_negative = apply_global_negative
        self._parts: list[JobPart] = []
        self._prompt_resolver = prompt_resolver or UnifiedPromptResolver()
        self._config_resolver = config_resolver or UnifiedConfigResolver()
        self._stage_flags = stage_flags or {}
        self._batch_runs = max(1, batch_runs)
        self._randomizer_summary = randomizer_summary

    def reset(self) -> None:
        self._parts.clear()

    def add_single_prompt(
        self,
        positive_prompt: str,
        *,
        negative_prompt: str = "",
        override_config: PipelineConfigSnapshot | None = None,
        prompt_source: Literal["single", "pack", "preset", "other"] = "single",
    ) -> JobPart:
        config = override_config or self._base_config
        resolved_prompt = self._resolve_prompt(
            base_prompt=positive_prompt,
            negative_prompt=negative_prompt,
        )
        resolved_config = self._resolve_config(config)
        part = JobPart(
            positive_prompt=resolved_prompt.positive,
            negative_prompt=resolved_prompt.negative,
            prompt_source=prompt_source,
            config_snapshot=config,
            resolved_prompt=resolved_prompt,
            resolved_config=resolved_config,
        )
        self._parts.append(part)
        return part

    def add_pack_prompts(
        self,
        pack_name: str,
        prompts: Sequence[str],
        *,
        prepend_text: str = "",
        pack_config: PipelineConfigSnapshot,
    ) -> list[JobPart]:
        result: list[JobPart] = []
        for prompt in prompts:
            resolved_prompt = self._resolve_prompt(
                base_prompt=prompt,
                prepend_text=prepend_text,
                pack_prompt=prompt,
                pack_negative=(
                    pack_config.metadata.get("negative_prompt") if pack_config.metadata else ""
                ),
            )
            resolved_config = self._resolve_config(pack_config)
            part = JobPart(
                positive_prompt=resolved_prompt.positive,
                negative_prompt=resolved_prompt.negative,
                prompt_source="pack",
                pack_name=pack_name,
                config_snapshot=pack_config,
                resolved_prompt=resolved_prompt,
                resolved_config=resolved_config,
            )
            self._parts.append(part)
            result.append(part)
        return result

    def to_job_bundle(
        self,
        *,
        label: str | None = None,
        run_mode: Literal["queue", "direct"] = "queue",
        tags: Sequence[str] | None = None,
    ) -> JobBundle:
        if not self._parts:
            raise ValueError("JobBundleBuilder requires at least one JobPart")
        bundle = JobBundle(
            label=label or "",
            parts=list(self._parts),
            global_negative_text=self._global_negative_text,
            run_mode=run_mode,
            tags=list(tags or []),
        )
        if not bundle.label:
            bundle.label = bundle.summary_label()
        return bundle

    def _resolve_prompt(
        self,
        *,
        base_prompt: str,
        negative_prompt: str = "",
        pack_prompt: str | None = None,
        prepend_text: str | None = None,
        pack_negative: str | None = None,
    ) -> ResolvedPrompt:
        return self._prompt_resolver.resolve(
            gui_prompt=base_prompt,
            pack_prompt=pack_prompt,
            prepend_text=prepend_text,
            global_negative=self._global_negative_text,
            apply_global_negative=self._apply_global_negative,
            negative_override=negative_prompt,
            pack_negative=pack_negative,
        )

    def _resolve_config(
        self,
        config: PipelineConfigSnapshot,
    ) -> ResolvedPipelineConfig:
        return self._config_resolver.resolve(
            config_snapshot=config,
            stage_flags=self._stage_flags,
            batch_count=self._batch_runs,
            randomizer_summary=self._randomizer_summary,
        )


@dataclass
class JobUiSummary:
    """
    Backward-compatible UI summary wrapper for preview/queue/history panels.

    This is intentionally lightweight and derived from NormalizedJobRecord so
    GUI code can display jobs without knowing pipeline internals.
    """

    job_id: str
    label: str                   # short display label (e.g. pack name or first prompt words)
    positive_preview: str        # truncated positive prompt
    negative_preview: str        # truncated negative prompt
    stages_display: str          # e.g. "txt2img → adetailer (optional) → img2img (optional) → upscale (optional)"
    estimated_images: int        # how many images this job will produce
    created_at: Optional[datetime] = None

    @classmethod
    def from_normalized(cls, rec: "NormalizedJobRecord") -> "JobUiSummary":
        """
        Adapter to create JobUiSummary from NormalizedJobRecord.
        """
        config = rec.config

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
        prompt_full = (
            (rec.txt2img_prompt_info and rec.txt2img_prompt_info.final_prompt)
            or _pick(["prompt"], "")
            or ""
        )
        negative_prompt_full = (
            (rec.txt2img_prompt_info and rec.txt2img_prompt_info.final_negative_prompt)
            or _pick(["negative_prompt"], "")
            or ""
        )
        stages = _pick(["stages"], []) or []

        positive_preview = cls._truncate_text(prompt_full, 120)
        negative_preview = (
            cls._truncate_text(negative_prompt_full, 120) if negative_prompt_full else None
        )
        seed_display = str(rec.seed) if rec.seed is not None else "?"

        variant_label = ""
        if rec.variant_total > 1:
            variant_label = f"[v{rec.variant_index + 1}/{rec.variant_total}]"

        batch_label = ""
        if rec.batch_total > 1:
            batch_label = f"[b{rec.batch_index + 1}/{rec.batch_total}]"

        stage_labels = {
            "txt2img": "txt2img",
            "img2img": "img2img",
            "adetailer": "ADetailer",
            "upscale": "upscale",
        }
        stage_parts = [stage_labels.get(s, s) for s in stages] if stages else ["txt2img"]
        stages_display = " → ".join(stage_parts)

        label = f"{model} | seed={seed_display}"
        if variant_label:
            label += f" {variant_label}"
        if batch_label:
            label += f" {batch_label}"

        estimated_images = rec.variant_total * rec.batch_total if rec.variant_total and rec.batch_total else 1

        return cls(
            job_id=rec.job_id,
            label=label,
            positive_preview=positive_preview,
            negative_preview=negative_preview,
            stages_display=stages_display,
            estimated_images=estimated_images,
            created_at=rec.created_ts,
        )

@dataclass
class JobLifecycleLogEvent:
    timestamp: datetime
    source: str
    event_type: str
    job_id: str | None
    bundle_id: str | None
    draft_size: int | None
    message: str



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
    txt2img_prompt_info: StagePromptInfo | None = None
    img2img_prompt_info: StagePromptInfo | None = None
    pack_usage: list[PackUsageInfo] = field(default_factory=list)

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
        prompt_full = (
            (self.txt2img_prompt_info and self.txt2img_prompt_info.final_prompt)
            or _pick(["prompt"], "")
            or ""
        )
        negative_prompt_full = (
            (self.txt2img_prompt_info and self.txt2img_prompt_info.final_negative_prompt)
            or _pick(["negative_prompt"], "")
            or ""
        )
        stages = _pick(["stages"], []) or []

        positive_preview = self._truncate_text(prompt_full, 120)
        negative_preview = (
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
        stages_display = " → ".join(stage_parts)

        label = f"{model} | seed={seed_display}"
        if variant_label:
            label += f" {variant_label}"
        if batch_label:
            label += f" {batch_label}"

        estimated_images = self.variant_total * self.batch_total if self.variant_total and self.batch_total else 1

        return JobUiSummary(
            job_id=self.job_id,
            label=label,
            positive_preview=positive_preview,
            negative_preview=negative_preview,
            stages_display=stages_display,
            estimated_images=estimated_images,
            created_at=self.created_ts,
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

        if self.txt2img_prompt_info:
            snapshot["txt2img_prompt_info"] = asdict(self.txt2img_prompt_info)
        if self.img2img_prompt_info:
            snapshot["img2img_prompt_info"] = asdict(self.img2img_prompt_info)
        if self.pack_usage:
            snapshot["pack_usage"] = [asdict(info) for info in self.pack_usage]

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
    "StagePromptInfo",
    "PackUsageInfo",
    "JobLifecycleLogEvent",
]
