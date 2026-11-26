"""Observational component evidence and compatibility for Base Generation catalogs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.assets.checkpoint_structure import read_tensor_table
from src.assets.compatibility import (
    CompatibilityStatus,
    embedded_metadata_evidence,
    resolve_compatibility_profile,
    sidecar_metadata_evidence,
)
from src.assets.component_evidence import (
    ROLE_BUNDLED,
    ROLE_PREVIEW_DECODER,
    ROLE_TEXT_ENCODER,
    ROLE_UNRECOGNIZED,
    ROLE_VAE,
    ComponentEvidence,
    classify_tensor_table,
    inspect_component_file,
)
from src.utils.webui_resource_names import vae_names_match

if TYPE_CHECKING:
    from src.image_backends.model_policy import ModelPolicy

_NON_CHECKPOINTS = {ROLE_VAE, ROLE_TEXT_ENCODER, ROLE_PREVIEW_DECODER}
_SIDECARS = {
    ".json",
    ".yaml",
    ".yml",
    ".txt",
    ".md",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".csv",
    ".toml",
    ".info",
    ".ini",
    ".url",
    ".html",
}
_VAE_WEIGHTS = {".safetensors", ".sft", ".ckpt", ".pt", ".pth", ".bin"}
_LATENT_4_FAMILIES = {"sd1", "sd2", "sdxl"}
_VAE_FAMILIES = {
    "flux1_ae": {"flux1"},
    "flux2_vae": {"flux2_klein"},
    "qwen_image_vae": {"qwen_image"},
}


@dataclass(frozen=True)
class PickerEvidence:
    component: ComponentEvidence
    family: str | None = None
    excluded: bool = False
    refusal: str = ""
    path: Path | None = None
    #: N1: ``refusal`` is a policy warning (the model still runs), not a real block such as missing files.
    warning: bool = False

    @property
    def recognized(self) -> bool:
        return self.component.role != ROLE_UNRECOGNIZED


def inspect_picker_file(
    path: Path | None,
    name: str,
    *,
    vae: bool,
    approximate: bool = False,
    sidecar: Mapping[str, Any] | None = None,
) -> PickerEvidence:
    """Inspect an already discovered file on the refresh worker. Never scans or hashes."""
    suffix = (path or Path(name)).suffix.lower()
    if (
        approximate
        or suffix in _SIDECARS
        or (
            vae
            and (
                suffix == ".gguf"
                or (path is not None and path.is_file() and suffix not in _VAE_WEIGHTS)
            )
        )
    ):
        return PickerEvidence(ComponentEvidence(), excluded=True)
    metadata: dict[str, Any] = {}
    if path is None:
        component = ComponentEvidence()
    elif suffix in {".safetensors", ".sft"}:
        try:
            shapes, dtypes, metadata = read_tensor_table(path)
            component = classify_tensor_table(shapes, dtypes, metadata)
        except (OSError, ValueError, TypeError, UnicodeDecodeError):
            component = ComponentEvidence(
                error="malformed, truncated or unreadable safetensors header"
            )
    else:
        component = inspect_component_file(path)

    role = component.role
    if (vae and role not in {ROLE_VAE, ROLE_UNRECOGNIZED}) or (
        not vae and role in _NON_CHECKPOINTS
    ):
        return PickerEvidence(component, excluded=True)
    architecture = component.fact("checkpoint_architecture")
    declared = resolve_compatibility_profile(
        (
            *embedded_metadata_evidence(metadata),
            *sidecar_metadata_evidence(dict(sidecar or {}), location=str(path or name)),
        ),
        checkpoint_architecture=architecture,
    )
    family = (
        str(declared.family.value)
        if declared.status is CompatibilityStatus.RESOLVED and declared.family
        else None
    )
    if role == ROLE_BUNDLED and architecture in {
        "sd1",
        "sd2",
        "sdxl_base",
        "sdxl_refiner",
        "sdxl_inpaint",
    }:
        structural_family = architecture.split("_", 1)[0]
        family = (
            structural_family
            if family in (None, structural_family)
            and declared.status is not CompatibilityStatus.CONFLICTING
            else None
        )
    elif role != ROLE_VAE:
        family = None
    return PickerEvidence(component, family)


def vae_compatibility(evidence: PickerEvidence | None, family: str | None) -> str:
    if evidence is not None and evidence.excluded:
        return "incompatible"
    if not family or evidence is None or evidence.component.role != ROLE_VAE:
        return "unverified"
    layout = evidence.component.fact("vae_family")
    if layout == "ldm_kl_4ch":
        if family in {"flux", "flux1", "flux2_klein", "qwen_image", "sd3"}:
            return "incompatible"
        if family in _LATENT_4_FAMILIES and evidence.family in _LATENT_4_FAMILIES:
            return "compatible" if family == evidence.family else "incompatible"
    elif layout in _VAE_FAMILIES:
        compatible = _VAE_FAMILIES[layout]
        if family in compatible:
            return "compatible"
        if family in _LATENT_4_FAMILIES or family in {
            "flux",
            "flux1",
            "flux2_klein",
            "qwen_image",
            "sd3",
        }:
            return "incompatible"
    return "unverified"


@dataclass(frozen=True)
class VaeCatalog:
    """Valid backend names and the subset with positive compatibility evidence."""

    offered: tuple[str, ...]
    verified: tuple[str, ...]
    listed: tuple[str, ...]

    def resolve(self, value: str, *, recommendation: bool = False) -> str | None:
        if not value:
            return ""
        names = self.verified if recommendation else self.offered
        if value in names:
            return value
        if value in self.listed:
            return None
        matches = [name for name in self.listed if vae_names_match(name, value)]
        return matches[0] if len(matches) == 1 and matches[0] in names else None


def picker_entry(entries: Iterable[Any], name: str) -> Any | None:
    """Match an internal value or an unambiguous display alias."""
    from src.image_backends.model_readiness_probe import checkpoint_key

    entries = tuple(entries)
    exact = [entry for entry in entries if getattr(entry, "name", entry) == name]
    if exact:
        return exact[0] if len(exact) == 1 else None
    key = checkpoint_key(name)
    matches = [
        entry
        for entry in entries
        if key
        and key
        in {
            checkpoint_key(getattr(entry, "name", entry)),
            checkpoint_key(getattr(entry, "display_name", "")),
        }
    ]
    return matches[0] if len(matches) == 1 else None


def vae_catalog(entries: Iterable[Any], family: str | None) -> VaeCatalog | None:
    entries = tuple(entries)
    if not entries:
        return None
    offered: list[str] = []
    verified: list[str] = []
    listed: list[str] = []
    for entry in entries:
        name = str(getattr(entry, "name", entry))
        status = vae_compatibility(getattr(entry, "picker", None), family)
        if not name:
            continue
        listed.append(name)
        if status != "incompatible":
            offered.append(name)
            if status == "compatible":
                verified.append(name)
    return VaeCatalog(
        tuple(dict.fromkeys(offered)),
        tuple(dict.fromkeys(verified)),
        tuple(dict.fromkeys(listed)),
    )


def picker_model_family(
    entries: Iterable[Any], name: str, policy: ModelPolicy | None
) -> str | None:
    if policy is not None and policy.qualified:
        return policy.family
    evidence = getattr(picker_entry(entries, name), "picker", None)
    if isinstance(evidence, PickerEvidence):
        return evidence.family
    if policy is not None and policy.evidence == "registry_evidence" and policy.family != "unknown":
        return policy.family
    return None
