from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.pipeline.intent_artifact_contract import (
    INTENT_ARTIFACT_SCHEMA_V1,
    INTENT_ARTIFACT_VERSION_V1,
    compute_intent_hash,
)


CONFIG_CONTRACT_SCHEMA_V26 = "stablenew.config.v2.6"

_EXECUTION_HINT_KEYS = {
    "prompt",
    "negative_prompt",
    "model",
    "model_name",
    "sampler",
    "sampler_name",
    "scheduler",
    "scheduler_name",
    "steps",
    "cfg_scale",
    "width",
    "height",
    "pipeline",
    "txt2img",
    "img2img",
    "adetailer",
    "upscale",
    "animatediff",
    "svd_native",
    "video_workflow",
    "train_lora",
    "hires_fix",
    "refiner",
    "randomization",
    "aesthetic",
    "metadata",
    "continuity",
    "continuity_link",
    "plan_origin",
    "story_plan",
}

_INTENT_TOP_LEVEL_KEYS = (
    "run_mode",
    "source",
    "prompt_source",
    "prompt_pack_id",
    "plan_origin",
    "story_plan",
    "adaptive_refinement",
    "secondary_motion",
    "config_snapshot_id",
    "requested_job_label",
    "selected_row_ids",
    "tags",
    "pipeline_state_snapshot",
)

_KNOWN_VIDEO_BACKEND_STAGES = ("animatediff", "svd_native", "video_workflow")
_VALID_SVD_RESIZE_MODES = {"letterbox", "center_crop", "contain_then_crop"}
_VALID_SVD_OUTPUT_FORMATS = {"mp4", "gif", "frames"}


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    return {}


def _config_layers_mapping(value: Any) -> dict[str, Any]:
    data = _mapping_dict(value)
    layers = data.get("config_layers")
    if isinstance(layers, Mapping):
        return _mapping_dict(layers)
    if any(key in data for key in ("intent_config", "execution_config", "backend_options")):
        return {
            "schema": data.get("schema") or data.get("config_schema") or CONFIG_CONTRACT_SCHEMA_V26,
            "intent_config": _mapping_dict(data.get("intent_config")),
            "execution_config": _mapping_dict(data.get("execution_config")),
            "backend_options": _mapping_dict(data.get("backend_options")),
        }
    return {}


def is_layered_config(value: Any) -> bool:
    return bool(_config_layers_mapping(value))


def canonicalize_intent_config(value: Any) -> dict[str, Any]:
    layers = _config_layers_mapping(value)
    if layers:
        data = _mapping_dict(layers.get("intent_config"))
    else:
        data = _mapping_dict(value)
    normalized: dict[str, Any] = {}
    for key in _INTENT_TOP_LEVEL_KEYS:
        if key not in data:
            continue
        item = data[key]
        if item in (None, ""):
            continue
        if isinstance(item, Mapping) and not item:
            continue
        normalized[key] = deepcopy(item)
    return normalized


def extract_adaptive_refinement_intent(value: Any) -> dict[str, Any]:
    intent = canonicalize_intent_config(value)
    payload = intent.get("adaptive_refinement")
    if isinstance(payload, Mapping) and payload:
        return _mapping_dict(payload)
    return {}


def extract_secondary_motion_intent(value: Any) -> dict[str, Any]:
    intent = canonicalize_intent_config(value)
    payload = intent.get("secondary_motion")
    if isinstance(payload, Mapping) and payload:
        return _mapping_dict(payload)
    return {}


def extract_execution_config(value: Any) -> dict[str, Any]:
    layers = _config_layers_mapping(value)
    if layers:
        return _mapping_dict(layers.get("execution_config"))
    data = _mapping_dict(value)
    if any(key in data for key in _EXECUTION_HINT_KEYS):
        return data
    return {}


def derive_backend_options(execution_config: Mapping[str, Any] | None) -> dict[str, Any]:
    config = _mapping_dict(execution_config)
    video_options: dict[str, Any] = {}
    for stage_name in _KNOWN_VIDEO_BACKEND_STAGES:
        stage_config = config.get(stage_name)
        if isinstance(stage_config, Mapping) and stage_config:
            video_options[stage_name] = _mapping_dict(stage_config)
    workflow_config = config.get("video_workflow")
    if isinstance(workflow_config, Mapping) and workflow_config:
        video_options["workflow"] = _mapping_dict(workflow_config)
    if video_options:
        return {"video": video_options}
    return {}


def _coerce_svd_int(
    value: Any,
    *,
    field_name: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{field_name} must be <= {maximum}")
    return parsed


def _coerce_svd_float(
    value: Any,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{field_name} must be <= {maximum}")
    return parsed


def _validate_choice(value: Any, *, field_name: str, allowed_values: set[str]) -> None:
    text = str(value or "").strip()
    if text and text not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ValueError(f"{field_name} must be one of: {allowed}")


def validate_svd_native_execution_config(value: Any) -> dict[str, Any]:
    data = _mapping_dict(value)
    payload = _mapping_dict(data.get("svd_native")) if isinstance(data.get("svd_native"), Mapping) else data

    preprocess = _mapping_dict(payload.get("preprocess"))
    inference = _mapping_dict(payload.get("inference"))
    output = _mapping_dict(payload.get("output"))
    postprocess = _mapping_dict(payload.get("postprocess"))

    if preprocess:
        if "target_width" in preprocess:
            _coerce_svd_int(preprocess.get("target_width"), field_name="preprocess.target_width", minimum=1)
        if "target_height" in preprocess:
            _coerce_svd_int(preprocess.get("target_height"), field_name="preprocess.target_height", minimum=1)
        if "resize_mode" in preprocess:
            _validate_choice(
                preprocess.get("resize_mode"),
                field_name="preprocess.resize_mode",
                allowed_values=_VALID_SVD_RESIZE_MODES,
            )

    if inference:
        if "num_frames" in inference:
            _coerce_svd_int(inference.get("num_frames"), field_name="inference.num_frames", minimum=1)
        if "fps" in inference:
            _coerce_svd_int(inference.get("fps"), field_name="inference.fps", minimum=1)
        if "motion_bucket_id" in inference:
            _coerce_svd_int(
                inference.get("motion_bucket_id"),
                field_name="inference.motion_bucket_id",
                minimum=0,
                maximum=255,
            )
        if "noise_aug_strength" in inference:
            _coerce_svd_float(
                inference.get("noise_aug_strength"),
                field_name="inference.noise_aug_strength",
                minimum=0.0,
                maximum=1.0,
            )
        if "decode_chunk_size" in inference:
            _coerce_svd_int(
                inference.get("decode_chunk_size"),
                field_name="inference.decode_chunk_size",
                minimum=1,
            )
        if "num_inference_steps" in inference:
            _coerce_svd_int(
                inference.get("num_inference_steps"),
                field_name="inference.num_inference_steps",
                minimum=1,
            )

    if output and "output_format" in output:
        _validate_choice(
            output.get("output_format"),
            field_name="output.output_format",
            allowed_values=_VALID_SVD_OUTPUT_FORMATS,
        )

    face_restore = _mapping_dict(postprocess.get("face_restore"))
    if face_restore and "fidelity_weight" in face_restore:
        _coerce_svd_float(
            face_restore.get("fidelity_weight"),
            field_name="postprocess.face_restore.fidelity_weight",
            minimum=0.0,
            maximum=1.0,
        )

    interpolation = _mapping_dict(postprocess.get("interpolation"))
    if interpolation and "multiplier" in interpolation:
        _coerce_svd_int(
            interpolation.get("multiplier"),
            field_name="postprocess.interpolation.multiplier",
            minimum=2,
        )

    upscale = _mapping_dict(postprocess.get("upscale"))
    if upscale and "scale" in upscale:
        _coerce_svd_float(
            upscale.get("scale"),
            field_name="postprocess.upscale.scale",
            minimum=1.0,
        )

    return data


def validate_train_lora_execution_config(value: Any) -> dict[str, Any]:
    data = _mapping_dict(value)
    nested = isinstance(data.get("train_lora"), Mapping)
    payload = _mapping_dict(data.get("train_lora")) if nested else data

    character_name = str(payload.get("character_name") or "").strip()
    if not character_name:
        raise ValueError("character_name is required")
    image_dir = str(Path(str(payload.get("image_dir") or "")).expanduser()).strip()
    if not image_dir:
        raise ValueError("image_dir is required")
    output_dir = str(Path(str(payload.get("output_dir") or "")).expanduser()).strip()
    if not output_dir:
        raise ValueError("output_dir is required")

    epochs = _coerce_svd_int(payload.get("epochs"), field_name="epochs", minimum=1)
    learning_rate_value = payload.get("learning_rate", payload.get("lr"))
    if learning_rate_value in (None, ""):
        raise ValueError("learning_rate is required")
    learning_rate = _coerce_svd_float(
        learning_rate_value,
        field_name="learning_rate",
        minimum=0.0,
    )
    if learning_rate <= 0:
        raise ValueError("learning_rate must be > 0")

    normalized_payload: dict[str, Any] = dict(payload)
    normalized_payload["enabled"] = bool(payload.get("enabled", True))
    normalized_payload["character_name"] = character_name
    normalized_payload["image_dir"] = image_dir
    normalized_payload["output_dir"] = output_dir
    normalized_payload["epochs"] = epochs
    normalized_payload["learning_rate"] = learning_rate
    normalized_payload["lr"] = learning_rate

    for field_name in (
        "base_model",
        "trigger_phrase",
        "output_name",
        "produced_weight_path",
        "trainer_working_dir",
    ):
        if normalized_payload.get(field_name) not in (None, ""):
            normalized_payload[field_name] = str(normalized_payload[field_name]).strip()

    for field_name in ("rank", "network_alpha"):
        if normalized_payload.get(field_name) in (None, ""):
            normalized_payload.pop(field_name, None)
            continue
        normalized_payload[field_name] = _coerce_svd_int(
            normalized_payload[field_name],
            field_name=field_name,
            minimum=1,
        )

    trainer_command = normalized_payload.get("trainer_command")
    if trainer_command in (None, "", []):
        normalized_payload.pop("trainer_command", None)
    elif isinstance(trainer_command, str):
        normalized_payload["trainer_command"] = trainer_command.strip()
    elif isinstance(trainer_command, (list, tuple)):
        normalized_payload["trainer_command"] = [
            str(item).strip() for item in trainer_command if str(item).strip()
        ]
        if not normalized_payload["trainer_command"]:
            normalized_payload.pop("trainer_command", None)
    else:
        raise ValueError("trainer_command must be a string or list of strings")

    trainer_args = normalized_payload.get("trainer_args", normalized_payload.get("trainer_extra_args"))
    if trainer_args in (None, "", []):
        normalized_payload.pop("trainer_args", None)
        normalized_payload.pop("trainer_extra_args", None)
    elif isinstance(trainer_args, str):
        normalized_payload["trainer_args"] = trainer_args.strip()
    elif isinstance(trainer_args, (list, tuple)):
        normalized_payload["trainer_args"] = [
            str(item).strip() for item in trainer_args if str(item).strip()
        ]
    else:
        raise ValueError("trainer_args must be a string or list of strings")

    if not nested:
        return normalized_payload

    normalized = dict(data)
    normalized["train_lora"] = normalized_payload
    pipeline = _mapping_dict(data.get("pipeline"))
    pipeline["train_lora_enabled"] = bool(
        pipeline.get("train_lora_enabled", normalized_payload.get("enabled", True))
    )
    normalized["pipeline"] = pipeline
    return normalized


def extract_continuity_linkage(value: Any) -> dict[str, Any]:
    layers = _config_layers_mapping(value)
    candidates: list[Any] = []
    if layers:
        intent_config = _mapping_dict(layers.get("intent_config"))
        execution_config = _mapping_dict(layers.get("execution_config"))
        candidates.extend(
            [
                intent_config.get("continuity_link"),
                intent_config.get("continuity"),
                execution_config.get("continuity_link"),
                execution_config.get("continuity"),
            ]
        )
        metadata = execution_config.get("metadata")
        if isinstance(metadata, Mapping):
            candidates.append(metadata.get("continuity"))
    else:
        data = _mapping_dict(value)
        candidates.extend(
            [
                data.get("continuity_link"),
                data.get("continuity"),
            ]
        )
        metadata = data.get("metadata")
        if isinstance(metadata, Mapping):
            candidates.append(metadata.get("continuity"))

    for candidate in candidates:
        if isinstance(candidate, Mapping) and candidate:
            return _mapping_dict(candidate)
    return {}


def extract_plan_origin_linkage(value: Any) -> dict[str, Any]:
    layers = _config_layers_mapping(value)
    candidates: list[Any] = []
    if layers:
        intent_config = _mapping_dict(layers.get("intent_config"))
        execution_config = _mapping_dict(layers.get("execution_config"))
        candidates.extend(
            [
                intent_config.get("plan_origin"),
                intent_config.get("story_plan"),
                execution_config.get("plan_origin"),
                execution_config.get("story_plan"),
            ]
        )
        metadata = execution_config.get("metadata")
        if isinstance(metadata, Mapping):
            candidates.append(metadata.get("plan_origin"))
    else:
        data = _mapping_dict(value)
        candidates.extend([data.get("plan_origin"), data.get("story_plan")])
        metadata = data.get("metadata")
        if isinstance(metadata, Mapping):
            candidates.append(metadata.get("plan_origin"))

    for candidate in candidates:
        if isinstance(candidate, Mapping) and candidate:
            return _mapping_dict(candidate)
    return {}


def canonicalize_backend_options(
    value: Any,
    *,
    execution_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    layers = _config_layers_mapping(value)
    if layers:
        data = _mapping_dict(layers.get("backend_options"))
    else:
        data = _mapping_dict(value)
        if "backend_options" in data and isinstance(data.get("backend_options"), Mapping):
            data = _mapping_dict(data.get("backend_options"))
    if data:
        return data
    return derive_backend_options(execution_config)


@dataclass(frozen=True, slots=True)
class CanonicalConfigLayers:
    intent_config: dict[str, Any] = field(default_factory=dict)
    execution_config: dict[str, Any] = field(default_factory=dict)
    backend_options: dict[str, Any] = field(default_factory=dict)
    schema: str = CONFIG_CONTRACT_SCHEMA_V26
    intent_artifact_schema: str = INTENT_ARTIFACT_SCHEMA_V1
    intent_artifact_version: str = INTENT_ARTIFACT_VERSION_V1
    intent_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "intent_config": _mapping_dict(self.intent_config),
            "execution_config": _mapping_dict(self.execution_config),
            "backend_options": _mapping_dict(self.backend_options),
            "intent_artifact_schema": self.intent_artifact_schema,
            "intent_artifact_version": self.intent_artifact_version,
            "intent_hash": self.intent_hash or compute_intent_hash(self.intent_config),
        }


def build_config_layers(
    *,
    intent_config: Any = None,
    execution_config: Any = None,
    backend_options: Any = None,
) -> CanonicalConfigLayers:
    normalized_intent = canonicalize_intent_config(intent_config)
    execution = extract_execution_config(execution_config)
    normalized_backend_options = canonicalize_backend_options(
        backend_options,
        execution_config=execution,
    )
    return CanonicalConfigLayers(
        intent_config=normalized_intent,
        execution_config=execution,
        backend_options=normalized_backend_options,
        intent_hash=compute_intent_hash(normalized_intent),
    )


def attach_config_layers(
    payload: Mapping[str, Any] | None,
    *,
    intent_config: Any = None,
    execution_config: Any = None,
    backend_options: Any = None,
) -> dict[str, Any]:
    result = _mapping_dict(payload)
    layers = build_config_layers(
        intent_config=intent_config if intent_config is not None else payload,
        execution_config=execution_config if execution_config is not None else payload,
        backend_options=backend_options,
    )
    result["config_schema"] = CONFIG_CONTRACT_SCHEMA_V26
    result["config_layers"] = layers.to_dict()
    return result


__all__ = [
    "CONFIG_CONTRACT_SCHEMA_V26",
    "CanonicalConfigLayers",
    "attach_config_layers",
    "build_config_layers",
    "canonicalize_backend_options",
    "canonicalize_intent_config",
    "derive_backend_options",
    "extract_adaptive_refinement_intent",
    "extract_secondary_motion_intent",
    "extract_continuity_linkage",
    "extract_plan_origin_linkage",
    "extract_execution_config",
    "is_layered_config",
    "validate_train_lora_execution_config",
    "validate_svd_native_execution_config",
]
