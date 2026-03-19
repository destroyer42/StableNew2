from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


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
    "hires_fix",
    "refiner",
    "randomization",
    "aesthetic",
    "metadata",
}

_INTENT_TOP_LEVEL_KEYS = (
    "run_mode",
    "source",
    "prompt_source",
    "prompt_pack_id",
    "config_snapshot_id",
    "requested_job_label",
    "selected_row_ids",
    "tags",
    "pipeline_state_snapshot",
)

_KNOWN_VIDEO_BACKEND_STAGES = ("animatediff", "svd_native")


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
        if key in data and data[key] not in (None, ""):
            normalized[key] = deepcopy(data[key])
    return normalized


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
    if video_options:
        return {"video": video_options}
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "intent_config": _mapping_dict(self.intent_config),
            "execution_config": _mapping_dict(self.execution_config),
            "backend_options": _mapping_dict(self.backend_options),
        }


def build_config_layers(
    *,
    intent_config: Any = None,
    execution_config: Any = None,
    backend_options: Any = None,
) -> CanonicalConfigLayers:
    execution = extract_execution_config(execution_config)
    normalized_backend_options = canonicalize_backend_options(
        backend_options,
        execution_config=execution,
    )
    return CanonicalConfigLayers(
        intent_config=canonicalize_intent_config(intent_config),
        execution_config=execution,
        backend_options=normalized_backend_options,
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
    "extract_execution_config",
    "is_layered_config",
]
