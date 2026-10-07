"""Pure stage/model intersection. Canonical ModelPolicy owns every capability fact."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from src.image_backends.model_policy import EVIDENCE_REGISTRY, ControlMode, ModelPolicy
from src.image_backends.model_policy_lora import assess_lora_selection
from src.learning.stage_capabilities import STAGE_CAPABILITIES
from src.learning.variable_metadata import (
    LEARNING_VARIABLES,
    get_variable_by_internal_name,
    get_variable_metadata,
)


def variable_name(value: str) -> str:
    meta = get_variable_metadata(value) or get_variable_by_internal_name(value)
    return meta.name if meta else ""


def policy_context(policy: ModelPolicy, model: str, stage: str) -> dict[str, Any]:
    """Stable, path-free identity and policy contract; no registry internals."""
    import json

    context = {
        "policy_id": policy.policy_id,
        "family": policy.family,
        "evidence": policy.evidence,
        "profile_ref": dict(policy.profile_ref) if policy.profile_ref else None,
        "selected_model": os.path.basename(str(model).replace("\\", "/")),
        "stage": stage,
        "contract": {
            "allowed_backends": list(policy.allowed_backends),
            "required_backend": policy.required_backend,
            "prompt_dialect": policy.prompt_dialect,
            "stages": list(policy.stages),
            "modes": list(policy.modes),
            "controls": {
                name: {
                    "mode": policy.control(name, stage).mode.value,
                    "value": policy.control(name, stage).value,
                    "allowed": list(policy.control(name, stage).allowed),
                }
                for name in (*LEARNING_VARIABLES, "geometry")
            },
            "features": {
                name: {
                    "support": feature.support.value,
                    "limit": feature.limit,
                    "compatibility_policy": feature.compatibility_policy,
                    "stages": list(feature.stages),
                }
                for name, feature in policy.features.items()
            },
        },
    }
    return json.loads(json.dumps(context, sort_keys=True))


def compatible_context(left: dict, right: dict) -> bool:
    """Control shape alone cannot upgrade unknown evidence to policy compatibility."""
    if not left or not right:
        return False
    if not left.get("profile_ref") and (
        left.get("evidence") != EVIDENCE_REGISTRY or right.get("evidence") != EVIDENCE_REGISTRY
    ):
        return False
    return all(
        left.get(key) == right.get(key)
        for key in ("policy_id", "family", "evidence", "profile_ref", "stage", "contract")
    )


@dataclass(frozen=True, slots=True)
class LearningCapabilities:
    context_json: str
    stage_supported: bool
    variables: tuple[str, ...]
    parameters: tuple[str, ...]
    unavailable: tuple[tuple[str, str], ...]
    lora_candidates: tuple[str, ...]
    target: str
    guidance: str

    def require(self, variable: str) -> None:
        name = variable_name(variable)
        if not self.stage_supported or name not in self.parameters:
            reason = dict(self.unavailable).get(name, "stage_unsupported")
            raise ValueError(f"Learning variable {variable} unavailable: {reason}")


def project_learning_capabilities(
    policy: ModelPolicy,
    model: str,
    stage: str,
    *,
    selected_loras=(),
    lora_resolver=None,
    style_lora_pending: bool = False,
) -> LearningCapabilities:
    import json

    stage_supported = stage in STAGE_CAPABILITIES and stage in policy.stages
    if stage in {"adetailer", "upscale"}:
        stage_supported = stage_supported and policy.feature(stage, stage).supported
    variables, parameters, unavailable, candidates = [], [], [], []
    feature = policy.feature("lora", stage)
    if feature.supported and not style_lora_pending:
        assessment = assess_lora_selection(policy, selected_loras, lora_resolver)
        if not assessment.blocked and (not feature.compatibility_policy or assessment.exact):
            candidates.extend(name for name, _weight in selected_loras)
    for display in STAGE_CAPABILITIES.get(stage, STAGE_CAPABILITIES["txt2img"]).allowed_variables:
        name = variable_name(display)
        control = policy.control(name, stage)
        reason = ""
        if not stage_supported:
            reason = "stage_unsupported"
        elif control.mode is not ControlMode.CONFIGURABLE:
            reason = control.mode.value
        elif control.allowed:
            reason = "restricted_control"
        elif name == "lora_strength":
            if not feature.supported:
                reason = "lora_" + feature.support.value
            elif (feature.compatibility_policy or policy.qualified) and not candidates:
                reason = "lora_admission_required"
        elif name == "model" and (policy.qualified or policy.evidence != EVIDENCE_REGISTRY):
            reason = "model_policy_comparison_unavailable"
        if reason:
            unavailable.append((name, reason))
        else:
            variables.append(display)
            parameters.append(name)
    suffix = f" — profile v{policy.profile_ref['version']}" if policy.profile_ref else f" — {model}"
    return LearningCapabilities(
        json.dumps(policy_context(policy, model, stage), sort_keys=True),
        stage_supported,
        tuple(variables),
        tuple(parameters),
        tuple(unavailable),
        tuple(dict.fromkeys(candidates)),
        "Learning Target: " + policy.display_name + suffix,
        policy.note or ("Capabilities unverified" if policy.evidence != EVIDENCE_REGISTRY else ""),
    )
