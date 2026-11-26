"""Capability projection for bounded Review mask edits; ModelPolicy remains authoritative."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.image_backends.image_backend_types import resolve_image_backend_id
from src.image_backends.model_policy import FamilyLookup, RegistryFamilyLookup, resolve_model_policy
from src.image_backends.sdxl_target import (
    OP_MASKED_INPAINT,
    OP_OUTPAINT,
    SdxlTarget,
    assess_sdxl_target,
)


def require_mask_target(
    model: str,
    backend_options: Mapping[str, Any],
    *,
    family_lookup: FamilyLookup | None = None,
    operation: str = OP_MASKED_INPAINT,
) -> SdxlTarget:
    """Raise for a real block (not Forge; positively another family); else the N1b target.

    An unclassified checkpoint is a warning (``target.warnings``) that Preview shows and Queue records, never a
    refusal (owner decision N1b); observed masked edits of the same checkpoint on Forge outrank the registry.
    """
    from src.history.observed_execution import observed_runs_lookup

    if resolve_image_backend_id(backend_options) != "forge_webui":
        raise ValueError(
            "Masked Review edits require Forge (outpaint too); select the Forge backend. Nothing was dispatched."
        )
    policy = resolve_model_policy(
        model, family_lookup=family_lookup if family_lookup is not None else RegistryFamilyLookup()
    )
    target = assess_sdxl_target(
        policy, model=model, operation=operation, backend_id="forge_webui",
        feature="outpaint" if operation == OP_OUTPAINT else "masked Review edits",
        observed=observed_runs_lookup(),
    )  # fmt: skip
    if not target.allowed:
        raise ValueError(f"{target.block} Nothing was dispatched.")
    return target


def validate_frozen_mask_target(
    model: str, backend_options: Mapping[str, Any], config: Mapping[str, Any], stages: list[str]
) -> None:
    stage = config.get("img2img", config)
    if isinstance(stage, Mapping):
        stage = stage.get("extra", stage)
    if isinstance(stage, Mapping) and "image_edit_inputs" in stage:
        outpaint = stage.get("edit_operation") == "outpaint" or (
            isinstance(config.get("img2img"), Mapping)
            and config["img2img"].get("edit_operation") == "outpaint"
        )
        require_mask_target(
            model, backend_options, operation=OP_OUTPAINT if outpaint else OP_MASKED_INPAINT
        )
        if stages != ["img2img"]:
            raise ValueError("Frozen Review mask edits support only one img2img stage")
