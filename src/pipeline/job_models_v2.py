"""Job models for V2 queue system."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

from src.pipeline.resolution_layer import (
    ResolvedPipelineConfig,
    ResolvedPrompt,
)

if TYPE_CHECKING:
    from src.queue.job_model import Job

_STAGE_DISPLAY_MAP: dict[str, str] = {
    "txt2img": "txt2img",
    "img2img": "img2img",
    "upscale": "upscale",
    "adetailer": "ADetailer",
}


def _coerce_iso_timestamp(value: float | str | datetime | None) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value).isoformat()
        except Exception:
            pass
    if isinstance(value, str) and value:
        return value
    return datetime.utcnow().isoformat()


def _coerce_iso_datetime(value: datetime | str | None) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def _truncate_display_text(value: str | None, limit: int) -> str:
    if not value:
        return ""
    return value if len(value) <= limit else f"{value[:limit]}..."


def _format_stage_display(stage_names: Sequence[str]) -> str:
    if not stage_names:
        return _STAGE_DISPLAY_MAP["txt2img"]
    formatted = [_STAGE_DISPLAY_MAP.get(name, name) for name in stage_names if name]
    return " + ".join(formatted) if formatted else _STAGE_DISPLAY_MAP["txt2img"]


def _format_variant_label(index: int, total: int) -> str | None:
    if total > 1:
        return f"[v{index + 1}/{total}]"
    return None


def _format_batch_label(index: int, total: int) -> str | None:
    if total > 1:
        return f"[b{index + 1}/{total}]"
    return None


@dataclass(frozen=True)
class JobQueueItemDTO:
    """Queue display DTO derived from NormalizedJobRecord snapshot.

    For jobs built via JobBuilderV2, this DTO should be constructed from
    the NJR snapshot stored in Job.snapshot, not from Job.pipeline_config.

    PR-CORE1-12: pipeline_config is DEPRECATED. Legacy jobs without NJR
    snapshots may fall back to pipeline_config, but all new jobs use NJR only.
    """

    job_id: str
    label: str
    status: str
    estimated_images: int
    created_at: datetime

    @classmethod
    def from_job(cls, job: Job) -> JobQueueItemDTO:
        return cls(
            job_id=job.job_id,
            label=getattr(job, "label", job.job_id) or job.job_id,
            status=job.status.value if hasattr(job.status, "value") else str(job.status),
            estimated_images=getattr(job, "total_images", 1),
            created_at=getattr(job, "created_at", datetime.utcnow()),
        )


@dataclass(frozen=True)
class JobHistoryItemDTO:
    """History display DTO derived from NormalizedJobRecord snapshot.

    For jobs built via JobBuilderV2, this DTO should be constructed from
    the NJR snapshot stored in history entries, not from pipeline_config.

    PR-CORE1-12: pipeline_config is DEPRECATED. Legacy history entries without
    NJR snapshots may fall back to pipeline_config, but all new jobs use NJR only.
    """

    job_id: str
    label: str
    completed_at: datetime
    total_images: int
    stages: str

    @classmethod
    def from_job(cls, job: Job) -> JobHistoryItemDTO:
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


StageType = Literal["txt2img", "img2img", "adetailer", "upscale"]


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


@dataclass(frozen=True)
class LoRATag:
    name: str
    weight: float


@dataclass
class StageConfig:
    stage_type: StageType
    enabled: bool = False
    steps: int | None = None
    cfg_scale: float | None = None
    denoising_strength: float | None = None
    sampler_name: str | None = None
    scheduler: str | None = None
    model: str | None = None
    vae: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


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

    def copy_with_overrides(self, **overrides: Any) -> PipelineConfigSnapshot:
        data = {**self.__dict__, **overrides}
        return PipelineConfigSnapshot(**data)

    @staticmethod
    def default() -> PipelineConfigSnapshot:
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
    prompt_source: Literal["pack"] = "pack"
    pack_name: str | None = None
    config_snapshot: PipelineConfigSnapshot = field(default_factory=PipelineConfigSnapshot.default)
    resolved_prompt: ResolvedPrompt | None = None
    resolved_config: ResolvedPipelineConfig | None = None
    estimated_image_count: int = 1

    def __post_init__(self) -> None:
        self.estimated_image_count = max(
            1, self.config_snapshot.batch_size * self.config_snapshot.batch_count
        )


@dataclass(frozen=True)
class UnifiedJobSummary:
    """Canonical job summary shared between preview, queue, history, learning, and Debug Hub."""

    job_id: str
    prompt_pack_id: str
    prompt_pack_name: str
    prompt_pack_row_index: int
    positive_prompt_preview: str
    negative_prompt_preview: str | None
    lora_preview: str
    embedding_preview: str
    base_model: str
    sampler_name: str
    cfg_scale: float
    steps: int
    width: int
    height: int
    stage_chain_labels: list[str]
    randomization_enabled: bool
    matrix_mode: str | None
    matrix_slot_values_preview: str
    variant_index: int
    batch_index: int
    config_variant_label: str
    config_variant_index: int
    estimated_image_count: int
    status: str
    created_at: datetime
    completed_at: datetime | None

    @staticmethod
    def _truncate(value: str) -> str:
        if not value:
            return ""
        return value if len(value) <= 120 else value[:120] + "..."

    @classmethod
    def from_normalized_record(cls, record: NormalizedJobRecord) -> UnifiedJobSummary:
        return cls(
            job_id=record.job_id,
            prompt_pack_id=record.prompt_pack_id,
            prompt_pack_name=record.prompt_pack_name,
            prompt_pack_row_index=record.prompt_pack_row_index,
            positive_prompt_preview=cls._truncate(record.positive_prompt),
            negative_prompt_preview=cls._truncate(record.negative_prompt)
            if record.negative_prompt
            else None,
            lora_preview=record.lora_preview,
            embedding_preview=" + ".join(record.positive_embeddings),
            base_model=record.base_model or "unknown",
            sampler_name=record.sampler_name,
            cfg_scale=record.cfg_scale,
            steps=record.steps,
            width=record.width,
            height=record.height,
            stage_chain_labels=record.stage_chain_labels,
            randomization_enabled=record.randomization_enabled,
            matrix_mode=record.matrix_mode,
            matrix_slot_values_preview=record.matrix_slot_values_preview(),
            variant_index=record.variant_index,
            batch_index=record.batch_index,
            config_variant_label=record.config_variant_label,
            config_variant_index=record.config_variant_index,
            estimated_image_count=record.estimated_image_count(),
            status=record.status.value.upper(),
            created_at=record.created_at,
            completed_at=record.completed_at,
        )

    @classmethod
    def from_job(cls, job: Job, status: JobStatusV2) -> UnifiedJobSummary:
        now = getattr(job, "created_at", datetime.utcnow())
        prompt_pack_id = getattr(job, "prompt_pack_id", "") or ""
        prompt_pack_name = getattr(job, "prompt_pack_name", "") or ""
        return cls(
            job_id=job.job_id,
            prompt_pack_id=prompt_pack_id,
            prompt_pack_name=prompt_pack_name,
            prompt_pack_row_index=getattr(job, "prompt_pack_row_index", 0) or 0,
            positive_prompt_preview="",
            negative_prompt_preview=None,
            lora_preview="",
            embedding_preview="",
            base_model="unknown",
            sampler_name="",
            cfg_scale=0.0,
            steps=0,
            width=0,
            height=0,
            stage_chain_labels=["txt2img"],
            randomization_enabled=False,
            matrix_mode=None,
            matrix_slot_values_preview="",
            variant_index=0,
            batch_index=0,
            config_variant_label="base",
            config_variant_index=0,
            estimated_image_count=1,
            status=status.value.upper(),
            created_at=now,
            completed_at=getattr(job, "completed_at", None),
        )


@dataclass
class JobUiSummary:
    """Unified UI summary derived from NormalizedJobRecord for display panels.

    This DTO is intentionally limited to presentation values derived from
    NormalizedJobRecord snapshots. It no longer inspects pipeline config or
    reconstructs prompts itself; instead it mirrors the data already produced
    by `JobView`.
    """

    job_id: str
    label: str
    positive_preview: str
    negative_preview: str | None
    stages_display: str
    estimated_images: int
    created_at: datetime | None = None

    @classmethod
    def from_normalized(cls, rec: NormalizedJobRecord) -> JobUiSummary:
        return cls.from_job_view(rec.to_job_view())

    @classmethod
    def from_job_view(cls, view: JobView) -> JobUiSummary:
        created_at = None
        if view.created_at:
            try:
                created_at = datetime.fromisoformat(view.created_at)
            except ValueError:
                created_at = None
        return cls(
            job_id=view.job_id,
            label=view.label,
            positive_preview=view.positive_preview,
            negative_preview=view.negative_preview,
            stages_display=view.stages_display,
            estimated_images=view.estimated_images,
            created_at=created_at,
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
    """Canonical job record for preview, queue display, and history (CORE1 hybrid state).

    This is the single source of truth for:
    - Job construction via JobBuilderV2
    - Preview/queue/history display via UnifiedJobSummary
    - Job snapshots and provenance tracking

    NormalizedJobRecord is the "read model" - used for building and displaying jobs.

    PR-CORE1-12: pipeline_config is DEPRECATED and removed from runtime execution.
    During early CORE1-A/B hybrid state, Job.pipeline_config was the execution payload,
    but PR-CORE1-B3 guarantees new v2.6 jobs never populate this field.
    Full NJR-only execution is enforced for all new jobs; pipeline_config is
    legacy-only (always None for v2.6 jobs) and will be fully removed in future cleanup.
    PR-CORE1-B5 removed the old Job.payload-driven execution path in favor of NJRs.

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
    For jobs where `prompt_source == "pack"`, `prompt_pack_id` must be non-empty and
    `prompt_pack_name` should be populated when available so downstream services can
    attribute the job to the correct PromptPack.
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
    prompt_pack_id: str = ""
    prompt_pack_name: str = ""
    prompt_pack_row_index: int = 0
    prompt_pack_version: str | None = None
    positive_prompt: str = ""
    negative_prompt: str = ""
    positive_embeddings: list[str] = field(default_factory=list)
    negative_embeddings: list[str] = field(default_factory=list)
    lora_tags: list[LoRATag] = field(default_factory=list)
    matrix_slot_values: dict[str, str] = field(default_factory=dict)
    steps: int = 0
    cfg_scale: float = 0.0
    width: int = 0
    height: int = 0
    sampler_name: str = ""
    scheduler: str = ""
    clip_skip: int = 0
    base_model: str = ""
    vae: str | None = None
    stage_chain: list[StageConfig] = field(default_factory=list)
    loop_type: Literal["pipeline", "prompt", "image"] = "pipeline"
    loop_count: int = 1
    images_per_prompt: int = 1
    variant_mode: str = "standard"
    run_mode: Literal["DIRECT", "QUEUE"] = "QUEUE"
    queue_source: Literal["RUN_NOW", "ADD_TO_QUEUE"] = "ADD_TO_QUEUE"
    randomization_enabled: bool = False
    matrix_name: str | None = None
    matrix_mode: str | None = None
    matrix_prompt_mode: str | None = None
    config_variant_label: str = "base"
    config_variant_index: int = 0
    config_variant_overrides: dict[str, Any] = field(default_factory=dict)
    aesthetic_enabled: bool = False
    aesthetic_weight: float | None = None
    aesthetic_text: str | None = None
    aesthetic_embedding: str | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)
    output_paths: list[str] = field(default_factory=list)
    thumbnail_path: str | None = None
    completed_at: datetime | None = None
    status: JobStatusV2 = JobStatusV2.QUEUED
    error_message: str | None = None

    @property
    def created_at(self) -> datetime:
        return datetime.fromtimestamp(self.created_ts) if self.created_ts else datetime.utcnow()

    @property
    def num_parts(self) -> int:
        return len(self.pack_usage) if self.pack_usage else 1

    @property
    def num_expected_images(self) -> int:
        total = self.variant_total * self.batch_total
        return total if total > 0 else 1

    def _config_value(self, *keys: str) -> Any:
        for key in keys:
            value = None
            if isinstance(self.config, dict):
                value = self.config.get(key)
            else:
                value = getattr(self.config, key, None)
            if value not in (None, "", []):
                return value
        return None

    def _extract_prompt_field(self, attr_name: str, *fallback_keys: str) -> str:
        if self.txt2img_prompt_info:
            info_value = getattr(self.txt2img_prompt_info, attr_name, None)
            if info_value:
                return info_value
        fallback = self._config_value(*fallback_keys)
        return str(fallback) if fallback is not None else ""

    def _extract_stage_names(self) -> list[str]:
        stages = self._config_value("stages")
        if isinstance(stages, list):
            return [str(stage) for stage in stages if stage]
        flags = []
        for stage in ("txt2img", "img2img", "upscale", "adetailer"):
            enabled = self._config_value(f"stage_{stage}_enabled", stage)
            if enabled or (isinstance(enabled, bool) and enabled):
                flags.append(stage)
        return flags or ["txt2img"]

    def _extract_model_name(self) -> str:
        value = self._config_value("model", "model_name")
        return str(value or "unknown")

    @property
    def stage_chain_labels(self) -> list[str]:
        if self.stage_chain:
            return [stage.stage_type for stage in self.stage_chain]
        return ["txt2img"]

    def matrix_slot_values_preview(self) -> str:
        if not self.matrix_slot_values:
            return ""
        return "; ".join(f"{key}={value}" for key, value in self.matrix_slot_values.items())

    @property
    def lora_preview(self) -> str:
        return ", ".join(f"{tag.name}({tag.weight})" for tag in self.lora_tags)

    def estimated_image_count(self) -> int:
        return max(1, self.images_per_prompt * self.loop_count)

    def get_display_summary(self) -> str:
        """Get a short display string for the job.
        
        Shows: Pack Name | batch_size×n_iter (X images) | seed | variant/batch info
        """
        config = self.config
        
        # Get pack name or model
        pack_name = self.prompt_pack_name or ""
        if isinstance(config, dict):
            model = config.get("model", "unknown")
            batch_size = config.get("batch_size", 1)
            n_iter = config.get("n_iter", 1)
        else:
            model = getattr(config, "model", "unknown")
            batch_size = getattr(config, "batch_size", 1)
            n_iter = getattr(config, "n_iter", 1)
        
        primary_label = pack_name if pack_name else model
        
        # Build batch display
        total_images = batch_size * n_iter
        if batch_size > 1 or n_iter > 1:
            batch_info = f" | {batch_size}×{n_iter} ({total_images} images)"
        else:
            batch_info = " | (1 image)"

        seed_str = str(self.seed) if self.seed is not None else "?"

        # PR-CORE-E: Add config variant label
        config_variant_info = ""
        if self.config_variant_label and self.config_variant_label != "base":
            config_variant_info = f" [{self.config_variant_label}]"

        variant_info = ""
        if self.variant_total > 1:
            variant_info = f" [v{self.variant_index + 1}/{self.variant_total}]"
        batch_info_suffix = ""
        if self.batch_total > 1:
            batch_info_suffix = f" [b{self.batch_index + 1}/{self.batch_total}]"

        return f"{primary_label}{batch_info} | seed={seed_str}{config_variant_info}{variant_info}{batch_info_suffix}"

    def to_unified_summary(self) -> UnifiedJobSummary:
        """Create a canonical summary for UI/queue/history consumers."""
        return UnifiedJobSummary.from_normalized_record(self)

    def to_ui_summary(self) -> JobUiSummary:
        """Build a JobUiSummary derived from this normalized record."""
        return JobUiSummary.from_job_view(self.to_job_view())

    def to_job_view(
        self,
        *,
        status: str | None = None,
        created_at: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        is_active: bool = False,
        last_error: str | None = None,
        worker_id: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> JobView:
        """Return a presentation-focused JobView derived from this NJR."""
        normalized_status = status or str(
            self.status.value if hasattr(self.status, "value") else self.status
        )
        return JobView.from_njr(
            self,
            status=normalized_status,
            created_at=created_at or _coerce_iso_timestamp(self.created_ts),
            started_at=started_at,
            completed_at=completed_at or _coerce_iso_datetime(self.completed_at),
            is_active=is_active,
            last_error=last_error or self.error_message,
            worker_id=worker_id,
            result=result,
        )

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @property
    def is_pack_job(self) -> bool:
        """Return True if this normalized job originated from a prompt pack."""
        return (getattr(self, "prompt_source", "") or "").lower() == "pack"

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

        snapshot["prompt_pack_id"] = self.prompt_pack_id
        snapshot["prompt_pack_name"] = self.prompt_pack_name
        snapshot["prompt_pack_row_index"] = self.prompt_pack_row_index
        snapshot["stage_chain"] = [stage.stage_type for stage in self.stage_chain]
        snapshot["images_per_prompt"] = self.images_per_prompt
        snapshot["loop_type"] = self.loop_type
        snapshot["loop_count"] = self.loop_count
        snapshot["variant_mode"] = self.variant_mode
        snapshot["randomization_enabled"] = self.randomization_enabled
        snapshot["matrix_slot_values"] = dict(self.matrix_slot_values)
        snapshot["lora_tags"] = [asdict(tag) for tag in self.lora_tags]
        snapshot["queue_source"] = self.queue_source
        snapshot["run_mode"] = self.run_mode
        snapshot["status"] = (
            self.status.value if hasattr(self.status, "value") else str(self.status)
        )

        if self.txt2img_prompt_info:
            snapshot["txt2img_prompt_info"] = asdict(self.txt2img_prompt_info)
        if self.img2img_prompt_info:
            snapshot["img2img_prompt_info"] = asdict(self.img2img_prompt_info)
        if self.pack_usage:
            snapshot["pack_usage"] = [asdict(info) for info in self.pack_usage]

        return snapshot


@dataclass(frozen=True)
class JobView:
    """Thin, NJR-derived presentation view used by controllers, history, and diagnostics."""

    job_id: str
    status: str
    model: str
    prompt: str
    negative_prompt: str | None
    seed: int | None
    label: str
    positive_preview: str
    negative_preview: str | None
    stages_display: str
    estimated_images: int
    created_at: str
    prompt_pack_id: str
    prompt_pack_name: str
    variant_label: str | None
    batch_label: str | None
    started_at: str | None = None
    completed_at: str | None = None
    is_active: bool = False
    last_error: str | None = None
    worker_id: str | None = None
    result: dict[str, Any] | None = None

    @classmethod
    def from_njr(
        cls,
        record: NormalizedJobRecord,
        *,
        status: str | None = None,
        created_at: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        is_active: bool = False,
        last_error: str | None = None,
        worker_id: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> JobView:
        model = record.base_model or record._extract_model_name() or "unknown"
        prompt_text = (
            record.positive_prompt
            or (record.txt2img_prompt_info and record.txt2img_prompt_info.final_prompt)
            or ""
        )
        negative_text = (
            record.negative_prompt
            or (record.txt2img_prompt_info and record.txt2img_prompt_info.final_negative_prompt)
            or None
        )
        positive_preview = _truncate_display_text(prompt_text, 120)
        negative_preview = _truncate_display_text(negative_text, 120) if negative_text else None
        stage_names = [stage.stage_type for stage in record.stage_chain if stage.stage_type]
        stages_display = _format_stage_display(stage_names)
        variant_label = _format_variant_label(record.variant_index, record.variant_total)
        batch_label = _format_batch_label(record.batch_index, record.batch_total)
        seed_display = str(record.seed) if record.seed is not None else "?"

        label = f"{model} | seed={seed_display}"
        if variant_label:
            label += f" {variant_label}"
        if batch_label:
            label += f" {batch_label}"

        status_value = status or str(
            record.status.value if hasattr(record.status, "value") else record.status
        )
        created_iso = created_at or _coerce_iso_timestamp(record.created_ts)
        return cls(
            job_id=record.job_id,
            status=status_value,
            model=model,
            prompt=prompt_text,
            negative_prompt=negative_text,
            seed=record.seed,
            label=label,
            positive_preview=positive_preview,
            negative_preview=negative_preview,
            stages_display=stages_display,
            estimated_images=record.estimated_image_count(),
            created_at=created_iso,
            prompt_pack_id=record.prompt_pack_id,
            prompt_pack_name=record.prompt_pack_name,
            variant_label=variant_label,
            batch_label=batch_label,
            started_at=started_at,
            completed_at=completed_at,
            is_active=is_active,
            last_error=last_error,
            worker_id=worker_id,
            result=result,
        )


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
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: float = 0.0
    eta_seconds: float | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        config_snapshot: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> QueueJobV2:
        """Create a new job with a unique ID."""
        return cls(
            job_id=str(uuid.uuid4()),
            config_snapshot=config_snapshot,
            metadata=metadata or {},
        )

    def get_display_summary(self) -> str:
        """Get a short display string for the job.

        PR-CORE-E: Includes config variant label in display.
        Shows: Pack Name | Model | batch_size×n_iter (X images) | seed
        """
        config = self.config_snapshot
        
        # Get pack name (fallback to model if not available)
        pack_name = config.get("prompt_pack_name", "")
        model = config.get("model", config.get("model_name", "unknown"))
        
        # Use pack name if available, otherwise use model name
        primary_label = pack_name if pack_name else model
        
        # Get batch info
        batch_size = config.get("batch_size", 1)
        n_iter = config.get("n_iter", 1)
        total_images = batch_size * n_iter
        
        # Build batch display
        if batch_size > 1 or n_iter > 1:
            batch_info = f" | {batch_size}×{n_iter} ({total_images} images)"
        else:
            batch_info = " | (1 image)"
        
        seed = config.get("seed", "?")

        # PR-CORE-E: Add config variant label if present
        config_variant_label = config.get("config_variant_label", None)
        variant_suffix = ""
        if config_variant_label and config_variant_label != "base":
            variant_suffix = f" [{config_variant_label}]"

        return f"{primary_label}{batch_info} | seed={seed}{variant_suffix}"

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
    def from_dict(cls, data: dict[str, Any]) -> QueueJobV2:
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
    "UnifiedJobSummary",
    "StagePromptInfo",
    "StageConfig",
    "LoRATag",
    "PackUsageInfo",
    "JobLifecycleLogEvent",
    "JobView",
]
