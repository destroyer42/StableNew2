"""Job models for V2 queue system."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

from src.pipeline.njr_core_v26 import (
    CURRENT_NJR_SCHEMA_VERSION,
    ImageWorkloadSpec,
    LearningJobContext,
    LoRATag,
    NJRProvenance,
    NormalizedJobRecord,
    OutputPlan,
    PackUsageInfo,
    SourceDescriptor,
    SourceKind,
    StageConfig,
    StagePromptInfo,
    TrainingWorkloadSpec,
    VideoWorkloadSpec,
    WorkloadKind,
    migrate_legacy_njr,
    read_njr,
)
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
    "animatediff": "AnimateDiff",
    "svd_native": "SVD Img2Vid",
    "video_workflow": "Video Workflow",
    "train_lora": "Train LoRA",
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


StageType = Literal[
    "txt2img",
    "img2img",
    "adetailer",
    "upscale",
    "animatediff",
    "svd_native",
    "video_workflow",
    "train_lora",
]


# ---------------------------------------------------------------------------
# Prompt metadata helpers
# ---------------------------------------------------------------------------


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
    def from_normalized_record(
        cls,
        record: NormalizedJobRecord,
        *,
        status: JobStatusV2 = JobStatusV2.QUEUED,
        created_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> UnifiedJobSummary:
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
            status=status.value.upper(),
            created_at=created_at or datetime.utcnow(),
            completed_at=completed_at,
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

    def get_display_summary(self) -> str:
        """Get a short display string for the job.

        Shows: Pack Name [row=X, v=Y/Z, b=A/B] | estimated images | resolution | steps
        """
        # Primary label is pack name or model
        primary_label = self.prompt_pack_name if self.prompt_pack_name else self.base_model

        # Build identifying info: prompt row, variant, batch
        id_parts = []
        # Always show row number (0-based in data, show as 1-based)
        id_parts.append(f"row={self.prompt_pack_row_index}")
        # Show variant if not the first or if there's a config variant
        if self.variant_index > 0:
            id_parts.append(f"v={self.variant_index + 1}")
        # Show batch if not the first
        if self.batch_index > 0:
            id_parts.append(f"b={self.batch_index + 1}")
        # Add config variant if not base
        if self.config_variant_label and self.config_variant_label != "base":
            id_parts.append(self.config_variant_label)

        id_info = f" [{', '.join(id_parts)}]" if id_parts else ""

        # Image count info
        if self.estimated_image_count > 1:
            image_info = f" | {self.estimated_image_count} imgs"
        else:
            image_info = " | 1 img"

        # Resolution and settings
        settings_info = f" | {self.width}Ã—{self.height} | {self.steps}s"

        return f"{primary_label}{id_info}{image_info}{settings_info}"


@dataclass
class RuntimeJobStatus:
    """Runtime execution status for the currently running job.

    This dataclass contains dynamic execution state that changes during job execution.
    It's separate from UnifiedJobSummary (which contains static NJR-derived data).

    Populated by SingleNodeJobRunner during execution and consumed by RunningJobPanelV2.
    """

    job_id: str
    current_stage: str  # e.g., "txt2img", "img2img", "upscale"
    stage_index: int  # 0-based current stage index
    total_stages: int  # Total number of stages in the job
    progress: float  # 0.0 to 1.0, percentage through current stage
    eta_seconds: float | None  # Estimated seconds remaining for current stage
    started_at: datetime  # When this stage started
    actual_seed: int | None  # The actual seed used (may differ from config if random)
    current_step: int  # Current step within stage (for progress bar)
    total_steps: int  # Total steps for current stage
    stage_detail: str | None = None  # Optional finer-grained phase within the current stage

    def get_stage_label(self) -> str:
        """Get formatted stage label like '2/3 img2img'."""
        return f"{self.stage_index + 1}/{self.total_stages} {self.current_stage}"

    def get_stage_display(self) -> str:
        """Get stage label including optional finer-grained runtime detail."""
        label = self.get_stage_label()
        if self.stage_detail:
            return f"{label} - {self.stage_detail}"
        return label

    def get_progress_percentage(self) -> int:
        """Get progress as integer percentage (0-100)."""
        return int(self.progress * 100)

    def get_eta_display(self) -> str:
        """Get formatted ETA string like '2m 30s' or 'calculating...'."""
        if self.eta_seconds is None:
            return "calculating..."
        if self.eta_seconds < 0:
            return "unknown"

        minutes = int(self.eta_seconds // 60)
        seconds = int(self.eta_seconds % 60)

        if minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"


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
    """Settings for job output directory.

    Attributes:
        base_output_dir: Base directory for job outputs.

    Note:
        Filenames are generated by the runner using a hardcoded convention that prevents
        collisions across matrix variants, batch indices, prompt rows, and variants.
        See pipeline_runner.py for filename construction logic.
    """

    base_output_dir: str = "output"


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
            or record._extract_prompt_field("final_prompt", "prompt", "positive_prompt")
        )
        negative_text = (
            record.negative_prompt
            or (record.txt2img_prompt_info and record.txt2img_prompt_info.final_negative_prompt)
            or record._extract_prompt_field("final_negative_prompt", "negative_prompt")
            or None
        )
        positive_preview = _truncate_display_text(prompt_text, 120)
        negative_preview = _truncate_display_text(negative_text, 120) if negative_text else None
        if record.stage_chain:
            stage_names = record.stage_chain_labels
        else:
            stage_names = record._extract_stage_names()
        stages_display = _format_stage_display(stage_names)
        variant_label = _format_variant_label(record.variant_index, record.variant_total)
        batch_label = _format_batch_label(record.batch_index, record.batch_total)
        seed_display = str(record.seed) if record.seed is not None else "?"

        label = f"{model} | seed={seed_display}"
        if variant_label:
            label += f" {variant_label}"
        if batch_label:
            label += f" {batch_label}"

        status_value = status or "queued"
        created_iso = created_at or _coerce_iso_timestamp(None)
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
# PR-QUEUE-PERSIST: QueueJobV2 removed (V2 queue system abandoned)
# The V1 JobQueue with NJR-based persistence is the canonical queue implementation.
# ---------------------------------------------------------------------------


__all__ = [
    "CURRENT_NJR_SCHEMA_VERSION",
    "JobStatusV2",
    "BatchSettings",
    "ImageWorkloadSpec",
    "LearningJobContext",
    "LoRATag",
    "NJRProvenance",
    "NormalizedJobRecord",
    "OutputSettings",
    "OutputPlan",
    "PackUsageInfo",
    "SourceDescriptor",
    "SourceKind",
    "StageConfig",
    "StagePromptInfo",
    "TrainingWorkloadSpec",
    "VideoWorkloadSpec",
    "WorkloadKind",
    "JobUiSummary",
    "UnifiedJobSummary",
    "JobLifecycleLogEvent",
    "JobView",
    "migrate_legacy_njr",
    "read_njr",
]
