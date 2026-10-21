"""Pure browser projection; registry evidence and ModelPolicy remain authoritative."""

from __future__ import annotations

from dataclasses import dataclass

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, EvidenceConfidence
from src.assets.registry import AssetKind, AssetRegistrySnapshot
from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.image_backends.forge_klein_lora import classify_klein_lora, unavailable_decision
from src.image_backends.model_policy import EVIDENCE_REGISTRY, ModelPolicy
from src.image_backends.model_policy_lora import assess_lora_selection
from src.utils.lora_scanner import LoRAResource

PAGE_SIZE = 4


def target_profile(snapshot: AssetRegistrySnapshot, model_name: str) -> CompatibilityProfile | None:
    """Read only the worker-returned snapshot; ambiguous target aliases stay unknown."""
    key = model_name.replace("\\", "/").rsplit("/", 1)[-1].split(" [", 1)[0].casefold()
    matches = [
        record
        for record in snapshot.records_for(AssetKind.CHECKPOINT)
        if any(
            key in {location.display_name.casefold(), location.path.name.casefold()}
            for location in record.locations
            if location.kind is AssetKind.CHECKPOINT
        )
    ]
    return matches[0].compatibility if len(matches) == 1 else None


def visible_resource(resource: LoRAResource, mode: str) -> bool:
    subject = dict(resource.visibility)
    subject.update(name=resource.name, keywords=resource.keywords, description=resource.description)
    # Failed metadata reads cannot establish a safe projection of the remaining strings or preview.
    return not (mode == "sfw" and resource.errors) and ContentVisibilityResolver(mode).is_visible(
        subject
    )


def browser_page(
    resources: dict[str, LoRAResource], mode: str, query: str, page: int
) -> tuple[list[LoRAResource], int, int]:
    matches = [
        value
        for name, value in sorted(resources.items(), key=lambda item: item[0].casefold())
        if visible_resource(value, mode) and query.casefold() in name.casefold()
    ]
    pages = max(1, (len(matches) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(page, 0), pages - 1)
    return matches[page * PAGE_SIZE : (page + 1) * PAGE_SIZE], page, pages


@dataclass(frozen=True)
class AdapterProjection:
    family: str = "Unknown / unverified family"
    compatibility: str = "Unknown / unverified compatibility"
    source: str = "No model-family evidence"


def project_adapter(
    resource: LoRAResource,
    policy: ModelPolicy | None,
    target: CompatibilityProfile | None = None,
) -> AdapterProjection:
    record = resource.record
    profile = record.compatibility if record is not None else None
    evidence = (
        tuple(
            item
            for item in profile.evidence
            if item.confidence is not EvidenceConfidence.FILENAME_HINT
        )
        if profile
        else ()
    )
    family = (
        profile.family.value
        if profile and profile.family and evidence
        else "Unknown / unverified family"
    )
    sources = ", ".join(sorted({item.source for item in evidence})) or "No model-family evidence"
    status = "Unknown / unverified compatibility"
    if policy is not None:
        decision = (
            classify_klein_lora(resource.name, record)
            if record
            else unavailable_decision(resource.name, "unavailable")
        )
        assessment = assess_lora_selection(policy, [(resource.name, 0.8)], lambda _name: decision)
        if assessment.exact:
            exact_status = assessment.statuses.get(resource.name)
            if exact_status == "compatible":
                status = (
                    "Possibly compatible — explicit profile metadata; pair not physically qualified"
                )
                sources = decision.evidence_source
            elif exact_status == "incompatible" or (not assessment.supported):
                status = "Incompatible with target policy"
            elif exact_status == "conflicting":
                status = "Unknown / conflicting metadata"
        elif (
            profile
            and profile.status is CompatibilityStatus.RESOLVED
            and evidence
            and policy.evidence == EVIDENCE_REGISTRY
            and target is not None
            and target.status is CompatibilityStatus.RESOLVED
            and any(
                item.confidence is not EvidenceConfidence.FILENAME_HINT for item in target.evidence
            )
        ):
            if family == policy.family:
                status = "Possibly compatible — family evidence only; pair not physically qualified"
            elif family in {"sd1", "sd2", "sdxl", "sd3", "flux"} and policy.family in {
                "sd1",
                "sd2",
                "sdxl",
                "sd3",
                "flux",
            }:
                status = "Incompatible family evidence"
    if profile and profile.status is CompatibilityStatus.CONFLICTING:
        family, status = "Conflicting model-family evidence", "Unknown / conflicting metadata"
    if resource.errors:
        status = "Unknown / unavailable metadata"
    elif not evidence and profile and profile.evidence:
        # Filename hints remain observable in the registry; they cannot decide a pairing here.
        status = "Unknown / unverified compatibility (filename hint only)"
    return AdapterProjection(family, status, sources)
