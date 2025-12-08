"""Snapshot helpers for Phase 9: Job Snapshotting + Deterministic Replay."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Mapping

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_model import Job

SCHEMA_VERSION = "1.0"


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


def _serialize_normalized_job(record: NormalizedJobRecord) -> dict[str, Any]:
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
    }


def _deserialize_normalized_job(data: Mapping[str, Any]) -> NormalizedJobRecord | None:
    if not data:
        return None
    return NormalizedJobRecord(
        job_id=str(data.get("job_id") or uuid.uuid4()),
        config=data.get("config") or {},
        path_output_dir=data.get("path_output_dir", ""),
        filename_template=data.get("filename_template", "{seed}"),
        seed=data.get("seed"),
        variant_index=int(data.get("variant_index", 0)),
        variant_total=int(data.get("variant_total", 1)),
        batch_index=int(data.get("batch_index", 0)),
        batch_total=int(data.get("batch_total", 1)),
        created_ts=float(data.get("created_ts", time.time())),
        randomizer_summary=data.get("randomizer_summary"),
    )


def build_job_snapshot(
    job: Job,
    normalized_job: NormalizedJobRecord,
    *,
    run_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a serializable job snapshot for replay + history."""

    config = normalized_job.config
    timestamp = datetime.utcnow().isoformat()
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
    }


def normalized_job_from_snapshot(snapshot: Mapping[str, Any]) -> NormalizedJobRecord | None:
    normalized = snapshot.get("normalized_job")
    if isinstance(normalized, Mapping):
        return _deserialize_normalized_job(normalized)
    return None
