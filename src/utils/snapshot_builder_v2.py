"""Snapshot helpers for Phase 9: Job Snapshotting + Deterministic Replay."""

from __future__ import annotations

import logging

import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Mapping

from src.pipeline.job_models_v2 import (
    JobStatusV2,
    LoRATag,
    NormalizedJobRecord,
    StageConfig,
)
from src.queue.job_model import Job

SCHEMA_VERSION = "1.0"

logger = logging.getLogger(__name__)


def _normalize_run_config(run_config: Mapping[str, Any] | None) -> dict[str, Any]:
    if not run_config:
        return {}
    try:
        return {k: v for k, v in dict(run_config).items()}
    except Exception:
        return {"value": str(run_config)}


def _serialize_pipeline_config(config: Any) -> dict[str, Any]:
    if config is None:
        return {}
    if isinstance(config, dict):
        return dict(config)
    if is_dataclass(config):
        try:
            return asdict(config)
        except Exception:
            pass
    if hasattr(config, "to_dict"):
        try:
            return config.to_dict()
        except Exception:
            pass
    if hasattr(config, "__dict__"):
        return {k: v for k, v in vars(config).items() if not k.startswith("_")}
    return {"repr": getattr(config, "__repr__", lambda: str(config))()}


def _config_value(config: Any, *keys: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        for key in keys:
            if key in config and config[key] not in (None, ""):
                return config[key]
        return default
    for key in keys:
        value = getattr(config, key, None)
        if value not in (None, ""):
            return value
    return default


def _extract_effective_prompts(config: Any) -> dict[str, str]:
    positive = _config_value(config, "prompt", "positive_prompt", default="")
    negative = _config_value(
        config,
        "negative_prompt",
        "negative_prompt_text",
        "neg_prompt",
        default="",
    )
    return {"positive": str(positive) if positive else "", "negative": str(negative) if negative else ""}


def _extract_model_selection(config: Any) -> dict[str, str | None]:
    base_model = _config_value(config, "model", "model_name", default=None)
    refiner = _config_value(config, "refiner_model", default=None)
    vae = _config_value(config, "vae_name", "vae", default=None)
    return {"base_model": base_model, "refiner_model": refiner, "vae_model": vae}


def _normalize_prompt_source(value: Any) -> str:
    return str(value or "").strip().lower()


def _ensure_prompt_pack_metadata(job: Job, normalized_job: NormalizedJobRecord) -> None:
    job_prompt_source = _normalize_prompt_source(getattr(job, "prompt_source", None))
    record_prompt_source = _normalize_prompt_source(getattr(normalized_job, "prompt_source", None))
    is_pack_job = job_prompt_source == "pack" or record_prompt_source == "pack"
    if not is_pack_job:
        return
    repaired = False
    job_pack_id = getattr(job, "prompt_pack_id", None)
    if not normalized_job.prompt_pack_id and job_pack_id:
        normalized_job.prompt_pack_id = job_pack_id
        repaired = True
    job_pack_name = getattr(job, "prompt_pack_name", None)
    if not normalized_job.prompt_pack_name and job_pack_name:
        normalized_job.prompt_pack_name = job_pack_name
        repaired = True
    if job_prompt_source == "pack" and record_prompt_source != "pack":
        normalized_job.prompt_source = "pack"
        repaired = True
    if repaired:
        logger.debug(
            "Repaired missing prompt pack metadata for normalized job",
            extra={
                "job_id": job.job_id,
                "prompt_pack_id": normalized_job.prompt_pack_id,
                "prompt_pack_name": normalized_job.prompt_pack_name,
            },
        )


def _extract_stage_metadata(config: Any) -> dict[str, Any]:
    stages = _config_value(config, "stages", default=[]) or []
    stage_flags = {
        "txt2img": bool(_config_value(config, "stage_txt2img_enabled", default=None) or "txt2img" in stages),
        "img2img": bool(_config_value(config, "stage_img2img_enabled", default=None) or "img2img" in stages),
        "refiner": bool(_config_value(config, "refiner_enabled", "refiner", default=False)),
        "hires": bool(_config_value(config, "hires_enabled", "hires_fix", default=False)),
        "upscale": bool(_config_value(config, "upscale_enabled", "upscale", default=False)),
        "adetailer": bool(_config_value(config, "adetailer_enabled", default=False)),
    }
    return {"stages": list(stages), "flags": stage_flags}


def _serialize_stage_chain(chain: list[StageConfig]) -> list[dict[str, Any]]:
    return [asdict(stage) for stage in chain]


def _deserialize_stage_chain(data: Any) -> list[StageConfig]:
    result: list[StageConfig] = []
    if not data:
        return result
    for entry in data:
        if isinstance(entry, StageConfig):
            result.append(entry)
        elif isinstance(entry, dict):
            try:
                result.append(StageConfig(**entry))
            except Exception:
                continue
    return result


def _serialize_lora_tags(tags: list[LoRATag]) -> list[dict[str, Any]]:
    return [asdict(tag) for tag in tags]


def _deserialize_lora_tags(data: Any) -> list[LoRATag]:
    result: list[LoRATag] = []
    if not data:
        return result
    for entry in data:
        if isinstance(entry, LoRATag):
            result.append(entry)
        elif isinstance(entry, dict):
            try:
                name = entry.get("name", "")
                weight = float(entry.get("weight", 0.0))
            except (TypeError, ValueError):
                continue
            result.append(LoRATag(name=name, weight=weight))
    return result


def _serialize_normalized_job(record: NormalizedJobRecord) -> dict[str, Any]:
    status_value = record.status.value if isinstance(record.status, JobStatusV2) else str(record.status)
    return {
        "job_id": record.job_id,
        "path_output_dir": record.path_output_dir,
        "filename_template": record.filename_template,
        "seed": record.seed,
        "variant_index": record.variant_index,
        "variant_total": record.variant_total,
        "batch_index": record.batch_index,
        "batch_total": record.batch_total,
        "created_ts": record.created_ts,
        "randomizer_summary": record.randomizer_summary,
        "config": _serialize_pipeline_config(record.config),
        "prompt_pack_id": record.prompt_pack_id,
        "prompt_pack_name": record.prompt_pack_name,
        "prompt_pack_row_index": record.prompt_pack_row_index,
        "prompt_pack_version": record.prompt_pack_version,
        "prompt_source": getattr(record, "prompt_source", "") or "",
        "positive_prompt": record.positive_prompt,
        "negative_prompt": record.negative_prompt,
        "positive_embeddings": list(record.positive_embeddings),
        "negative_embeddings": list(record.negative_embeddings),
        "lora_tags": _serialize_lora_tags(record.lora_tags),
        "matrix_slot_values": dict(record.matrix_slot_values),
        "steps": record.steps,
        "cfg_scale": record.cfg_scale,
        "width": record.width,
        "height": record.height,
        "sampler_name": record.sampler_name,
        "scheduler": record.scheduler,
        "clip_skip": record.clip_skip,
        "base_model": record.base_model,
        "vae": record.vae,
        "stage_chain": _serialize_stage_chain(record.stage_chain),
        "loop_type": record.loop_type,
        "loop_count": record.loop_count,
        "images_per_prompt": record.images_per_prompt,
        "variant_mode": record.variant_mode,
        "run_mode": record.run_mode,
        "queue_source": record.queue_source,
        "randomization_enabled": record.randomization_enabled,
        "matrix_name": record.matrix_name,
        "matrix_mode": record.matrix_mode,
        "matrix_prompt_mode": record.matrix_prompt_mode,
        "aesthetic_enabled": record.aesthetic_enabled,
        "aesthetic_weight": record.aesthetic_weight,
        "aesthetic_text": record.aesthetic_text,
        "aesthetic_embedding": record.aesthetic_embedding,
        "extra_metadata": dict(record.extra_metadata or {}),
        "output_paths": list(record.output_paths),
        "thumbnail_path": record.thumbnail_path,
        "status": status_value,
        "error_message": record.error_message,
        "completed_at_ts": record.completed_at.timestamp() if record.completed_at else None,
    }


def _deserialize_normalized_job(data: Mapping[str, Any]) -> NormalizedJobRecord | None:
    if not data:
        return None
    status_value = data.get("status", JobStatusV2.QUEUED.value)
    try:
        status = JobStatusV2(status_value)
    except ValueError:
        status = JobStatusV2.QUEUED
    completed_at_ts = data.get("completed_at_ts")
    completed_at = None
    if isinstance(completed_at_ts, (int, float)):
        try:
            completed_at = datetime.fromtimestamp(completed_at_ts)
        except Exception:
            completed_at = None

    def _coerce_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    record = NormalizedJobRecord(
        job_id=str(data.get("job_id") or uuid.uuid4()),
        config=data.get("config") or {},
        path_output_dir=data.get("path_output_dir", ""),
        filename_template=data.get("filename_template", "{seed}"),
        seed=data.get("seed"),
        variant_index=_coerce_int(data.get("variant_index", 0)),
        variant_total=_coerce_int(data.get("variant_total", 1)),
        batch_index=_coerce_int(data.get("batch_index", 0)),
        batch_total=_coerce_int(data.get("batch_total", 1)),
        created_ts=float(data.get("created_ts", time.time())),
        randomizer_summary=data.get("randomizer_summary"),
        prompt_pack_id=str(data.get("prompt_pack_id", "") or ""),
        prompt_pack_name=str(data.get("prompt_pack_name", "") or ""),
        prompt_pack_row_index=_coerce_int(data.get("prompt_pack_row_index", 0)),
        prompt_pack_version=data.get("prompt_pack_version"),
        positive_prompt=str(data.get("positive_prompt", "") or ""),
        negative_prompt=str(data.get("negative_prompt", "") or ""),
        positive_embeddings=list(data.get("positive_embeddings") or []),
        negative_embeddings=list(data.get("negative_embeddings") or []),
        lora_tags=_deserialize_lora_tags(data.get("lora_tags")),
        matrix_slot_values=dict(data.get("matrix_slot_values") or {}),
        steps=_coerce_int(data.get("steps", 0)),
        cfg_scale=float(data.get("cfg_scale", 0.0) or 0.0),
        width=_coerce_int(data.get("width", 0)),
        height=_coerce_int(data.get("height", 0)),
        sampler_name=str(data.get("sampler_name", "") or ""),
        scheduler=str(data.get("scheduler", "") or ""),
        clip_skip=_coerce_int(data.get("clip_skip", 0)),
        base_model=str(data.get("base_model", "") or ""),
        vae=data.get("vae"),
        stage_chain=_deserialize_stage_chain(data.get("stage_chain")),
        loop_type=str(data.get("loop_type", "pipeline") or "pipeline"),
        loop_count=_coerce_int(data.get("loop_count", 1)),
        images_per_prompt=_coerce_int(data.get("images_per_prompt", 1)),
        variant_mode=str(data.get("variant_mode", "standard") or "standard"),
        run_mode=str(data.get("run_mode", "QUEUE") or "QUEUE"),
        queue_source=str(data.get("queue_source", "ADD_TO_QUEUE") or "ADD_TO_QUEUE"),
        randomization_enabled=bool(data.get("randomization_enabled", False)),
        matrix_name=data.get("matrix_name"),
        matrix_mode=data.get("matrix_mode"),
        matrix_prompt_mode=data.get("matrix_prompt_mode"),
        aesthetic_enabled=bool(data.get("aesthetic_enabled", False)),
        aesthetic_weight=data.get("aesthetic_weight"),
        aesthetic_text=data.get("aesthetic_text"),
        aesthetic_embedding=data.get("aesthetic_embedding"),
        extra_metadata=dict(data.get("extra_metadata") or {}),
        output_paths=list(data.get("output_paths") or []),
        thumbnail_path=data.get("thumbnail_path"),
        completed_at=completed_at,
        status=status,
        error_message=data.get("error_message"),
    )
    prompt_source = data.get("prompt_source")
    if prompt_source is not None:
        try:
            record.prompt_source = str(prompt_source)
        except Exception:
            pass
    return record


def build_job_snapshot(
    job: Job,
    normalized_job: NormalizedJobRecord,
    *,
    run_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a serializable job snapshot for replay + history."""

    _ensure_prompt_pack_metadata(job, normalized_job)
    config = normalized_job.config
    timestamp = datetime.utcnow().isoformat()
    legacy_mode = False
    if not normalized_job.prompt_pack_id and _normalize_prompt_source(getattr(job, "prompt_source", None)) == "pack":
        legacy_mode = True
    return {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": timestamp,
        "job_id": job.job_id,
        "run_config": _normalize_run_config(run_config),
        "normalized_job": _serialize_normalized_job(normalized_job),
        "effective_prompts": _extract_effective_prompts(config),
        "seed_info": {
            "master_seed": normalized_job.seed,
            "variant_index": normalized_job.variant_index,
            "variant_total": normalized_job.variant_total,
            "batch_index": normalized_job.batch_index,
            "batch_total": normalized_job.batch_total,
        },
        "stage_metadata": _extract_stage_metadata(config),
        "randomizer_expansions": normalized_job.randomizer_summary or {},
        "model_selection": _extract_model_selection(config),
        "source": job.source,
        "prompt_source": job.prompt_source,
        "legacy_snapshot_mode": legacy_mode,
    }


def normalized_job_from_snapshot(snapshot: Mapping[str, Any]) -> NormalizedJobRecord | None:
    normalized = snapshot.get("normalized_job")
    legacy_snapshot_mode = False
    if isinstance(normalized, Mapping):
        record = _deserialize_normalized_job(normalized)
        if record is not None and snapshot.get("legacy_snapshot_mode"):
            legacy_snapshot_mode = True
        if record and legacy_snapshot_mode:
            record.extra_metadata["legacy_snapshot_mode"] = True
        return record
    return None
