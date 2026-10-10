"""Pure, advisory model-bundle evidence (PR-IMG-MODELS-152).

Projects an ``ObservationScan`` into per-candidate ``ModelBundleEvidence``: what a primary file/logical package appears to
be, which external components it needs (from its own header where it states them, else from a labelled *documented*
requirement), and which observed files are ``possible``/``incompatible``/``missing``/``unknown``/``conflicting`` for each
need. It is evidence for an operator, not an executable profile: nothing here selects, admits, loads, writes, hashes or
contacts a runtime, and no ``ready``/``qualified`` label is ever produced. Every runtime/profile/hardware/job dimension
starts ``not_checked`` and is only filled by the (higher-layer) report from separately sourced evidence.

Never inferred from: a filename, a latent-channel count alone, a file size, or a mixed-precision label. A format mismatch
(for example a Diffusers-key VAE offered to a Forge-native layout) is reported as its own reason, not as a shape match.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from src.assets.component_evidence import (
    ARCH_FLUX2_DIT,
    ARCH_QWEN_IMAGE_DIT,
    ARCH_Z_IMAGE_DIT,
    ROLE_BUNDLED,
    ROLE_TEXT_ENCODER,
    ROLE_TRANSFORMER,
    ROLE_UNRECOGNIZED,
    ROLE_VAE,
    ComponentEvidence,
)
from src.assets.observation import (
    FORMAT_UNINSPECTED,
    ObservationScan,
    ObservedFile,
    ObservedPackage,
)

BUNDLE_CONTRACT = "model_bundle_evidence/1"
_SHARD_NAME = re.compile(r"-\d+-of-\d+\.safetensors$")

POSSIBLE, INCOMPATIBLE, MISSING, UNKNOWN, CONFLICTING = (
    "possible",
    "incompatible",
    "missing",
    "unknown",
    "conflicting",
)
NOT_CHECKED = "not_checked"
#: Cap on named adapter candidates per bundle (counts are always complete).
MAX_NAMED_ADAPTERS = 25

#: Requirements a header does not state, taken from published model documentation. Always labelled ``documented``.
_DOCUMENTED: Mapping[str, Mapping[str, Mapping[str, Any]]] = {
    ARCH_FLUX2_DIT: {
        ROLE_TEXT_ENCODER: {"family": "qwen3"},
        ROLE_VAE: {"vae_family": "flux2_vae", "key_format": "native", "latent_channels": 32},
    },
    ARCH_Z_IMAGE_DIT: {
        ROLE_TEXT_ENCODER: {"family": "qwen3"},
        ROLE_VAE: {"vae_family": "flux1_ae", "latent_channels": 16},
    },
    ARCH_QWEN_IMAGE_DIT: {
        ROLE_TEXT_ENCODER: {"family": "qwen2_5_vl"},
        ROLE_VAE: {"vae_family": "qwen_image_vae", "latent_channels": 16},
    },
}
_FAMILY = {
    ARCH_FLUX2_DIT: "flux2",
    ARCH_Z_IMAGE_DIT: "z_image",
    ARCH_QWEN_IMAGE_DIT: "qwen_image",
    "flux_dit": "flux1",
    "sdxl_unet_bundle": "sdxl",
    "sdxl_inpaint": "sdxl",
    "sdxl_refiner": "sdxl",
    "sd1": "sd1",
    "sd2": "sd2",
}
_ADAPTER_FAMILY = {
    "sd1": "sd1",
    "sd2": "sd2",
    "sdxl": "sdxl",
    "flux2": "flux_style_dit",
    "flux1": "flux_style_dit",
}


@dataclass(frozen=True)
class CandidateRelation:
    path: str
    outcome: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Relationship:
    role: str
    requirement: Mapping[str, Any]
    requirement_basis: str  # header | documented | header+documented | none
    outcome: str
    reason: str
    candidates: tuple[CandidateRelation, ...] = ()


@dataclass(frozen=True)
class ModelBundleEvidence:
    contract: str
    bundle_id: str
    primary: str  # display path (root label + relative), never absolute
    members: tuple[str, ...]
    package_status: str | None
    packaging: str  # native | diffusers_sharded | gguf | bundled_checkpoint | unknown
    architecture: str
    family: str
    variant: str | None
    variant_basis: str | None
    quantization: Mapping[str, Any]
    facts: Mapping[str, Any]  # selected scalar header facts (sizes, layers, channels); never paths
    embedded_components: tuple[str, ...]
    relationships: tuple[Relationship, ...]
    adapters: Mapping[str, Any]
    identity: str  # verified | pending
    claims: Mapping[str, Any]
    readiness: Mapping[str, str]
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def dependencies_feasible(self) -> str:
        return self.readiness.get("dependencies_feasible", UNKNOWN)


def display(item: ObservedFile) -> str:
    return f"{item.root_label}/{item.relative}"


def default_readiness(installed: str, header: str, dependencies: str) -> dict[str, str]:
    return {
        "installed": installed,
        "header_identified": header,
        "dependencies_feasible": dependencies,
        "served_in_forge": NOT_CHECKED,
        "selected_in_forge": NOT_CHECKED,
        "exact_profile_admitted": NOT_CHECKED,
        "hardware_qualified": NOT_CHECKED,
        "job_result_evidence": NOT_CHECKED,
    }


def _component(item: ObservedFile) -> ComponentEvidence | None:
    return item.header.component if item.header else None


def _quantization(component: ComponentEvidence | None, item: ObservedFile | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if component is not None:
        for key in (
            "precision_layout",
            "dtype_histogram",
            "dtype_bytes",
            "dominant_dtype_by_tensor_count",
            "dominant_dtype_by_bytes",
            "scale_key_count",
            "quantized_dtypes",
        ):
            if key in component.facts:
                result[key] = component.facts[key]
    if item is not None and item.header is not None:
        if item.header.quantization_formats:
            result["declared_quantization_formats"] = list(item.header.quantization_formats)
        if item.header.gguf is not None:
            result["gguf_file_type"] = item.header.gguf.quantization
            result["gguf_quantization_basis"] = (
                "container_declared" if item.header.gguf.quantization else "unknown"
            )
    return result


_FACT_KEYS = (
    "hidden_size",
    "layers",
    "double_blocks",
    "single_blocks",
    "input_channels",
    "joint_input_dim",
    "key_format",
    "tensor_count",
    "required_text_encoder_hidden_size",
    "required_vae_latent_channels",
)


def _facts(component: ComponentEvidence | None, item: ObservedFile | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if component is not None:
        result.update({key: component.facts[key] for key in _FACT_KEYS if key in component.facts})
    if item is not None:
        result["size_bytes"] = item.size
    return result


def _aggregate(candidates: list[CandidateRelation]) -> tuple[str, str]:
    outcomes = {candidate.outcome for candidate in candidates}
    if POSSIBLE in outcomes:
        return (
            POSSIBLE,
            "at least one observed file is structurally plausible; none is selected or verified",
        )
    if CONFLICTING in outcomes:
        return CONFLICTING, "observed evidence for a candidate disagrees with itself"
    if UNKNOWN in outcomes:
        return UNKNOWN, "only candidates whose structure could not be established were observed"
    if candidates:
        return (
            MISSING,
            "every observed candidate of this role is incompatible with the stated requirement",
        )
    return MISSING, "no observed file of this role"


def _encoder_requirement(component: ComponentEvidence) -> tuple[dict[str, Any], str]:
    documented = dict(_DOCUMENTED.get(component.architecture, {}).get(ROLE_TEXT_ENCODER, {}))
    hidden = component.facts.get("required_text_encoder_hidden_size")
    requirement = dict(documented)
    if isinstance(hidden, int):
        requirement["hidden_size"] = hidden
    basis = (
        "header+documented"
        if documented and hidden
        else "header"
        if hidden
        else "documented"
        if documented
        else "none"
    )
    return requirement, basis


def _vae_requirement(component: ComponentEvidence) -> tuple[dict[str, Any], str]:
    documented = dict(_DOCUMENTED.get(component.architecture, {}).get(ROLE_VAE, {}))
    header = component.facts.get("required_vae_latent_channels")
    requirement = dict(documented)
    conflict = (
        isinstance(header, int)
        and "latent_channels" in documented
        and header != documented["latent_channels"]
    )
    if isinstance(header, int):
        requirement["latent_channels"] = header
    if conflict:
        requirement["conflict"] = "header and documented latent channels disagree"
    basis = (
        "header+documented"
        if documented and isinstance(header, int)
        else "header"
        if isinstance(header, int)
        else "documented"
        if documented
        else "none"
    )
    return requirement, basis


def _encoder_candidate(item: ObservedFile, requirement: Mapping[str, Any]) -> CandidateRelation:
    path = display(item)
    component = _component(item)
    if item.header is None or item.header.error or component is None:
        return CandidateRelation(path, UNKNOWN, ("header could not be established",))
    if component.role != ROLE_TEXT_ENCODER:
        if component.role == ROLE_UNRECOGNIZED:
            return CandidateRelation(
                path, UNKNOWN, ("no reliable text-encoder signature; recorded as unrecognized",)
            )
        return CandidateRelation(
            path, INCOMPATIBLE, (f"observed as {component.role}, not a text encoder",)
        )
    wanted_family = requirement.get("family")
    if wanted_family and component.architecture != wanted_family:
        return CandidateRelation(
            path, INCOMPATIBLE, (f"encoder family {component.architecture} is not {wanted_family}",)
        )
    hidden, wanted = component.facts.get("hidden_size"), requirement.get("hidden_size")
    if wanted is None:
        return CandidateRelation(
            path, UNKNOWN, ("the primary file states no hidden-size requirement to compare",)
        )
    if hidden != wanted:
        return CandidateRelation(
            path, INCOMPATIBLE, (f"hidden size {hidden} is not the required {wanted}",)
        )
    if component.facts.get("quantized"):
        return CandidateRelation(
            path,
            UNKNOWN,
            (
                "quantized encoder: not shown interchangeable with the plain dtype the requirement covers",
            ),
        )
    return CandidateRelation(
        path,
        POSSIBLE,
        ("hidden size and encoder family match; selection and loading are unverified",),
    )


def _vae_candidate(item: ObservedFile, requirement: Mapping[str, Any]) -> CandidateRelation:
    path = display(item)
    component = _component(item)
    if item.header is None or item.header.error or component is None:
        return CandidateRelation(path, UNKNOWN, ("header could not be established",))
    if component.role != ROLE_VAE:
        if component.role == ROLE_UNRECOGNIZED:
            return CandidateRelation(
                path, UNKNOWN, ("no reliable VAE signature; recorded as unrecognized",)
            )
        return CandidateRelation(path, INCOMPATIBLE, (f"observed as {component.role}, not a VAE",))
    facts = component.facts
    reasons: list[str] = []
    if requirement.get("conflict"):
        return CandidateRelation(path, CONFLICTING, (str(requirement["conflict"]),))
    wanted_latent = requirement.get("latent_channels")
    if wanted_latent is not None and facts.get("latent_channels") != wanted_latent:
        reasons.append(
            f"latent channels {facts.get('latent_channels')} differ from the required {wanted_latent}"
        )
    wanted_family = requirement.get("vae_family")
    if wanted_family and facts.get("vae_family") != wanted_family:
        reasons.append(f"VAE family {facts.get('vae_family')} is not {wanted_family}")
    wanted_format = requirement.get("key_format")
    if wanted_format and facts.get("key_format") != wanted_format:
        reasons.append(
            f"key format {facts.get('key_format')} is not the {wanted_format} layout the runtime needs"
        )
    if reasons:
        return CandidateRelation(path, INCOMPATIBLE, tuple(reasons))
    if wanted_latent is None and not wanted_family:
        return CandidateRelation(path, UNKNOWN, ("no VAE requirement is established to compare",))
    return CandidateRelation(
        path, POSSIBLE, ("latent channels, family and key format match; selection is unverified",)
    )


def _adapter_relations(
    scan: ObservationScan, family: str, component: ComponentEvidence | None
) -> dict[str, Any]:
    wanted = _ADAPTER_FAMILY.get(family)
    hidden = component.facts.get("hidden_size") if component is not None else None
    lora: dict[str, list[str]] = {POSSIBLE: [], INCOMPATIBLE: [], UNKNOWN: [], CONFLICTING: []}
    embedding: dict[str, list[str]] = {POSSIBLE: [], INCOMPATIBLE: [], UNKNOWN: []}
    for item in scan.files:
        header = item.header
        if header is None or header.error:
            continue
        if header.lora is not None:
            evidence = header.lora
            if evidence.conflicts or evidence.suspected_misplaced_as:
                bucket = CONFLICTING if evidence.conflicts else UNKNOWN
            elif wanted is None or evidence.tensor_family is None:
                bucket = UNKNOWN
            elif evidence.tensor_family != wanted:
                bucket = INCOMPATIBLE
            elif (
                wanted == "flux_style_dit"
                and hidden
                and evidence.facts.get("flux_style_hidden_size") not in (None, hidden)
            ):
                bucket = INCOMPATIBLE
            elif wanted == "flux_style_dit" and not evidence.facts.get("flux_style_hidden_size"):
                bucket = UNKNOWN
            else:
                bucket = POSSIBLE
            lora[bucket].append(display(item))
        elif header.embedding is not None:
            suitability = header.embedding.suitability
            bucket = (
                UNKNOWN
                if suitability == "unknown" or wanted is None
                else POSSIBLE
                if suitability == wanted
                else INCOMPATIBLE
            )
            embedding[bucket].append(display(item))

    def summarize(groups: Mapping[str, list[str]]) -> dict[str, Any]:
        return {
            "counts": {key: len(values) for key, values in groups.items()},
            "possible_named": sorted(groups[POSSIBLE])[:MAX_NAMED_ADAPTERS],
        }

    return {
        "basis": "tensor-signature family only; never an admission",
        "lora": summarize(lora),
        "embedding": summarize(embedding),
    }


def _claims(package: ObservedPackage | None, item: ObservedFile | None) -> dict[str, Any]:
    claims: dict[str, Any] = {}
    if package is not None and package.config:
        claims["package_config"] = dict(package.config)
    if package is not None and package.license:
        claims["license_files"] = dict(package.license)
    if item is not None and item.header is not None and item.header.claims:
        claims["embedded_metadata"] = dict(item.header.claims)
    return claims


def _identity(items: list[ObservedFile]) -> str:
    return (
        "verified"
        if items and all(item.identity.status == "verified" for item in items)
        else "pending"
    )


def _bundle(
    scan: ObservationScan,
    encoders: list[ObservedFile],
    vaes: list[ObservedFile],
    *,
    bundle_id: str,
    primary: str,
    members: list[ObservedFile],
    package: ObservedPackage | None,
    component: ComponentEvidence | None,
    item: ObservedFile | None,
    packaging: str,
) -> ModelBundleEvidence:
    notes: list[str] = []
    installed = "present"
    if package is not None and package.status != "complete" and package.status != "single_file":
        installed = package.status
    gguf = item.header.gguf if item is not None and item.header is not None else None
    architecture = component.architecture if component is not None else ROLE_UNRECOGNIZED
    variant = variant_basis = None
    if item is not None and item.header is not None:
        checkpoint_arch = item.header.checkpoint_architecture
        if (
            checkpoint_arch in ("sdxl_inpaint", "sdxl_refiner", "sd1", "sd2")
            and architecture in _FAMILY
        ):
            architecture = checkpoint_arch
        variant, variant_basis = item.header.checkpoint_variant, item.header.variant_basis
        if variant == "inpaint" and checkpoint_arch == "sdxl_inpaint":
            variant_basis = "tensor_shape"
    if gguf is not None:
        architecture = f"gguf:{gguf.architecture}" if gguf.architecture else "gguf:unknown"
        notes.append(
            "GGUF container only: architecture family and loadability by any pinned runtime are unverified"
        )
    family = _FAMILY.get(architecture, "unknown")
    if package is not None and package.status not in ("complete", "single_file"):
        notes.append("package is not complete; no shard is a standalone runnable candidate")
    if architecture == ROLE_UNRECOGNIZED:
        notes.append(
            "no reliable architecture signature; recorded as unrecognized, never guessed from the file name"
        )
    header_state = (
        "format_uninspected"
        if item is not None and item.header is not None and item.header.format == FORMAT_UNINSPECTED
        else "container_parsed"
        if gguf is not None and gguf.parsed
        else "error"
        if item is not None and item.header is not None and item.header.error
        else "identified"
        if architecture != ROLE_UNRECOGNIZED and not architecture.startswith("gguf:")
        else "unrecognized"
    )
    if package is not None and package.status != "complete" and package.status != "single_file":
        header_state = "package_" + package.status
    relationships: list[Relationship] = []
    embedded: list[str] = []
    dependency_outcome = "not_required"
    if component is not None and component.role == ROLE_BUNDLED:
        embedded = ["text_encoder", "vae"]
    elif (
        component is not None
        and component.role == ROLE_TRANSFORMER
        and (package is None or package.status == "complete")
    ):
        enc_req, enc_basis = _encoder_requirement(component)
        enc_candidates = [_encoder_candidate(entry, enc_req) for entry in encoders]
        outcome, reason = _aggregate(enc_candidates)
        if enc_basis == "none":
            outcome, reason = (
                UNKNOWN,
                "the header states no encoder requirement and none is documented for this architecture",
            )
        relationships.append(
            Relationship(
                ROLE_TEXT_ENCODER, enc_req, enc_basis, outcome, reason, tuple(enc_candidates)
            )
        )
        vae_req, vae_basis = _vae_requirement(component)
        vae_candidates = [_vae_candidate(entry, vae_req) for entry in vaes]
        v_outcome, v_reason = _aggregate(vae_candidates)
        if vae_basis == "none":
            v_outcome, v_reason = (
                UNKNOWN,
                "the header states no VAE requirement and none is documented for this architecture",
            )
        relationships.append(
            Relationship(ROLE_VAE, vae_req, vae_basis, v_outcome, v_reason, tuple(vae_candidates))
        )
        order = (MISSING, INCOMPATIBLE, CONFLICTING, UNKNOWN, POSSIBLE)
        dependency_outcome = min((outcome, v_outcome), key=order.index)
    elif component is not None and component.role == ROLE_TRANSFORMER:
        dependency_outcome = UNKNOWN
    else:
        dependency_outcome = (
            UNKNOWN if gguf is not None or architecture == ROLE_UNRECOGNIZED else dependency_outcome
        )
        if gguf is not None:
            notes.append(
                "GGUF text-encoder/VAE requirements are not derivable from the container header"
            )
    return ModelBundleEvidence(
        BUNDLE_CONTRACT,
        bundle_id,
        primary,
        tuple(sorted(display(entry) for entry in members)),
        package.status if package is not None else None,
        packaging,
        architecture,
        family,
        variant,
        variant_basis,
        _quantization(component, item),
        _facts(component, item),
        tuple(embedded),
        tuple(relationships),
        _adapter_relations(scan, family, component),
        _identity(members),
        _claims(package, item),
        default_readiness(installed, header_state, dependency_outcome),
        tuple(notes),
    )


def build_bundles(scan: ObservationScan) -> tuple[ModelBundleEvidence, ...]:
    """Group-first, then pair: logical packages replace their shard files as the only candidates."""

    by_path = {item.path: item for item in scan.files}
    # A shard is never a dependency candidate on its own: its header is partial. Indexed package members and
    # shard-named files are kept in the inventory but excluded from pairing (no sharded-model execution is modelled).
    sharded = {path for package in scan.packages if package.index_file for path in package.members}

    def whole(item: ObservedFile) -> bool:
        return item.path not in sharded and not _SHARD_NAME.search(item.name.lower())

    encoders = [item for item in scan.files if item.kind == "text_encoder" and whole(item)]
    vaes = [item for item in scan.files if item.kind == "vae" and whole(item)]
    bundles: list[ModelBundleEvidence] = []
    packaged: set[str] = set()
    for package in scan.packages:
        if package.index_file is None:
            continue  # a single file with an adjacent config is still a file candidate below
        members = [by_path[path] for path in package.members if path in by_path]
        packaged.update(package.members)
        bundles.append(
            _bundle(
                scan,
                encoders,
                vaes,
                bundle_id=package.package_id,
                primary=f"{package.root_label}/{package.directory}/{package.index_file}".replace(
                    "//", "/"
                ),
                members=members,
                package=package,
                component=package.component,
                item=None,
                packaging="diffusers_sharded",
            )
        )
    package_by_member = {
        path: package
        for package in scan.packages
        if package.index_file is None
        for path in package.members
    }
    for item in scan.files:
        if item.kind not in ("checkpoint", "transformer") or item.path in packaged:
            continue
        component = _component(item)
        if _SHARD_NAME.search(item.name.lower()):
            # A shard-named file with no validated index is never a standalone candidate: its header is partial.
            orphan = _bundle(
                scan,
                encoders,
                vaes,
                bundle_id=f"{item.root_label}:{item.relative}",
                primary=display(item),
                members=[item],
                package=None,
                component=None,
                item=item,
                packaging="unindexed_shard",
            )
            readiness = dict(orphan.readiness)
            readiness.update({"installed": "orphan_shard", "header_identified": "partial_shard"})
            bundles.append(
                replace(
                    orphan,
                    readiness=readiness,
                    notes=(
                        *orphan.notes,
                        "named like one shard of a multi-file model but no valid index groups it; not a standalone candidate",
                    ),
                )
            )
            continue
        packaging = (
            "gguf"
            if item.suffix == ".gguf"
            else "bundled_checkpoint"
            if component is not None and component.role == ROLE_BUNDLED
            else "native"
            if component is not None and component.role == ROLE_TRANSFORMER
            else "unknown"
        )
        bundles.append(
            _bundle(
                scan,
                encoders,
                vaes,
                bundle_id=f"{item.root_label}:{item.relative}",
                primary=display(item),
                members=[item],
                package=package_by_member.get(item.path),
                component=component,
                item=item,
                packaging=packaging,
            )
        )
    return tuple(sorted(bundles, key=lambda entry: entry.bundle_id.casefold()))


__all__ = [
    "BUNDLE_CONTRACT",
    "CONFLICTING",
    "INCOMPATIBLE",
    "MISSING",
    "NOT_CHECKED",
    "POSSIBLE",
    "UNKNOWN",
    "CandidateRelation",
    "ModelBundleEvidence",
    "Relationship",
    "build_bundles",
    "default_readiness",
    "display",
]
