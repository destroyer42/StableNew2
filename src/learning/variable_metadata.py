"""Variable metadata registry for learning experiments.

PR-LEARN-020: Defines testable variables and their characteristics.
"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class VariableMetadata:
    """Metadata describing a testable variable."""

    name: str  # Internal name (e.g., "cfg_scale")
    display_name: str  # UI display name (e.g., "CFG Scale")
    value_type: Literal["numeric", "discrete", "resource", "composite"]
    config_path: str  # Dot-notation path in config (e.g., "txt2img.cfg_scale")
    ui_component: Literal["range", "checklist", "lora_composite"]
    resource_key: str | None = None  # Key in AppStateV2.resources (e.g., "samplers")
    constraints: dict[str, Any] = field(default_factory=dict)  # Type-specific constraints


# Variable registry - defines all testable variables
LEARNING_VARIABLES: dict[str, VariableMetadata] = {
    "cfg_scale": VariableMetadata(
        name="cfg_scale",
        display_name="CFG Scale",
        value_type="numeric",
        config_path="txt2img.cfg_scale",
        ui_component="range",
        constraints={
            "min": 1.0,
            "max": 30.0,
            "step": 0.5,
            "default_start": 5.0,
            "default_end": 10.0,
        },
    ),
    "steps": VariableMetadata(
        name="steps",
        display_name="Steps",
        value_type="numeric",
        config_path="txt2img.steps",
        ui_component="range",
        constraints={
            "min": 1,
            "max": 150,
            "step": 1,
            "default_start": 20,
            "default_end": 50,
        },
    ),
    "sampler": VariableMetadata(
        name="sampler",
        display_name="Sampler",
        value_type="discrete",
        config_path="txt2img.sampler_name",
        ui_component="checklist",
        resource_key="samplers",
        constraints={},
    ),
    "scheduler": VariableMetadata(
        name="scheduler",
        display_name="Scheduler",
        value_type="discrete",
        config_path="txt2img.scheduler",
        ui_component="checklist",
        resource_key="schedulers",
        constraints={},
    ),
    "denoise_strength": VariableMetadata(
        name="denoise_strength",
        display_name="Denoise Strength",
        value_type="numeric",
        config_path="txt2img.denoising_strength",
        ui_component="range",
        constraints={
            "min": 0.0,
            "max": 1.0,
            "step": 0.05,
            "default_start": 0.5,
            "default_end": 0.9,
        },
    ),
    "upscale_factor": VariableMetadata(
        name="upscale_factor",
        display_name="Upscale Factor",
        value_type="numeric",
        config_path="upscale.upscale_factor",
        ui_component="range",
        constraints={
            "min": 1.0,
            "max": 4.0,
            "step": 0.25,
            "default_start": 2.0,
            "default_end": 4.0,
        },
    ),
    # PR-LEARN-021: Resource variables
    "model": VariableMetadata(
        name="model",
        display_name="Model",
        value_type="resource",
        config_path="txt2img.model",
        ui_component="checklist",
        resource_key="models",
        constraints={"supports_filter": True, "display_metadata": True},
    ),
    "vae": VariableMetadata(
        name="vae",
        display_name="VAE",
        value_type="resource",
        config_path="txt2img.vae",
        ui_component="checklist",
        resource_key="vaes",
        constraints={"supports_filter": True, "display_metadata": False},
    ),
    # PR-LEARN-022: Composite LoRA variable
    "lora_strength": VariableMetadata(
        name="lora_strength",
        display_name="LoRA Strength",
        value_type="composite",
        config_path="lora_override",  # Special handling in controller
        ui_component="lora_composite",
        constraints={
            "lora_source": "stage_card",
            "min_strength": 0.0,
            "max_strength": 2.0,
            "default_step": 0.1,
            "supports_comparison_mode": True,  # Can test different LoRAs
        },
    ),
}


def get_variable_metadata(variable_display_name: str) -> VariableMetadata | None:
    """Look up metadata by display name.

    Args:
        variable_display_name: Display name like "CFG Scale"

    Returns:
        VariableMetadata if found, None otherwise
    """
    for meta in LEARNING_VARIABLES.values():
        if meta.display_name == variable_display_name:
            return meta
    return None


def get_all_variable_names() -> list[str]:
    """Get list of all variable display names for UI dropdown.

    Returns:
        Sorted list of display names
    """
    names = [meta.display_name for meta in LEARNING_VARIABLES.values()]
    return sorted(names)


def get_variable_by_internal_name(internal_name: str) -> VariableMetadata | None:
    """Look up metadata by internal name.

    Args:
        internal_name: Internal name like "cfg_scale"

    Returns:
        VariableMetadata if found, None otherwise
    """
    return LEARNING_VARIABLES.get(internal_name)
