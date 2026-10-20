"""Capability projection for bounded Review mask edits; ModelPolicy remains authoritative."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.image_backends.image_backend_types import resolve_image_backend_id
from src.image_backends.model_policy import FamilyLookup, RegistryFamilyLookup, resolve_model_policy


def require_mask_target(
    model: str, backend_options: Mapping[str, Any], *, family_lookup: FamilyLookup | None = None
) -> None:
    policy = resolve_model_policy(
        model, family_lookup=family_lookup if family_lookup is not None else RegistryFamilyLookup()
    )
    if resolve_image_backend_id(backend_options) != "forge_webui" or policy.policy_id != "sdxl":
        raise ValueError(
            "Masked Review edits require Forge and a registry-resolved SDXL base checkpoint; "
            "this target is unsupported or its family is unverified. Nothing was dispatched."
        )


def validate_frozen_mask_target(
    model: str, backend_options: Mapping[str, Any], config: Mapping[str, Any], stages: list[str]
) -> None:
    stage = config.get("img2img", config)
    if isinstance(stage, Mapping):
        stage = stage.get("extra", stage)
    if isinstance(stage, Mapping) and "image_edit_inputs" in stage:
        require_mask_target(model, backend_options)
        if stages != ["img2img"]:
            raise ValueError("Frozen Review mask edits support only one img2img stage")
