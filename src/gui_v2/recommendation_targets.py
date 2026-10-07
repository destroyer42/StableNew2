"""Toolkit-neutral mapping from Learning parameters to executable operator controls."""

from __future__ import annotations

from typing import Any

_BASE = "txt2img_card"  # aliases the shared Base Generation variables
_COMMON = {"cfg_scale": "cfg_var", "steps": "steps_var", "sampler": "sampler_var"}
_TARGETS = {
    "txt2img": {
        **{p: (_BASE, v) for p, v in _COMMON.items()},
        "scheduler": (_BASE, "scheduler_var"),
        "model": (_BASE, "model_var"),
        "vae": (_BASE, "vae_var"),
    },
    # PipelineRunner pins secondary stages to the NJR base checkpoint/VAE.
    # Img2img has no local scheduler selector; its scheduler is inherited.
    "img2img": {
        **{p: ("img2img_card", v) for p, v in _COMMON.items()},
        "scheduler": (_BASE, "scheduler_var"),
        "model": (_BASE, "model_var"),
        "vae": (_BASE, "vae_var"),
        "denoise_strength": ("img2img_card", "denoise_var"),
    },
    "adetailer": {
        **{p: ("adetailer_card", v) for p, v in _COMMON.items()},
        "scheduler": ("adetailer_card", "scheduler_var"),
        "model": ("adetailer_card", "stage_model_override_var"),
        "vae": (_BASE, "vae_var"),
        "denoise_strength": ("adetailer_card", "denoise_var"),
    },
    "upscale": {
        "upscale_factor": ("upscale_card", "factor_var"),
        "model": (_BASE, "model_var"),
        "vae": (_BASE, "vae_var"),
    },
}
_ALIASES = {
    "cfg": "cfg_scale",
    "model_name": "model",
    "sampler_name": "sampler",
    "denoising_strength": "denoise_strength",
    "adetailer_cfg": "cfg_scale",
    "adetailer_steps": "steps",
    "adetailer_denoise": "denoise_strength",
}


def recommendation_target(stage: str, parameter: str) -> tuple[str, str] | None:
    name = str(parameter).lower().replace(" ", "_")
    return _TARGETS.get(stage, {}).get(_ALIASES.get(name, name))


def checkpoint_for_stage(cards: Any, stage: str) -> str | None:
    """Resolve checkpoint selection, never confusing ADetailer's detector with it."""
    if stage == "adetailer":
        card = getattr(cards, "adetailer_card", None)
        override = getattr(card, "stage_model_override_var", None)
        value = override.get() if override is not None else None
        if isinstance(value, str) and value.strip() and value.strip() != "Inherit Base Generation":
            return value
    base = getattr(cards, _BASE, None)
    variable = getattr(base, "model_var", None)
    value = variable.get() if variable is not None else None
    return value if isinstance(value, str) else None


def prepare_recommendation_patch(cards: Any, stage: str, recommendations: list) -> list:
    """Resolve every target and read every old value before any variable is set."""
    patch = []
    for rec in recommendations:
        parameter = (
            rec.parameter_name if hasattr(rec, "parameter_name") else rec.get("parameter", "")
        )
        value = rec.recommended_value if hasattr(rec, "recommended_value") else rec.get("value")
        target = recommendation_target(stage, parameter)
        if target is None:
            raise ValueError(f"No faithful {stage} operator control for {parameter}")
        card = getattr(cards, target[0], None)
        variable = getattr(card, target[1], None)
        if not callable(getattr(variable, "get", None)) or not callable(
            getattr(variable, "set", None)
        ):
            raise ValueError(f"Missing operator control: {target}")
        patch.append((target, variable, value, variable.get()))
    return patch
