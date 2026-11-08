"""Settings a controlled Learning study refuses, detected in and cleared from the Learning baseline draft only.

A Pipeline copy can carry settings (prompt optimizer, Style Consistency, hires fix, refiner, stage LoRAs, extra
stages...) that a controlled study refuses at Preview but that the baseline editor has no field for. This module names
them per study and turns them off in a copy of the Learning baseline; it never reads or writes the Pipeline and never
decides a refusal itself (each study's own check stays the authority, and the tests hold this detection to it).
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable, Mapping
from typing import Any

PROMPT_OPTIMIZER = "prompt_optimizer"
STYLE = "style_consistency"
HIRES = "hires_fix"
REFINER = "refiner"
STAGE_LORAS = "stage_loras"
EXTRA_STAGES = "extra_stages"
HYPERNETWORK = "hypernetwork"
AESTHETIC = "aesthetic_conditioning"
CONTROLNET = "controlnet"

PROMPT_SLOT = "prompt_slot"
LORA_COMPOSITION = "lora_composition"
EMBEDDING = "embedding_experiment"
MATRIX = "prompt_model_matrix"
GRID = "two_axis_grid"

LABELS: dict[str, str] = {
    PROMPT_OPTIMIZER: "Prompt optimizer",
    STYLE: "Style Consistency",
    HIRES: "Hires fix",
    REFINER: "Refiner",
    STAGE_LORAS: "Stage LoRA settings",
    EXTRA_STAGES: "Extra stages (img2img / ADetailer / upscale)",
    HYPERNETWORK: "Hypernetwork",
    AESTHETIC: "Aesthetic conditioning",
    CONTROLNET: "ControlNet",
}

#: What each study refuses, in display order (Learning sections 3.7 and 3.11-3.14). Hires fix and the refiner are
#: ordinary fixed settings for Prompt Slot, LoRA Composition and Embedding studies, so they are not listed there.
STUDY_EXCLUSIONS: dict[str, tuple[str, ...]] = {
    PROMPT_SLOT: (PROMPT_OPTIMIZER,),
    LORA_COMPOSITION: (PROMPT_OPTIMIZER, STYLE, STAGE_LORAS),
    EMBEDDING: (PROMPT_OPTIMIZER, STYLE),
    MATRIX: (
        PROMPT_OPTIMIZER,
        HIRES,
        REFINER,
        STAGE_LORAS,
        EXTRA_STAGES,
        HYPERNETWORK,
        AESTHETIC,
        CONTROLNET,
    ),
    GRID: (HIRES, REFINER, EXTRA_STAGES, HYPERNETWORK, AESTHETIC, CONTROLNET),
}

_SECONDARY_STAGES = ("img2img", "adetailer", "upscale")
_REFINER_FLAGS = ("use_refiner", "refiner_enabled")


def _section(config: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = config.get(name)
    return value if isinstance(value, Mapping) else {}


def _enabled(value: Any) -> bool:
    return bool(value.get("enabled")) if isinstance(value, Mapping) else bool(value)


def hires_requested(config: Mapping[str, Any]) -> bool:
    """True for hires fix in any spelling the executor or a study reads."""
    return bool(
        _section(config, "txt2img").get("enable_hr")
        or config.get("enable_hr")
        or _section(config, "hires_fix").get("enabled")
    )


def refiner_requested(config: Mapping[str, Any]) -> bool:
    """True for the refiner in any spelling, including ``txt2img.use_refiner`` that the executor honours."""
    base = _section(config, "txt2img")
    return bool(
        any(base.get(flag) or config.get(flag) for flag in _REFINER_FLAGS)
        or _section(config, "refiner").get("enabled")
    )


def _optimizer(config: Mapping[str, Any]) -> bool:
    return any(
        bool(_section(section, "prompt_optimizer").get("enabled"))
        for section in (config, _section(config, "txt2img"))
    )


def _style(config: Mapping[str, Any]) -> bool:
    style = config.get("style_lora")
    return bool(
        isinstance(style, Mapping)
        and style.get("enabled", True)
        and any(style.get(key) for key in ("style_id", "id", "name", "lora_name"))
    )


def _stage_loras(config: Mapping[str, Any]) -> bool:
    base = _section(config, "txt2img")
    return bool(config.get("lora_override") or base.get("lora_strengths") or base.get("loras"))


def _extra_stages(config: Mapping[str, Any]) -> bool:
    pipeline = _section(config, "pipeline")
    return any(
        pipeline.get(f"{stage}_enabled")
        or config.get(f"{stage}_enabled")
        or _section(config, stage).get("enabled")
        for stage in _SECONDARY_STAGES
    )


def _hypernetwork(config: Mapping[str, Any]) -> bool:
    return str(_section(config, "txt2img").get("hypernetwork") or "none").lower() not in {
        "",
        "none",
    }


def _aesthetic_sections(config: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [config, *(_section(config, name) for name in ("txt2img", "pipeline"))]


def _aesthetic(config: Mapping[str, Any]) -> bool:
    for section in _aesthetic_sections(config):
        if _enabled(section.get("aesthetic")):
            return True
        if section.get("aesthetic_enabled") or section.get("aesthetic_gradient_enabled"):
            return True
    return False


def _controlnet_keys(section: Mapping[str, Any]) -> list[str]:
    return [
        str(key)
        for key, value in section.items()
        if "controlnet" in str(key).lower() and _enabled(value)
    ]


def _controlnet(config: Mapping[str, Any]) -> bool:
    return bool(_controlnet_keys(config) or _controlnet_keys(_section(config, "txt2img")))


_DETECTORS: dict[str, Callable[[Mapping[str, Any]], bool]] = {
    PROMPT_OPTIMIZER: _optimizer,
    STYLE: _style,
    HIRES: hires_requested,
    REFINER: refiner_requested,
    STAGE_LORAS: _stage_loras,
    EXTRA_STAGES: _extra_stages,
    HYPERNETWORK: _hypernetwork,
    AESTHETIC: _aesthetic,
    CONTROLNET: _controlnet,
}


def present(config: Mapping[str, Any] | None, study: str) -> list[str]:
    """The refused settings this study would meet in ``config``, in display order (empty for other studies)."""
    if not config:
        return []
    return [key for key in STUDY_EXCLUSIONS.get(study, ()) if _DETECTORS[key](config)]


def describe(keys: Iterable[str]) -> str:
    return ", ".join(LABELS.get(key, key) for key in keys)


def _off(section: Any, *keys: str) -> None:
    if isinstance(section, dict):
        for key in keys:
            if key in section:
                section[key] = False


def _disable_mapping(section: Any, key: str) -> None:
    if isinstance(section, dict) and isinstance(section.get(key), dict):
        section[key]["enabled"] = False


def _clear(config: dict[str, Any], key: str) -> None:
    base = config.get("txt2img")
    if key == PROMPT_OPTIMIZER:
        for section in (config, base):
            _disable_mapping(section, "prompt_optimizer")
    elif key == STYLE:
        _disable_mapping(config, "style_lora")
    elif key == HIRES:
        _off(base, "enable_hr")
        _off(config, "enable_hr")
        _disable_mapping(config, "hires_fix")
    elif key == REFINER:
        for section in (base, config):
            _off(section, *_REFINER_FLAGS)
        _disable_mapping(config, "refiner")
    elif key == STAGE_LORAS:
        config.pop("lora_override", None)
        if isinstance(base, dict):
            base.pop("lora_strengths", None)
            base.pop("loras", None)
    elif key == EXTRA_STAGES:
        pipeline = config.setdefault("pipeline", {})
        for stage in _SECONDARY_STAGES:
            if isinstance(pipeline, dict):
                pipeline[f"{stage}_enabled"] = False
            _off(config, f"{stage}_enabled")
            stage_section = config.get(stage)
            if isinstance(stage_section, dict):
                _off(stage_section, "enabled", f"{stage}_enabled")
    elif key == HYPERNETWORK:
        if isinstance(base, dict):
            base["hypernetwork"] = "None"
    elif key == AESTHETIC:
        for section in (config, base, config.get("pipeline")):
            if not isinstance(section, dict):
                continue
            if isinstance(section.get("aesthetic"), dict):
                section["aesthetic"]["enabled"] = False
            elif section.get("aesthetic"):
                section["aesthetic"] = False
            _off(section, "aesthetic_enabled", "aesthetic_gradient_enabled")
    elif key == CONTROLNET:
        for section in (config, base):
            if not isinstance(section, dict):
                continue
            for name in _controlnet_keys(section):
                if isinstance(section[name], dict):
                    section[name]["enabled"] = False
                else:
                    section.pop(name)


def cleared(config: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    """A deep copy of ``config`` with each named refused setting turned off; every other setting is kept."""
    result: dict[str, Any] = copy.deepcopy(dict(config))
    for key in keys:
        if key not in _DETECTORS:
            raise ValueError(f"Unknown study exclusion: {key}")
        _clear(result, key)
    return result
