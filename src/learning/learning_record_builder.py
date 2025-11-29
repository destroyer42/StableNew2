# Subsystem: Learning
# Role: Builds LearningRecord instances from pipeline outputs and metadata.

"""Helper for constructing LearningRecord instances from pipeline runs."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Optional, TYPE_CHECKING

from src.learning.learning_record import LearningRecord, _now_iso

if TYPE_CHECKING:  # pragma: no cover
    from src.pipeline.pipeline_runner import PipelineConfig, PipelineRunResult


def _extract_primary_knobs(config: dict[str, Any]) -> dict[str, Any]:
    txt2img = (config or {}).get("txt2img", {}) or {}
    return {
        "model": txt2img.get("model", ""),
        "sampler": txt2img.get("sampler_name", ""),
        "scheduler": txt2img.get("scheduler", ""),
        "steps": txt2img.get("steps", 0),
        "cfg_scale": txt2img.get("cfg_scale", 0.0),
    }


def _stage_plan_list(run_result: PipelineRunResult) -> list[str]:
    plan = getattr(run_result, "stage_plan", None)
    stages: list[str] = []
    if plan and getattr(plan, "stages", None):
        try:
            stages = [getattr(stage, "stage_type", "") for stage in plan.stages]
        except Exception:
            stages = []
    return [s for s in stages if s]


def build_learning_record(
    pipeline_config: PipelineConfig,
    run_result: PipelineRunResult,
    learning_context: Optional[dict[str, Any]] = None,
) -> LearningRecord:
    """
    Build a LearningRecord from pipeline inputs and outputs without performing IO.
    """

    config_dict = asdict(pipeline_config)
    variant_configs = config_dict.get("variant_configs") or []
    randomizer_mode = config_dict.get("randomizer_mode") or ""
    randomizer_plan_size = config_dict.get("randomizer_plan_size") or len(variant_configs)
    metadata = dict(config_dict.get("metadata") or {})
    if learning_context:
        metadata.update(learning_context)
    rr_meta = getattr(run_result, "metadata", {}) or {}
    timestamp_value = metadata.get("timestamp") or rr_meta.get("timestamp") or _now_iso()

    base_config: dict[str, Any] = (variant_configs[0] if variant_configs else config_dict) or {}
    if isinstance(base_config, dict) and "txt2img" not in base_config:
        base_config = dict(base_config)
        base_config["txt2img"] = {
            "model": config_dict.get("model", ""),
            "sampler_name": config_dict.get("sampler", ""),
            "steps": config_dict.get("steps", 0),
            "cfg_scale": config_dict.get("cfg_scale", 0.0),
            "width": config_dict.get("width", 0),
            "height": config_dict.get("height", 0),
        }
    primary_knobs = _extract_primary_knobs(base_config if isinstance(base_config, dict) else {})
    # Discover sidecar priors for model and LoRA
    from pathlib import Path
    from src.learning.learning_profile_sidecar import find_profile_sidecar
    sidecar_priors = {}
    model_name = str(primary_knobs.get("model", ""))
    if model_name:
        model_sidecar = find_profile_sidecar(Path("profiles"), model_name)
        if model_sidecar:
            sidecar_priors[model_name] = model_sidecar.get_prior()
    # If LoRA(s) are present in config, add their priors
    loras = base_config.get("txt2img", {}).get("loras", [])
    for lora in loras:
        lora_name = lora.get("name") if isinstance(lora, dict) else str(lora)
        if lora_name:
            lora_sidecar = find_profile_sidecar(Path("profiles"), lora_name)
            if lora_sidecar:
                sidecar_priors[lora_name] = lora_sidecar.get_prior()
    record = LearningRecord(
        run_id=run_result.run_id,
        timestamp=timestamp_value,
        base_config=base_config,
        variant_configs=list(variant_configs),
        randomizer_mode=randomizer_mode,
        randomizer_plan_size=randomizer_plan_size,
        primary_model=str(primary_knobs.get("model", "")),
        primary_sampler=str(primary_knobs.get("sampler", "")),
        primary_scheduler=str(primary_knobs.get("scheduler", "")),
        primary_steps=int(primary_knobs.get("steps", 0)),
        primary_cfg_scale=float(primary_knobs.get("cfg_scale", 0.0)),
        metadata=metadata,
        stage_plan=_stage_plan_list(run_result),
        stage_events=getattr(run_result, "stage_events", []) or [],
        outputs=getattr(run_result, "metadata", {}).get("stage_outputs", []) if hasattr(run_result, "metadata") else [],
        sidecar_priors=sidecar_priors,
    )
    return record
