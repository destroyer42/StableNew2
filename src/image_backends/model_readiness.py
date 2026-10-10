"""Installed-model readiness projection (PR-IMG-MODELS-150): discovered and installed is not executable.

One pure, I/O-free answer to "can StableNew run this multi-component image model, and if not, what is missing?". It keeps
seven things apart and conflates none of them: local file presence, structural identity evidence, the auxiliary
dependencies the checkpoint's own header asks for, what Forge *lists* (``/sd-modules`` is a catalog), what Forge currently
has *selected* (``forge_additional_modules`` from ``/options`` is live state), whether an exact qualified StableNew profile
exists, and hardware qualification (never established here).

The inputs are plain evidence objects gathered elsewhere (header-only ``ComponentEvidence`` per file, the two Forge reads).
Nothing here reads a file, calls Forge, hashes, writes or imports Tk. Missing or failed evidence is ``unavailable``/unknown,
never "empty" and never "ready". A structural match is not a load proof and is never labelled executable.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.assets.component_evidence import (
    ROLE_TEXT_ENCODER,
    ROLE_TRANSFORMER,
    ROLE_VAE,
    ComponentEvidence,
)

CONTRACT = "model_readiness/1"
QUALIFIED_STATUS = "qualified"
UNQUALIFIED_STATUS = "unqualified"


class ReadinessStatus(str, Enum):
    QUALIFIED = "qualified"
    #: A self-contained or unrecognized checkpoint: nothing here claims it needs auxiliary files.
    NOT_DEPENDENCY_BEARING = "not_dependency_bearing"
    DEPENDENCIES_INCOMPLETE = "dependencies_incomplete"
    DEPENDENCIES_PRESENT_NOT_SELECTED = "dependencies_present_not_selected"
    SELECTED_UNQUALIFIED = "selected_unqualified"
    UNKNOWN_OR_CONFLICTING = "unknown_or_conflicting"
    UNAVAILABLE_OR_STALE = "unavailable_or_stale"


STATUS_LABELS: Mapping[ReadinessStatus, str] = {
    ReadinessStatus.QUALIFIED: "Qualified",
    ReadinessStatus.NOT_DEPENDENCY_BEARING: "No auxiliary dependencies identified",
    ReadinessStatus.DEPENDENCIES_INCOMPLETE: "Discovered — dependencies incomplete",
    ReadinessStatus.DEPENDENCIES_PRESENT_NOT_SELECTED: "Discovered — dependencies present but not selected",
    ReadinessStatus.SELECTED_UNQUALIFIED: "Discovered — selected but execution unqualified",
    ReadinessStatus.UNKNOWN_OR_CONFLICTING: "Unknown/conflicting",
    ReadinessStatus.UNAVAILABLE_OR_STALE: "Unavailable/stale",
}


def normalize_module_name(value: str) -> str:
    """Order- and extension-insensitive module identity (basename, lower-case, no ``.safetensors``)."""

    base = str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    for ext in (".safetensors", ".sft", ".ckpt", ".pt", ".pth", ".bin"):
        if base.endswith(ext):
            return base[: -len(ext)]
    return base


@dataclass(frozen=True)
class CatalogModule:
    """One file Forge lists in ``/sd-modules`` with whatever header evidence could be read for it."""

    name: str
    evidence: ComponentEvidence | None = None
    #: ``False`` when the listing gave no readable local file (evidence stays unknown rather than guessed).
    file_known: bool = True


@dataclass(frozen=True)
class DependencyRequirement:
    role: str  # "text_encoder" | "vae"
    description: str
    #: What the checkpoint's header fixes (hidden size / latent channels), or ``None`` when it does not.
    required_value: int | None
    candidates: tuple[str, ...] = ()  # catalog names whose structure matches
    mismatched: tuple[str, ...] = ()  # catalog names of this role whose structure contradicts the requirement
    unclassified: tuple[str, ...] = ()  # catalog names whose structure could not be established
    selected: tuple[str, ...] = ()  # the matching candidates that are currently selected

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "requirement": self.description,
            "required_value": self.required_value,
            "candidates": list(self.candidates),
            "mismatched": list(self.mismatched),
            "unclassified": list(self.unclassified),
            "selected": list(self.selected),
        }


@dataclass(frozen=True)
class ModelReadiness:
    checkpoint: str
    status: ReadinessStatus
    reason_code: str
    reasons: tuple[str, ...] = ()
    qualified: bool = False
    #: Structural evidence of the checkpoint (path-free scalars) and the evidence type behind it.
    evidence_type: str = "none"
    architecture: str = "unrecognized"
    facts: Mapping[str, Any] = field(default_factory=dict)
    dependencies: tuple[DependencyRequirement, ...] = ()
    catalog_names: tuple[str, ...] | None = None
    selected_modules: tuple[str, ...] | None = None
    #: ``forge_options_get`` when the selection was read from Forge, ``unavailable`` otherwise; epoch of that read.
    selection_source: str = "unavailable"
    observed_at: float = 0.0
    qualification_status: str = UNQUALIFIED_STATUS

    @property
    def label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def blocks_dispatch(self) -> bool:
        """Only a positively identified dependency-bearing, unqualified checkpoint is refused before dispatch."""

        return not self.qualified and self.architecture != "unrecognized" and bool(self.dependencies)

    def as_dict(self) -> dict[str, Any]:
        """Durable, path-free diagnostic record for stage failure evidence and logs."""

        return {
            "contract": CONTRACT,
            "checkpoint": self.checkpoint,
            "evidence_type": self.evidence_type,
            "architecture": self.architecture,
            "facts": dict(self.facts),
            "status": self.status.value,
            "reason_code": self.reason_code,
            "qualification_status": self.qualification_status,
            "dependencies": [item.as_dict() for item in self.dependencies],
            "catalog_modules": None if self.catalog_names is None else list(self.catalog_names),
            "selected_modules": None if self.selected_modules is None else list(self.selected_modules),
            "selection_source": self.selection_source,
            "observed_at": self.observed_at,
        }

    def summary(self) -> str:
        """One operator-facing paragraph: what is present, selected, required and why it is not admitted."""

        lines = [f"{self.label}: {self.checkpoint}"]
        lines.extend(self.reasons)
        return " ".join(lines)


def _requirements(evidence: ComponentEvidence) -> list[tuple[str, str, int | None]]:
    hidden = evidence.fact("required_text_encoder_hidden_size")
    latent = evidence.fact("required_vae_latent_channels")
    return [
        (
            ROLE_TEXT_ENCODER,
            f"a text encoder with hidden size {hidden}" if hidden else "a separate text encoder",
            hidden if isinstance(hidden, int) else None,
        ),
        (
            ROLE_VAE,
            f"a VAE with {latent} latent channels" if latent else "a separate VAE",
            latent if isinstance(latent, int) else None,
        ),
    ]


def _module_matches(role: str, required: int | None, module: CatalogModule) -> str:
    """``match`` / ``mismatch`` / ``unclassified`` for one catalog module against one requirement."""

    found = module.evidence
    if found is None or found.error or found.role != role:
        # A module of a different recognised role is simply not a candidate for this role.
        if found is not None and not found.error and found.role not in ("unrecognized",):
            return "other"
        return "unclassified"
    key = "hidden_size" if role == ROLE_TEXT_ENCODER else "latent_channels"
    value = found.fact(key)
    if required is None:
        return "unclassified"  # the checkpoint's header fixes no value to compare against
    if value is None:
        return "unclassified"
    if found.fact("quantized"):
        return "mismatch"  # a quantized encoder is not interchangeable with the plain dtype the evidence covers
    return "match" if value == required else "mismatch"


def assess_model_readiness(
    model_name: str,
    *,
    checkpoint: ComponentEvidence | None,
    catalog: Sequence[CatalogModule] | None,
    selected: Sequence[str] | None,
    qualified_profile: bool = False,
    observed_at: float | None = None,
) -> ModelReadiness:
    """Combine header evidence, the Forge catalog and the live selection into one readiness verdict.

    ``catalog``/``selected`` are ``None`` when Forge could not be read (unavailable, never empty). A qualified exact
    profile short-circuits to ``QUALIFIED``; every other dependency-bearing checkpoint is, by definition, unqualified.
    """

    stamp = time.time() if observed_at is None else observed_at
    if qualified_profile:
        return ModelReadiness(
            model_name,
            ReadinessStatus.QUALIFIED,
            "exact_profile",
            ("An exact versioned StableNew execution profile qualifies this checkpoint.",),
            qualified=True,
            evidence_type="exact_profile",
            qualification_status=QUALIFIED_STATUS,
            observed_at=stamp,
        )
    if checkpoint is None:
        return ModelReadiness(
            model_name,
            ReadinessStatus.UNAVAILABLE_OR_STALE,
            "checkpoint_evidence_unavailable",
            ("The checkpoint file could not be located or read, so no structural evidence exists.",),
            observed_at=stamp,
        )
    if checkpoint.error:
        return ModelReadiness(
            model_name,
            ReadinessStatus.UNKNOWN_OR_CONFLICTING,
            "checkpoint_header_unreadable",
            (f"The checkpoint header could not be established ({checkpoint.error}).",),
            evidence_type="safetensors_header",
            observed_at=stamp,
        )
    if not checkpoint.dependency_bearing or checkpoint.role != ROLE_TRANSFORMER:
        return ModelReadiness(
            model_name,
            ReadinessStatus.NOT_DEPENDENCY_BEARING,
            "no_auxiliary_dependency_identified",
            ("No separate text encoder or VAE requirement was identified from the checkpoint header.",),
            evidence_type="safetensors_header",
            architecture=checkpoint.architecture,
            facts=dict(checkpoint.facts),
            observed_at=stamp,
        )

    base: dict[str, Any] = {
        "evidence_type": "safetensors_header",
        "architecture": checkpoint.architecture,
        "facts": dict(checkpoint.facts),
        "observed_at": stamp,
    }
    requirements = _requirements(checkpoint)
    needs = " and ".join(description for _role, description, _value in requirements)
    intro = (
        f"This is a multi-component {checkpoint.architecture.replace('_', ' ')} transformer: it needs {needs} supplied "
        "separately. StableNew has no exact qualified execution profile for it."
    )
    tail = "Physical qualification (PR-IMG-MODELS-151) is required before it can run."
    if catalog is None or selected is None:
        missing = "the Forge module catalog" if catalog is None else "Forge's current module selection"
        return ModelReadiness(
            model_name,
            ReadinessStatus.UNAVAILABLE_OR_STALE,
            "forge_state_unavailable",
            (intro, f"{missing.capitalize()} could not be read, so dependency availability is unknown.", tail),
            dependencies=tuple(DependencyRequirement(role, desc, value) for role, desc, value in requirements),
            catalog_names=None if catalog is None else tuple(item.name for item in catalog),
            selected_modules=None if selected is None else tuple(selected),
            **base,
        )

    names = [normalize_module_name(item.name) for item in catalog]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    selected_keys = {normalize_module_name(item) for item in selected}
    dependencies: list[DependencyRequirement] = []
    for role, description, value in requirements:
        candidates, mismatched, unclassified = [], [], []
        for module in catalog:
            verdict = _module_matches(role, value, module)
            if verdict == "match":
                candidates.append(module.name)
            elif verdict == "mismatch":
                mismatched.append(module.name)
            elif verdict == "unclassified" and (module.evidence is None or module.evidence.role == "unrecognized"):
                unclassified.append(module.name)
        chosen = tuple(name for name in candidates if normalize_module_name(name) in selected_keys)
        dependencies.append(
            DependencyRequirement(
                role, description, value, tuple(candidates), tuple(mismatched), tuple(unclassified), chosen
            )
        )
    common = {
        "dependencies": tuple(dependencies),
        "catalog_names": tuple(item.name for item in catalog),
        "selected_modules": tuple(selected),
        "selection_source": "forge_options_get",
        **base,
    }
    if duplicates:
        return ModelReadiness(
            model_name,
            ReadinessStatus.UNKNOWN_OR_CONFLICTING,
            "duplicate_module_names",
            (
                intro,
                f"Forge lists more than one file named {', '.join(duplicates)}; identity cannot be established from the name.",
                tail,
            ),
            **common,
        )
    detail = "; ".join(
        f"{item.role.replace('_', ' ')}: "
        + (", ".join(item.candidates) if item.candidates else "no structurally matching file listed")
        + (f" (selected: {', '.join(item.selected)})" if item.selected else "")
        for item in dependencies
    )
    if any(not item.candidates for item in dependencies):
        missing_roles = ", ".join(item.role.replace("_", " ") for item in dependencies if not item.candidates)
        return ModelReadiness(
            model_name,
            ReadinessStatus.DEPENDENCIES_INCOMPLETE,
            "dependency_not_listed",
            (intro, f"Not found in Forge's module catalog: {missing_roles}. {detail}.", tail),
            **common,
        )
    if all(item.selected for item in dependencies):
        return ModelReadiness(
            model_name,
            ReadinessStatus.SELECTED_UNQUALIFIED,
            "selected_but_unqualified",
            (
                intro,
                f"Matching components are listed and currently selected in Forge ({detail}); a structural match is not "
                "proof that the model loads or is correctly paired.",
                tail,
            ),
            **common,
        )
    return ModelReadiness(
        model_name,
        ReadinessStatus.DEPENDENCIES_PRESENT_NOT_SELECTED,
        "dependencies_listed_not_selected",
        (intro, f"Matching components are listed but not all are selected in Forge ({detail}).", tail),
        **common,
    )


__all__ = [
    "CONTRACT",
    "CatalogModule",
    "DependencyRequirement",
    "ModelReadiness",
    "QUALIFIED_STATUS",
    "ReadinessStatus",
    "STATUS_LABELS",
    "UNQUALIFIED_STATUS",
    "assess_model_readiness",
    "normalize_module_name",
]
