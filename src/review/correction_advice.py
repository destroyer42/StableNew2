"""Project guided Review eligibility through the existing model and operation contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.image_backends.backend_capabilities import capabilities_for
from src.image_backends.image_backend_types import (
    FORGE_IMAGE_BACKEND_ID,
    normalize_image_backend_options,
    resolve_image_backend_id,
)
from src.image_backends.model_policy import (
    FamilyLookup,
    ModelPolicy,
    RegistryFamilyLookup,
    policy_for_model_profile_reference,
    resolve_model_policy,
)
from src.image_backends.operation_compatibility import OperationRequest, assess_operation
from src.pipeline.adetailer_contract import split_detectors
from src.pipeline.image_edit_inputs import KEY as FROZEN_EDIT_KEY
from src.pipeline.reprocess_builder import ReprocessJobBuilder
from src.review.findings import (
    Action,
    Advisory,
    Category,
    Confirmation,
    Finding,
    FindingSource,
    Region,
)


@dataclass(frozen=True, slots=True)
class CorrectionTarget:
    model: str
    backend: str
    policy: ModelPolicy
    stages: tuple[str, ...]
    width: int | None
    height: int | None
    inherited_mask: bool


@dataclass(frozen=True, slots=True)
class ReviewResources:
    models: frozenset[str]
    detectors: tuple[str, ...]
    backend: str


@dataclass(frozen=True, slots=True)
class GuidedReprocess:
    """Operator-authored stage and target for one existing Review batch Preview."""

    source: FindingSource
    action: Action
    category: Category
    region: Region | None
    model: str
    backend: str
    detector: str = ""
    resources: ReviewResources | None = None

    @property
    def stage(self) -> str:
        return "adetailer" if self.action in (Action.FACE, Action.HANDS) else "img2img"


def resolve_target(
    baseline: Mapping[str, Any],
    fallback: dict[str, Any],
    stage: str,
    *,
    family_lookup: FamilyLookup | None = None,
) -> CorrectionTarget:
    config = ReprocessJobBuilder._merge_nested_dicts(fallback, dict(baseline.get("config") or {}))
    stage_config = config.get(stage) or {}
    model = str(
        baseline.get("model")
        or config.get("model")
        or (stage_config.get("model") if stage == "img2img" else "")
        or config.get("txt2img", {}).get("model")
        or ""
    )
    options = normalize_image_backend_options(config.get("backend_options"), model_name=model)
    backend = resolve_image_backend_id(options)
    try:
        stages = capabilities_for(backend).stage_types
    except KeyError:
        stages = ()
    lookup = family_lookup if family_lookup is not None else RegistryFamilyLookup()
    policy = policy_for_model_profile_reference(options) or resolve_model_policy(
        model, family_lookup=lookup
    )
    width, height = stage_config.get("width"), stage_config.get("height")
    inherited_mask = stage == "img2img" and any(
        settings.get(key)
        for settings in (config, stage_config, stage_config.get("extra") or {})
        if isinstance(settings, Mapping)
        for key in ("mask_image_path", "mask_path", FROZEN_EDIT_KEY)
    )
    return CorrectionTarget(
        model,
        backend,
        policy,
        stages,
        width if type(width) is int else None,
        height if type(height) is int else None,
        inherited_mask,
    )


def detectors_for(action: Action, resources: ReviewResources) -> tuple[str, ...]:
    faces, hands = split_detectors(resources.detectors)
    return tuple(faces if action is Action.FACE else hands if action is Action.HANDS else ())


def target_refusal(
    action: Action,
    target: CorrectionTarget,
    resources: ReviewResources,
    *,
    source_size: tuple[int, int] | None = None,
) -> str:
    """Use supplied resource and registry evidence without probing or changing a backend."""

    stage = "adetailer" if action in (Action.FACE, Action.HANDS) else "img2img"
    size = (source_size or (None, None)) if action is Action.MASK else (target.width, target.height)
    assessment = assess_operation(
        target.policy, OperationRequest((stage,), target.backend, *size, input_image_count=1)
    )
    if not assessment.ready:
        return assessment.explain()
    if target.backend != resources.backend or stage not in target.stages:
        return "The recorded target backend is unavailable for this stage."
    if not target.model or target.model not in resources.models:
        return "The target checkpoint is unavailable in the current model inventory."
    if action is Action.MASK:
        if target.backend != FORGE_IMAGE_BACKEND_ID or target.policy.policy_id != "sdxl":
            return "Masked Review edits require Forge and a registry-resolved SDXL base checkpoint."
    elif action in (Action.FACE, Action.HANDS):
        if target.policy.policy_id != "sdxl":
            return f"Guided ADetailer requires a registry-resolved SDXL base checkpoint ({target.policy.display_name})."
        if not detectors_for(action, resources):
            return "The current backend inventory contains no detector for this pass."
    elif target.policy.policy_id != "sdxl":
        return (
            f"Guided img2img requires a verified SDXL base target ({target.policy.display_name})."
        )
    if action is Action.REPROCESS and target.inherited_mask:
        return "The source settings include a mask. Use Edit Mask to approve a new mask."
    return ""


def recommend(
    finding: Finding,
    targets: Mapping[str, CorrectionTarget],
    resources: ReviewResources,
) -> tuple[Advisory, ...]:
    if finding.confirmation is not Confirmation.CONFIRMED:
        return (
            Advisory(
                Action.INSPECT, False, "Confirm a visible issue before opening a correction draft."
            ),
        )
    actions: list[Action] = [Action.MASK] if finding.region is not None else []
    if finding.category is Category.FACE:
        actions.append(Action.FACE)
    elif finding.category is Category.HANDS:
        actions.append(Action.HANDS)
    else:
        actions.append(Action.REPROCESS)
    result = []
    for action in actions:
        stage = "adetailer" if action in (Action.FACE, Action.HANDS) else "img2img"
        reason = target_refusal(
            action, targets[stage], resources, source_size=finding.source.identity.size
        )
        if not reason:
            reason = {
                Action.MASK: "Paint or refine the approved mask in Edit Mask.",
                Action.FACE: "The detector may affect any face. Use a mask for one region.",
                Action.HANDS: "The detector may affect any hand. Use a mask for one region.",
                Action.REPROCESS: "Img2img reprocesses the whole image.",
            }[action]
            result.append(Advisory(action, True, reason))
        else:
            result.append(Advisory(action, False, reason))
    if not any(option.eligible for option in result):
        result.append(Advisory(Action.INSPECT, False, "Manual inspection remains available."))
    return tuple(result)
