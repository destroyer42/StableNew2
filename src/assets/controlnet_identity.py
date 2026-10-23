"""Documented ControlNet model identities and their modality (PR-IMG-CNET-210/220), below both its consumers.

Production dispatch admission (``image_backends.forge_controlnet_units``) and the offline readiness projection
(``assets.resource_readiness``) must agree on which model names a unit of each modality may use, so the policy lives here
once and both import it. A name is compatibility guidance, never a claim of weight integrity or quality; no fuzzy alias
is inferred. Architecture evidence (SDXL header) is a separate fact and is passed in, not computed here.
"""

from __future__ import annotations

from src.assets.controlnet_structure import STATUS_SDXL, name_key

# Exact published model identities, separate from SDXL architecture evidence.
# Full Canny/Depth and Thibaud names: https://github.com/Mikubill/sd-webui-controlnet/discussions/2039
# Xinsir: existing PR-IMG-CNET-210 declaration example; no fuzzy aliases are inferred.
MODEL_MODALITIES = {
    "thibaud_xl_openpose": "openpose",
    "xinsir_openpose_sdxl": "openpose",
    "diffusers_xl_canny_full": "canny",
    "diffusers_xl_depth_full": "depth",
}


def model_problem(modality: str, model: str, architecture: str | None) -> str:
    """Why ``model`` cannot serve a ``modality`` unit (empty when admitted)."""

    if architecture != STATUS_SDXL:
        return (
            "ControlNet weight SDXL architecture is missing, ambiguous, unverified or incompatible."
        )
    known = MODEL_MODALITIES.get(name_key(model))
    if known != modality:
        return f"ControlNet model modality is {'unverified' if known is None else known}; cannot admit {modality}. Choose a documented compatible model."
    return ""


__all__ = ["MODEL_MODALITIES", "model_problem"]
