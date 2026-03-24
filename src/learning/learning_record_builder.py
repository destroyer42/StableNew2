# Subsystem: Learning
# Role: Builds LearningRecord instances from pipeline outputs and metadata.

"""Helper for constructing LearningRecord instances from pipeline runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from src.learning.learning_record import LearningRecord, _now_iso
from src.refinement.quality_metrics import build_refinement_learning_context
from src.video.motion.secondary_motion_metrics import build_secondary_motion_learning_context

if TYPE_CHECKING:  # pragma: no cover
    from src.pipeline.pipeline_runner import PipelineRunResult


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


def _extract_output_paths(run_result: PipelineRunResult) -> list[str]:
    paths: list[str] = []
    for variant in getattr(run_result, "variants", []) or []:
        if not isinstance(variant, dict):
            continue
        for key in ("path", "output_path", "video_path"):
            value = variant.get(key)
            if isinstance(value, str) and value:
                paths.append(value)
        for key in ("all_paths", "output_paths", "frame_paths"):
            values = variant.get(key)
            if isinstance(values, list):
                paths.extend(str(item) for item in values if str(item or "").strip())
        artifact = variant.get("artifact")
        if isinstance(artifact, dict):
            primary = artifact.get("primary_path")
            if isinstance(primary, str) and primary:
                paths.append(primary)
    deduped: list[str] = []
    for item in paths:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, Mapping):
        return _truthy_flag(value.get("enabled"))
    return bool(value)


def _prompt_optimizer_learning_enabled(
    metadata: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
) -> bool:
    for candidate in (
        metadata.get("prompt_optimizer_learning"),
        run_metadata.get("prompt_optimizer_learning"),
    ):
        if isinstance(candidate, Mapping):
            return _truthy_flag(candidate.get("enabled"))

    for candidate in (
        metadata.get("prompt_optimizer_learning_enabled"),
        run_metadata.get("prompt_optimizer_learning_enabled"),
    ):
        if candidate is not None:
            return _truthy_flag(candidate)

    return False


def _extract_prompt_optimizer_v3_record(run_result: PipelineRunResult) -> dict[str, Any]:
    run_metadata = getattr(run_result, "metadata", {}) or {}
    direct_record = run_metadata.get("prompt_optimizer_v3")
    if isinstance(direct_record, Mapping):
        return dict(direct_record)

    for variant in getattr(run_result, "variants", []) or []:
        if not isinstance(variant, Mapping):
            continue
        variant_record = variant.get("prompt_optimizer_v3")
        if isinstance(variant_record, Mapping):
            return dict(variant_record)

    return {}


def _build_prompt_optimizer_learning_context(
    run_result: PipelineRunResult,
    *,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    bundle = _extract_prompt_optimizer_v3_record(run_result)
    if not bundle:
        return {}

    inputs = dict(bundle.get("inputs") or {})
    outputs = dict(bundle.get("outputs") or {})
    context = dict(bundle.get("context") or {})
    intent = dict(bundle.get("intent") or {})
    policy = dict(bundle.get("policy") or {})
    stage_policy = dict(policy.get("stage_policy") or {})
    recommendation_ids = [
        str(item.get("recommendation_id"))
        for item in policy.get("recommendations") or []
        if isinstance(item, Mapping) and str(item.get("recommendation_id") or "").strip()
    ]
    prompt_source = dict(inputs.get("prompt_source") or {})
    prompt_optimizer_learning = metadata.get("prompt_optimizer_learning")
    preset_id = str(metadata.get("prompt_optimizer_learning_preset") or "").strip()
    if not preset_id and isinstance(prompt_optimizer_learning, Mapping):
        preset_id = str(prompt_optimizer_learning.get("preset_id") or "").strip()
    positive_original = str(inputs.get("positive_original") or "")
    negative_original = str(inputs.get("negative_original") or "")
    positive_final = str(outputs.get("positive_final") or "")
    negative_final = str(outputs.get("negative_final") or "")
    bucket_counts = dict(context.get("bucket_counts") or {})
    positive_bucket_counts = dict(bucket_counts.get("positive") or {})
    negative_bucket_counts = dict(bucket_counts.get("negative") or {})
    chunk_counts = dict(context.get("chunk_counts") or {})

    return {
        "schema": str(bundle.get("schema") or ""),
        "version": str(bundle.get("version") or ""),
        "stage": str(bundle.get("stage") or ""),
        "mode": str(bundle.get("mode") or ""),
        "preset_id": preset_id,
        "stage_policy_mode": str(stage_policy.get("mode") or ""),
        "applied_setting_keys": sorted(
            str(key) for key in (stage_policy.get("applied_settings") or {}).keys()
        ),
        "recommendation_ids": recommendation_ids,
        "recommendation_count": len(recommendation_ids),
        "positive_changed": positive_original != positive_final,
        "negative_changed": negative_original != negative_final,
        "positive_chunk_count": int(chunk_counts.get("positive") or 0),
        "negative_chunk_count": int(chunk_counts.get("negative") or 0),
        "positive_bucket_count": sum(int(value or 0) for value in positive_bucket_counts.values()),
        "negative_bucket_count": sum(int(value or 0) for value in negative_bucket_counts.values()),
        "lora_count": len(context.get("loras") or []),
        "embedding_count": len(context.get("embeddings") or []),
        "intent_band": str(intent.get("intent_band") or ""),
        "requested_pose": str(intent.get("requested_pose") or ""),
        "wants_face_detail": bool(intent.get("wants_face_detail")),
        "has_people_tokens": bool(intent.get("has_people_tokens")),
        "has_conflicts": bool(intent.get("conflicts")),
        "warning_count": len(bundle.get("warnings") or []),
        "error_count": len(bundle.get("errors") or []),
        "prompt_source": {
            "prompt_source": str(prompt_source.get("prompt_source") or ""),
            "prompt_pack_id": str(prompt_source.get("prompt_pack_id") or ""),
            "run_mode": str(prompt_source.get("run_mode") or ""),
            "source": str(prompt_source.get("source") or ""),
            "tags": [
                str(item)
                for item in prompt_source.get("tags") or []
                if str(item or "").strip()
            ],
        },
    }


def build_learning_record(
    pipeline_config: Any,
    run_result: PipelineRunResult,
    learning_context: dict[str, Any] | None = None,
) -> LearningRecord:
    """
    Build a LearningRecord from pipeline inputs and outputs without performing IO.
    """

    config_dict = asdict(pipeline_config)
    variant_configs = config_dict.get("variant_configs") or []
    randomizer_mode = (
        config_dict.get("randomizer_mode")
        or config_dict.get("variant_mode")
        or getattr(pipeline_config, "randomizer_mode", "")
        or getattr(pipeline_config, "variant_mode", "")
    ) or ""
    randomizer_plan_size = config_dict.get("randomizer_plan_size") or len(variant_configs)
    metadata = dict(config_dict.get("metadata") or {})
    if learning_context:
        metadata.update(learning_context)
    rr_meta = getattr(run_result, "metadata", {}) or {}
    if "adaptive_refinement" not in metadata:
        refinement_context = build_refinement_learning_context(
            rr_meta.get("adaptive_refinement"),
            output_paths=_extract_output_paths(run_result),
        )
        if refinement_context:
            metadata["adaptive_refinement"] = refinement_context
    if "secondary_motion" not in metadata:
        secondary_motion_context = build_secondary_motion_learning_context(rr_meta)
        if secondary_motion_context:
            metadata["secondary_motion"] = secondary_motion_context
    if "prompt_optimizer_learning" not in metadata and _prompt_optimizer_learning_enabled(metadata, rr_meta):
        prompt_optimizer_context = _build_prompt_optimizer_learning_context(
            run_result,
            metadata=metadata,
        )
        if prompt_optimizer_context:
            metadata["prompt_optimizer_learning"] = prompt_optimizer_context
    timestamp_value = metadata.get("timestamp") or rr_meta.get("timestamp") or _now_iso()

    base_config: dict[str, Any] = (variant_configs[0] if variant_configs else config_dict) or {}
    if isinstance(base_config, dict) and "txt2img" not in base_config:
        base_config = dict(base_config)
        config_payload = config_dict.get("config") or {}
        base_config["txt2img"] = {
            "model": config_payload.get("model")
            or getattr(pipeline_config, "base_model", "")
            or config_dict.get("model", ""),
            "sampler_name": config_payload.get("sampler_name")
            or getattr(pipeline_config, "sampler_name", "")
            or config_payload.get("sampler")
            or config_dict.get("sampler", ""),
            "steps": config_payload.get("steps")
            or getattr(pipeline_config, "steps", 0)
            or config_dict.get("steps", 0),
            "cfg_scale": config_payload.get("cfg_scale")
            or getattr(pipeline_config, "cfg_scale", 0.0)
            or config_dict.get("cfg_scale", 0.0),
            "width": config_payload.get("width")
            or getattr(pipeline_config, "width", 0)
            or config_dict.get("width", 0),
            "height": config_payload.get("height")
            or getattr(pipeline_config, "height", 0)
            or config_dict.get("height", 0),
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
        outputs=getattr(run_result, "metadata", {}).get("stage_outputs", [])
        if hasattr(run_result, "metadata")
        else [],
        sidecar_priors=sidecar_priors,
    )
    return record
