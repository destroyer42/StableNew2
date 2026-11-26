"""Multi-unit adapter at the existing PromptPack conditioning compile seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.conditioning.controlnet import FrozenControlNet, FrozenUnit, parse_units
from src.image_backends.openpose_capability import assess_openpose_target
from src.pipeline.openpose_compile import (
    OpenPoseCompileError,
    controlnet_sdxl_target,
    family_source,
)


@dataclass(frozen=True, slots=True)
class CompiledUnits:
    frozen: FrozenControlNet
    target: dict[str, Any]


def compile_units(
    build: Any, raw: Any, *, stage_names: tuple[str, ...], **kwargs: Any
) -> CompiledUnits | None:
    selections = parse_units(raw)
    active = [unit for unit in selections if unit.settings.enabled]
    if not active:
        return None
    if "txt2img" not in stage_names:
        raise OpenPoseCompileError(
            f"{kwargs['label']}: ControlNet requires the base txt2img stage."
        )
    # N1b: an unclassified checkpoint is a warning (shown at Preview, accepted on Queue); observed runs outrank the
    # registry; a positively identified other family and a non-Forge backend stay real blocks.
    sdxl = controlnet_sdxl_target(
        kwargs["policy_for"](kwargs["model_name"]),
        kwargs["model_name"],
        kwargs["backend_id"],
        tuple(unit.modality for unit in active),
    )
    if not sdxl.allowed:
        raise OpenPoseCompileError(f"{kwargs['label']}: {sdxl.block}")
    policy = sdxl.policy
    target = assess_openpose_target(policy, kwargs["backend_id"])
    if not target.executable:
        raise OpenPoseCompileError(f"{kwargs['label']}: {target.message}")
    units = []
    for index, unit in enumerate(active):
        compiled = build.compile_slot(
            unit.settings.to_dict(),
            **{
                **kwargs,
                "label": f"{kwargs['label']} ControlNet unit {index + 1} ({unit.modality})",
            },
        )
        assert compiled is not None
        units.append(FrozenUnit(unit.modality, compiled.frozen))
    return CompiledUnits(
        frozen=FrozenControlNet(tuple(units)),
        target={
            "family": policy.family,
            "family_source": family_source(policy),
            "backend_id": kwargs["backend_id"],
            "stage": "txt2img",
            **(
                {"policy_warnings": [item.as_dict() for item in sdxl.warnings]}
                if sdxl.warnings
                else {}
            ),
        },
    )
