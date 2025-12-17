"""Legacy NJR Adapter - COMPATIBILITY ONLY (PR-CORE1-12)

This module provides backward compatibility for converting legacy PipelineConfig
objects to NormalizedJobRecord (NJR).

**STATUS: DEPRECATED - DO NOT USE FOR NEW CODE**

As of PR-CORE1-B2 and PR-CORE1-12:
- All new execution MUST use JobBuilderV2 to build NJR directly
- PipelineConfig is NO LONGER a runtime execution payload
- This adapter exists ONLY for:
  1. Deprecated controller methods (app_controller.run_pipeline, etc.)
  2. Historical compatibility during migration period
  3. Reference implementation for understanding legacy behavior

**FUTURE:** This module will be archived once all legacy execution paths are removed.

**DO NOT:**
- Use this for new features
- Create new PipelineConfig → NJR conversion paths
- Add new functions to this module

**INSTEAD:**
- Use JobBuilderV2 + ConfigMergerV2 to build NJR from GUI state + PromptPack
- Follow v2.6 canonical execution path: GUI → Controller → NJR → Queue → Runner
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from time import time
from typing import Any
from uuid import uuid4

from src.controller.archive.pipeline_config_types import PipelineConfig
from src.pipeline.job_models_v2 import (
    JobStatusV2,
    NormalizedJobRecord,
    StageConfig,
)
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot


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


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _strip_draft_fields(data: dict[str, Any]) -> dict[str, Any]:
    legacy_keys = {"draft", "bundle", "draft_bundle", "job_bundle", "bundle_summary"}
    return {k: v for k, v in data.items() if k not in legacy_keys}


def _normalize_model_name(value: Any) -> str:
    name = str(value or "").strip()
    return name or "unknown"


def build_njr_from_history_dict(legacy_dict: dict[str, Any]) -> NormalizedJobRecord:
    """
    Accepts ANY historical job dict from StableNew v1.x -> v2.6.
    Produces a full NJR with all required fields.
    Deterministic hydration.
    """
    data = _strip_draft_fields(dict(legacy_dict or {}))
    snapshot = data.get("snapshot")
    if isinstance(snapshot, Mapping):
        # Prefer normalized_job section if present
        normalized = normalized_job_from_snapshot(snapshot)
        if normalized is None and isinstance(snapshot.get("normalized_job"), Mapping):
            normalized = normalized_job_from_snapshot(
                {"normalized_job": snapshot["normalized_job"]}
            )
        if normalized is not None:
            return normalized

    pipeline_config = data.get("pipeline_config")
    if isinstance(pipeline_config, PipelineConfig):
        return build_njr_from_legacy_pipeline_config(pipeline_config)
    if isinstance(pipeline_config, Mapping):
        config = PipelineConfig(
            prompt=str(pipeline_config.get("prompt", "") or ""),
            model=_normalize_model_name(
                pipeline_config.get("model", "") or pipeline_config.get("model_name", "")
            ),
            sampler=str(
                pipeline_config.get("sampler", "")
                or pipeline_config.get("sampler_name", "")
                or "Euler a"
            ),
            width=_coerce_int(pipeline_config.get("width", 512), 512),
            height=_coerce_int(pipeline_config.get("height", 512), 512),
            steps=_coerce_int(pipeline_config.get("steps", 20), 20),
            cfg_scale=_coerce_float(pipeline_config.get("cfg_scale", 7.0), 7.0),
            negative_prompt=str(pipeline_config.get("negative_prompt", "") or ""),
            metadata=dict(pipeline_config.get("metadata") or {}),
        )
        return build_njr_from_legacy_pipeline_config(config)

    prompt = str(data.get("prompt") or data.get("positive_prompt") or "")
    negative_prompt = str(data.get("negative_prompt") or data.get("neg_prompt") or "")
    model = _normalize_model_name(data.get("model") or data.get("model_name"))
    scheduler = str(data.get("scheduler") or data.get("scheduler_name") or "")
    sampler = str(data.get("sampler") or data.get("sampler_name") or "Euler a") or "Euler a"
    seed = _coerce_int(data.get("seed", 0), 0)
    cfg_scale = _coerce_float(data.get("cfg_scale", 7.0), 7.0)
    steps = _coerce_int(data.get("steps", 20), 20)
    width = _coerce_int(data.get("width", 512), 512)
    height = _coerce_int(data.get("height", 512), 512)
    created_ts = float(data.get("created_ts") or 0.0)
    stage = StageConfig(
        stage_type="txt2img",
        enabled=True,
        steps=steps,
        cfg_scale=cfg_scale,
        sampler_name=sampler,
        scheduler=scheduler,
        model=model,
        vae=None,
        extra={"legacy_adapter": True},
    )

    metadata = dict(data.get("metadata") or {})
    return NormalizedJobRecord(
        job_id=str(data.get("job_id") or data.get("id") or uuid4()),
        config={
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "model": model,
            "sampler": sampler,
            "scheduler": scheduler,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "width": width,
            "height": height,
        },
        path_output_dir=str(data.get("path_output_dir") or data.get("output_dir") or "output"),
        filename_template=str(data.get("filename_template") or "{seed}"),
        seed=seed,
        variant_index=_coerce_int(data.get("variant_index", 0), 0),
        variant_total=_coerce_int(data.get("variant_total", 1), 1),
        batch_index=_coerce_int(data.get("batch_index", 0), 0),
        batch_total=_coerce_int(data.get("batch_total", 1), 1),
        created_ts=created_ts or time(),
        randomizer_summary=data.get("randomizer_summary"),
        prompt_pack_id=str(data.get("prompt_pack_id", "") or ""),
        prompt_pack_name=str(data.get("prompt_pack_name", "") or ""),
        prompt_pack_row_index=_coerce_int(data.get("prompt_pack_row_index", 0), 0),
        positive_prompt=prompt,
        negative_prompt=negative_prompt,
        positive_embeddings=list(data.get("positive_embeddings") or []),
        negative_embeddings=list(data.get("negative_embeddings") or []),
        lora_tags=[],
        matrix_slot_values=dict(data.get("matrix_slot_values") or {}),
        steps=steps,
        cfg_scale=cfg_scale,
        width=width,
        height=height,
        sampler_name=sampler,
        scheduler=scheduler,
        base_model=model,
        vae=data.get("vae"),
        stage_chain=[stage],
        loop_type=str(data.get("loop_type") or "pipeline"),
        loop_count=_coerce_int(data.get("loop_count", 1), 1),
        images_per_prompt=_coerce_int(data.get("images_per_prompt", 1), 1),
        variant_mode=str(data.get("variant_mode") or "legacy"),
        run_mode=str(data.get("run_mode") or "QUEUE"),
        queue_source=str(data.get("queue_source") or "LEGACY"),
        randomization_enabled=bool(data.get("randomization_enabled", False)),
        matrix_name=data.get("matrix_name"),
        matrix_mode=data.get("matrix_mode"),
        matrix_prompt_mode=data.get("matrix_prompt_mode"),
        aesthetic_enabled=bool(data.get("aesthetic_enabled", False)),
        aesthetic_weight=data.get("aesthetic_weight"),
        aesthetic_text=data.get("aesthetic_text"),
        aesthetic_embedding=data.get("aesthetic_embedding"),
        extra_metadata={"legacy_source": "history_dict", "legacy_adapter": True, **metadata},
        output_paths=list(data.get("output_paths") or []),
        thumbnail_path=data.get("thumbnail_path"),
        status=JobStatusV2(str(data.get("status")) if data.get("status") else JobStatusV2.QUEUED),
        error_message=data.get("error_message"),
    )
