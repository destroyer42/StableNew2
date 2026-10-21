"""Multi-unit adapter at the existing PromptPack conditioning compile seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.conditioning.controlnet import FrozenControlNet, FrozenUnit, parse_units
from src.image_backends.model_policy import EVIDENCE_REGISTRY
from src.image_backends.openpose_capability import assess_openpose_target
from src.pipeline.openpose_compile import OpenPoseCompileError


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
    policy = kwargs["policy_for"](kwargs["model_name"])
    target = assess_openpose_target(policy, kwargs["backend_id"])
    if policy.evidence != EVIDENCE_REGISTRY or not target.executable:
        raise OpenPoseCompileError(
            f"{kwargs['label']}: ControlNet requires a registry-verified SDXL checkpoint on Forge. {target.message}"
        )
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
            "family_source": "registry_snapshot",
            "backend_id": kwargs["backend_id"],
            "stage": "txt2img",
        },
    )
