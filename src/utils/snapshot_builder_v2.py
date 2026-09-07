"""Snapshot helpers for Phase 9: Job Snapshotting + Deterministic Replay."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from src.pipeline.config_contract_v26 import build_config_layers
from src.pipeline.intent_artifact_contract import build_intent_artifact_contract
from src.pipeline.job_models_v2 import NormalizedJobRecord, read_njr
from src.queue.job_model import Job

SCHEMA_VERSION = "1.0"

logger = logging.getLogger(__name__)


def _normalize_run_config(run_config: Mapping[str, Any] | None) -> dict[str, Any]:
    if not run_config:
        return {}
    try:
        return dict(run_config)
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
    return {
        "positive": str(positive) if positive else "",
        "negative": str(negative) if negative else "",
    }


def _extract_model_selection(config: Any) -> dict[str, str | None]:
    base_model = _config_value(config, "model", "model_name", default=None)
    refiner = _config_value(config, "refiner_model", default=None)
    vae = _config_value(config, "vae_name", "vae", default=None)
    return {"base_model": base_model, "refiner_model": refiner, "vae_model": vae}


def _normalize_prompt_source(value: Any) -> str:
    return str(value or "").strip().lower()


def _extract_stage_metadata(config: Any) -> dict[str, Any]:
    stages = _config_value(config, "stages", default=[]) or []
    stage_flags = {
        "txt2img": bool(
            _config_value(config, "stage_txt2img_enabled", default=None) or "txt2img" in stages
        ),
        "img2img": bool(
            _config_value(config, "stage_img2img_enabled", default=None) or "img2img" in stages
        ),
        "refiner": bool(_config_value(config, "refiner_enabled", "refiner", default=False)),
        "hires": bool(_config_value(config, "hires_enabled", "hires_fix", default=False)),
        "upscale": bool(_config_value(config, "upscale_enabled", "upscale", default=False)),
        "adetailer": bool(_config_value(config, "adetailer_enabled", default=False)),
    }
    return {"stages": list(stages), "flags": stage_flags}


def _serialize_normalized_job(record: NormalizedJobRecord) -> dict[str, Any]:
    return record.to_dict()


def _deserialize_normalized_job(data: Mapping[str, Any]) -> NormalizedJobRecord | None:
    if not data:
        return None
    try:
        return read_njr(data)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Rejected invalid normalized job snapshot: %s", exc)
        return None


def build_job_snapshot(
    job: Job,
    normalized_job: NormalizedJobRecord,
    *,
    run_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a serializable job snapshot for replay + history."""

    config = normalized_job.config
    timestamp = datetime.utcnow().isoformat()
    legacy_mode = False
    if (
        not normalized_job.prompt_pack_id
        and _normalize_prompt_source(getattr(job, "prompt_source", None)) == "pack"
    ):
        legacy_mode = True
    return {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": timestamp,
        "job_id": job.job_id,
        "run_config": _normalize_run_config(run_config),
        "intent_contract": build_intent_artifact_contract(
            {**dict(normalized_job.intent_config or {}), **_normalize_run_config(run_config)}
        ),
        "config_layers": build_config_layers(
            intent_config={
                **dict(normalized_job.intent_config or {}),
                **_normalize_run_config(run_config),
            },
            execution_config=config,
            backend_options=normalized_job.backend_options,
        ).to_dict(),
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
    if isinstance(normalized, Mapping):
        record = _deserialize_normalized_job(normalized)
        return record
    return None
