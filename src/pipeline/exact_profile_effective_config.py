"""Effective-configuration preparation for the generic (non-PromptPack) NJR builder (PR-IMG-MODELS-159).

The PromptPack compiler adapts structured intent and composes global positive terms itself. The generic builder has only a
merged configuration and one prompt string, so this module gives it the same normalization and global-term composition
for an exact Z-Image selection (the terms use the shared prose rules; the manual prompt itself is validated, not adapted): inherited values the profile owns (sampling, CLIP skip, VAE, prompt optimizer, global terms) are
replaced through the one profile projection, and enabled stored global positive terms are composed in front of the prompt
with the executor's own merge rule so neither the executor nor the backend applies them again. Unresolved inline syntax and
every genuine envelope conflict are left for the profile validator, which still refuses them.

Pure over the config copy it is given. Every other model is returned untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.image_backends.model_policy import normalize_profile_owned_values
from src.pipeline.global_prompt_policy import (
    GLOBAL_NEGATIVE_STAGE_FLAGS,
    GLOBAL_POSITIVE_STAGE_FLAG,
    has_frozen_global_prompt_policy,
)
from src.utils.negative_helpers_v2 import merge_global_positive

EFFECTIVE_CONFIGURATION_CONTRACT = "effective_configuration/1"


@dataclass(frozen=True, slots=True)
class EffectiveProfileConfig:
    config: dict[str, Any]
    #: Content-free records of inherited profile-owned values that were replaced.
    normalizations: tuple[dict[str, Any], ...] = ()
    #: ``"composed"``, ``"not_applied"`` (stored terms, disabled) or ``""``.
    global_positive: str = ""
    #: ``"omitted"`` only when stored global negative terms would have applied; disabled terms make no claim.
    global_negative: str = ""
    #: Content-free shared-adaptation operations (weighted/BREAK rewrites of the composed terms), in the same
    #: ``{code, scope, effect, details}`` vocabulary as ``prompt_adaptation`` manifests.
    operations: tuple[dict[str, Any], ...] = ()

    def evidence(self) -> dict[str, Any] | None:
        """Frozen, content-free provenance, or ``None`` when nothing was adapted."""

        if not (self.normalizations or self.global_positive or self.global_negative or self.operations):
            return None
        return {
            "contract": EFFECTIVE_CONFIGURATION_CONTRACT,
            "normalized": [dict(change) for change in self.normalizations],
            "global_positive": self.global_positive,
            "global_negative": self.global_negative,
            "operations": [dict(operation) for operation in self.operations],
        }


def _selected_model(config: dict[str, Any]) -> str | None:
    for section in (config.get("txt2img"), config):
        if isinstance(section, dict):
            for key in ("model", "model_name", "base_model", "sd_model_checkpoint"):
                value = str(section.get(key) or "").strip()
                if value:
                    return value
    return None


def prepare_effective_config(config: dict[str, Any]) -> EffectiveProfileConfig:
    """Prepare one merged generic configuration for its exact profile (in place on the supplied copy)."""

    from src.image_backends.forge_zimage_profile import zimage_selected

    if not zimage_selected(config):
        return EffectiveProfileConfig(config)
    status = ""
    if has_frozen_global_prompt_policy(config):
        terms = str(config.get("global_positive_prompt") or "").strip()
        enabled = bool((config.get("pipeline") or {}).get(GLOBAL_POSITIVE_STAGE_FLAG, False))
        if terms and enabled:
            status = "composed"
        elif terms:
            status = "not_applied"
    else:
        terms, enabled = "", False
    negative_status = ""
    if has_frozen_global_prompt_policy(config):
        pipeline = config.get("pipeline") or {}
        applies = bool(pipeline.get(GLOBAL_NEGATIVE_STAGE_FLAGS[0], True))
        if str(config.get("global_negative_prompt") or "").strip() and applies:
            negative_status = "omitted"
    changes: list[dict[str, Any]] = []
    operations: tuple[dict[str, Any], ...] = ()
    sections = [item for item in (config, config.get("txt2img")) if isinstance(item, dict)]
    prompts = [(section, section.get("prompt")) for section in sections if "prompt" in section]
    normalize_profile_owned_values(config, changes)
    for section, prompt in prompts:  # the projection blanks prompt channels; here the prompt is the real executable text
        section["prompt"] = prompt
    if status == "composed":
        from src.image_backends.model_policy import resolve_model_policy
        from src.prompting.prompt_adaptation import PromptAdaptationInput, adapt_prompt_for_target

        # The terms follow the same shared prose rules (weighted syntax, BREAK) as in the PromptPack compiler.
        policy = resolve_model_policy(_selected_model(config))
        plan = adapt_prompt_for_target(policy, PromptAdaptationInput(positive_text=terms))
        terms = plan.positive_text.strip()
        operations = tuple(operation.to_dict() for operation in plan.operations)
        for section, _prompt in prompts:
            if str(section.get("prompt") or "").strip():
                section["prompt"] = merge_global_positive(section["prompt"], terms)[1]
    return EffectiveProfileConfig(config, tuple(changes), status, negative_status, operations)


__all__ = ["EFFECTIVE_CONFIGURATION_CONTRACT", "EffectiveProfileConfig", "prepare_effective_config"]
