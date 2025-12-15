from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
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

    chain = list(stage_chain) if stage_chain else [make_stage_config()]
    record = NormalizedJobRecord(
        job_id=job_id or f"njr-{uuid.uuid4()}",
        config=config or {"model": base_model, "prompt": positive_prompt},
        path_output_dir="output",
        filename_template="{seed}",
        seed=seed,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        base_model=base_model,
        sampler_name=sampler_name,
        steps=steps,
        cfg_scale=cfg_scale,
        width=width,
        height=height,
        stage_chain=chain,
        variant_index=variant_index,
        variant_total=variant_total,
        batch_index=batch_index,
        batch_total=batch_total,
        images_per_prompt=images_per_prompt,
        config_variant_label=config_variant_label,
        config_variant_index=config_variant_index,
        randomizer_summary=randomizer_summary,
        created_ts=created_ts,
    )
    if extra_metadata:
        record.extra_metadata.update(extra_metadata)
    for attr, value in overrides.items():
        setattr(record, attr, value)
    return record


__all__ = ["make_stage_config", "make_pipeline_njr"]
