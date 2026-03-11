from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageCapability:
    stage: str
    display_name: str
    requires_input_image: bool
    allowed_variables: tuple[str, ...]


STAGE_CAPABILITIES: dict[str, StageCapability] = {
    "txt2img": StageCapability(
        stage="txt2img",
        display_name="txt2img",
        requires_input_image=False,
        allowed_variables=(
            "CFG Scale",
            "Steps",
            "Sampler",
            "Scheduler",
            "Model",
            "VAE",
            "LoRA Strength",
        ),
    ),
    "img2img": StageCapability(
        stage="img2img",
        display_name="img2img",
        requires_input_image=True,
        allowed_variables=(
            "CFG Scale",
            "Steps",
            "Sampler",
            "Scheduler",
            "Model",
            "VAE",
            "LoRA Strength",
            "Denoise Strength",
        ),
    ),
    "adetailer": StageCapability(
        stage="adetailer",
        display_name="ADetailer",
        requires_input_image=True,
        allowed_variables=(
            "CFG Scale",
            "Steps",
            "Sampler",
            "Scheduler",
            "Model",
            "VAE",
            "Denoise Strength",
        ),
    ),
    "upscale": StageCapability(
        stage="upscale",
        display_name="Upscale",
        requires_input_image=True,
        allowed_variables=(
            "Upscale Factor",
            "Model",
            "VAE",
        ),
    ),
}


def get_stage_capability(stage_name: str | None) -> StageCapability:
    stage = str(stage_name or "txt2img").strip().lower() or "txt2img"
    return STAGE_CAPABILITIES.get(stage, STAGE_CAPABILITIES["txt2img"])


def list_supported_stages() -> list[str]:
    return list(STAGE_CAPABILITIES.keys())


def get_variables_for_stage(stage_name: str | None) -> list[str]:
    capability = get_stage_capability(stage_name)
    return list(capability.allowed_variables)
