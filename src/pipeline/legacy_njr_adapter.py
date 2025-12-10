from __future__ import annotations

from dataclasses import asdict
from time import time
from typing import Any
from uuid import uuid4

from src.pipeline.job_models_v2 import (
    JobStatusV2,
    NormalizedJobRecord,
    StageConfig,
)
from src.pipeline.pipeline_runner import PipelineConfig


def _make_default_stage(config: PipelineConfig) -> StageConfig:
    return StageConfig(
        stage_type="txt2img",
        enabled=True,
        steps=config.steps or 20,
        cfg_scale=config.cfg_scale or 7.0,
        sampler_name=config.sampler or "Euler a",
        scheduler=getattr(config, "scheduler", "") or "",
        model=config.model or "unknown",
        vae=None,
        extra={"legacy_adapter": True},
    )


def build_njr_from_legacy_pipeline_config(pipeline_config: PipelineConfig) -> NormalizedJobRecord:
    """
    PR-CORE1-B4:
    Adapter for legacy PipelineConfig-based jobs.

    Produces a best-effort NormalizedJobRecord used only for replay.
    It captures the information available in PipelineConfig and marks the record metadata
    so downstream systems know this came from the legacy path.
    """
    config_snapshot = asdict(pipeline_config)
    stage = _make_default_stage(pipeline_config)
    metadata = dict(pipeline_config.metadata or {})
    run_id = metadata.get("run_id")

    return NormalizedJobRecord(
        job_id=f"legacy-{run_id or uuid4()}",
        config=config_snapshot,
        path_output_dir=metadata.get("_pack_output_dir", "output"),
        filename_template=metadata.get("filename_template", "{seed}"),
        seed=int(metadata.get("seed") or 0),
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=float(metadata.get("created_ts") or time()),
        randomizer_summary={"legacy_adapter": True},
        prompt_pack_id=metadata.get("prompt_pack_id", ""),
        prompt_pack_name=metadata.get("prompt_pack_name", ""),
        prompt_pack_row_index=int(metadata.get("prompt_pack_row_index") or 0),
        positive_prompt=pipeline_config.prompt or "",
        negative_prompt=pipeline_config.negative_prompt or "",
        positive_embeddings=[],
        negative_embeddings=[],
        lora_tags=[],
        matrix_slot_values={},
        steps=pipeline_config.steps or 20,
        cfg_scale=pipeline_config.cfg_scale or 7.0,
        width=pipeline_config.width or 512,
        height=pipeline_config.height or 512,
        sampler_name=pipeline_config.sampler or "Euler a",
        scheduler=getattr(pipeline_config, "scheduler", "") or "",
        base_model=pipeline_config.model or "unknown",
        vae=None,
        stage_chain=[stage],
        loop_type="pipeline",
        loop_count=1,
        images_per_prompt=1,
        variant_mode="legacy",
        run_mode=metadata.get("run_mode", "QUEUE"),
        queue_source=metadata.get("queue_source", "LEGACY"),
        randomization_enabled=False,
        matrix_name=metadata.get("matrix_name"),
        matrix_mode=metadata.get("matrix_mode"),
        matrix_prompt_mode=metadata.get("matrix_prompt_mode"),
        config_variant_label="legacy",
        config_variant_index=0,
        config_variant_overrides={},
        aesthetic_enabled=False,
        extra_metadata={
            "legacy_source": "pipeline_config",
            "core1_b4_adapter": True,
            **({"legacy_metadata": metadata} if metadata else {}),
        },
        output_paths=[],
        thumbnail_path=None,
        status=JobStatusV2.QUEUED,
    )
