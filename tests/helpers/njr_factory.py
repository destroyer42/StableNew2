from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from src.pipeline.job_models_v2 import (
    CURRENT_NJR_SCHEMA_VERSION,
    ImageWorkloadSpec,
    NJRProvenance,
    NormalizedJobRecord,
    OutputPlan,
    SourceDescriptor,
    SourceKind,
    StageConfig,
    TrainingWorkloadSpec,
    VideoWorkloadSpec,
    WorkloadKind,
)
from src.pipeline.stage_models import StageType


def _coerce_stage_type(stage_type: StageType | str) -> str:
    if isinstance(stage_type, StageType):
        return stage_type.value
    return str(stage_type)


def make_stage_config(
    stage_type: StageType | str = StageType.TXT2IMG,
    *,
    steps: int = 20,
    cfg_scale: float = 7.5,
    sampler_name: str = "Euler a",
    model: str = "sdxl",
    enabled: bool = True,
    **overrides: Any,
) -> StageConfig:
    """Return a single stage config suitable for pipeline NJRs."""

    data = {
        "stage_type": _coerce_stage_type(stage_type),
        "enabled": enabled,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "sampler_name": sampler_name,
        "model": model,
        **overrides,
    }
    return StageConfig(**data)


def make_pipeline_njr(
    *,
    job_id: str | None = None,
    positive_prompt: str = "test prompt",
    negative_prompt: str = "",
    base_model: str = "sdxl",
    sampler_name: str = "Euler a",
    steps: int = 20,
    cfg_scale: float = 7.5,
    width: int = 512,
    height: int = 512,
    variant_index: int = 0,
    variant_total: int = 1,
    batch_index: int = 0,
    batch_total: int = 1,
    images_per_prompt: int = 1,
    stage_chain: Sequence[StageConfig] | None = None,
    config: dict[str, Any] | None = None,
    config_variant_label: str = "base",
    config_variant_index: int = 0,
    randomizer_summary: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
    seed: int = 42,
    created_ts: float = 0.0,
    **overrides: Any,
) -> NormalizedJobRecord:
    """Build a minimal NormalizedJobRecord geared toward pipeline runner tests."""

    del created_ts
    chain = tuple(stage_chain) if stage_chain else (make_stage_config(),)
    stage_names = {stage.stage_type for stage in chain if stage.enabled}
    if stage_names & {"animatediff", "svd_native", "video_workflow"}:
        workload_kind = WorkloadKind.VIDEO
        source_kind = SourceKind.VIDEO_WORKFLOW
        workload_class = VideoWorkloadSpec
    elif "train_lora" in stage_names:
        workload_kind = WorkloadKind.TRAINING
        source_kind = SourceKind.TRAINING
        workload_class = TrainingWorkloadSpec
    else:
        workload_kind = WorkloadKind.IMAGE
        source_kind = SourceKind(str(overrides.pop("source_kind", SourceKind.CLI.value)))
        workload_class = ImageWorkloadSpec
    prompt_pack_id = overrides.pop("prompt_pack_id", None)
    prompt_pack_name = overrides.pop("prompt_pack_name", None)
    prompt_pack_row_index = overrides.pop("prompt_pack_row_index", None)
    if prompt_pack_id:
        source_kind = SourceKind.PROMPT_PACK
    workload_kwargs = {
        "positive_prompt": positive_prompt,
        "negative_prompt": negative_prompt,
        "config": config
        or {
            "model": base_model,
            "prompt": positive_prompt,
            "sampler_name": sampler_name,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "width": width,
            "height": height,
        },
        "images_per_prompt": images_per_prompt,
        "input_image_paths": tuple(overrides.pop("input_image_paths", ())),
        "start_stage": overrides.pop("start_stage", None),
        "loop_type": overrides.pop("loop_type", "pipeline"),
        "loop_count": overrides.pop("loop_count", 1),
        "variant_mode": overrides.pop("variant_mode", "standard"),
        "intent_config": overrides.pop("intent_config", {}),
        "backend_options": overrides.pop("backend_options", {}),
        "metadata": extra_metadata or overrides.pop("metadata", {}),
    }
    if workload_class is VideoWorkloadSpec:
        workload = workload_class(
            **workload_kwargs,
            continuity_link=overrides.pop("continuity_link", None),
            sequence_intent=overrides.pop("sequence_intent", None),
        )
    else:
        workload = workload_class(**workload_kwargs)
    return NormalizedJobRecord(
        schema_version=CURRENT_NJR_SCHEMA_VERSION,
        job_id=job_id or f"njr-{uuid.uuid4()}",
        workload_kind=workload_kind,
        source=SourceDescriptor(
            kind=source_kind,
            id=prompt_pack_id,
            display_name=prompt_pack_name,
            row_index=prompt_pack_row_index,
        ),
        workload=workload,
        stages=chain,
        output_plan=OutputPlan(
            base_output_dir=overrides.pop("path_output_dir", "output"),
            filename_template=overrides.pop("filename_template", "{seed}"),
        ),
        provenance=NJRProvenance(
            seed=seed,
            variant_index=variant_index,
            variant_total=variant_total,
            batch_index=batch_index,
            batch_total=batch_total,
            config_variant_label=config_variant_label,
            config_variant_index=config_variant_index,
            randomizer_summary=randomizer_summary or {},
            lora_tags=tuple(overrides.pop("lora_tags", ())),
            positive_embeddings=tuple(overrides.pop("positive_embeddings", ())),
            negative_embeddings=tuple(overrides.pop("negative_embeddings", ())),
            matrix_slot_values=overrides.pop("matrix_slot_values", {}),
            learning_context=overrides.pop("learning_context", None),
            metadata={
                **(extra_metadata or {}),
                **({"test_overrides": sorted(overrides)} if overrides else {}),
            },
        ),
    )


__all__ = ["make_stage_config", "make_pipeline_njr"]
