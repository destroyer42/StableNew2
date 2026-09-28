"""Conservative, observational model-family compatibility evidence.

Produces provenance-preserving evidence about which narrow model family a
local asset's embedded metadata, local sidecar metadata, or filename
plausibly indicates. This module answers only "what evidence exists and
where did it come from" -- it never ranks, recommends, or rejects an asset.
Conflicting or absent evidence is preserved rather than resolved by guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ModelFamily(str, Enum):
    SD1 = "sd1"
    SD2 = "sd2"
    SDXL = "sdxl"
    SD3 = "sd3"
    FLUX = "flux"


class EvidenceConfidence(str, Enum):
    METADATA = "metadata"
    FILENAME_HINT = "filename_hint"


class CompatibilityStatus(str, Enum):
    RESOLVED = "resolved"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"


@dataclass(frozen=True)
class FamilyEvidence:
    """One piece of evidence toward a model family, with exact provenance."""

    family: ModelFamily
    source: str
    raw_value: str
    confidence: EvidenceConfidence
    location: str | None = None


@dataclass(frozen=True)
class CompatibilityProfile:
    """Observational projection: what family evidence exists, not a verdict."""

    status: CompatibilityStatus
    family: ModelFamily | None
    evidence: tuple[FamilyEvidence, ...]


# Explicit, conservative tokens only, covering three realistic conventions
# seen in repository evidence: kohya-style underscore versions (embedded
# metadata, e.g. "sdxl_base_v1-0", "sd_v1.5"), CivitAI-style space-separated
# labels (local sidecars, e.g. "SD 1.5", "SDXL 1.0"), and canonical ModelSpec
# architecture strings (embedded metadata, e.g. "stable-diffusion-xl-v1-base",
# "stable-diffusion-v1"). SDXL/FLUX/SD3 tokens are checked first so they are
# never shadowed by a shorter SD1/SD2 token.
_FAMILY_TOKENS: tuple[tuple[str, ModelFamily], ...] = (
    ("sdxl", ModelFamily.SDXL),
    ("sd_xl", ModelFamily.SDXL),
    ("sd xl", ModelFamily.SDXL),
    ("stable-diffusion-xl", ModelFamily.SDXL),
    ("flux", ModelFamily.FLUX),
    ("sd3", ModelFamily.SD3),
    ("sd_v3", ModelFamily.SD3),
    ("sd 3", ModelFamily.SD3),
    ("stable-diffusion-v3", ModelFamily.SD3),
    ("sd2", ModelFamily.SD2),
    ("sd_v2", ModelFamily.SD2),
    ("sd 2", ModelFamily.SD2),
    ("stable-diffusion-v2", ModelFamily.SD2),
    ("sd1", ModelFamily.SD1),
    ("sd_v1", ModelFamily.SD1),
    ("sd 1", ModelFamily.SD1),
    ("stable-diffusion-v1", ModelFamily.SD1),
)

# Likely authoritative embedded-metadata evidence fields (repository evidence
# from PR-ASSET-DISCOVERY-100). Every field present here is inspected; none
# is skipped merely because an earlier field already produced evidence.
EMBEDDED_BASE_MODEL_KEYS: tuple[str, ...] = (
    "ss_base_model_version",
    "modelspec.architecture",
    "modelspec.base_model_version",
)

# Common local CivitAI-sidecar base-model fields.
SIDECAR_BASE_MODEL_KEYS: tuple[str, ...] = ("baseModel", "base_model")


def _normalize_token(raw: str) -> ModelFamily | None:
    lowered = raw.strip().lower()
    for needle, family in _FAMILY_TOKENS:
        if needle in lowered:
            return family
    return None


def _all_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """Every non-empty supported field, not just the first.

    A field silently suppressing another would hide genuine conflicting
    evidence, so every recognized field must contribute its own evidence.
    """

    found = []
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            found.append((key, str(value).strip()))
    return tuple(found)


def embedded_metadata_evidence(metadata: dict[str, Any]) -> tuple[FamilyEvidence, ...]:
    """Content-level evidence derived from safetensors-header metadata.

    Every supported field present with a recognized value becomes its own
    evidence record; callers must not assume at most one exists.
    """

    evidence = []
    for _key, raw_value in _all_present(metadata, EMBEDDED_BASE_MODEL_KEYS):
        family = _normalize_token(raw_value)
        if family is not None:
            evidence.append(
                FamilyEvidence(family, "embedded_metadata", raw_value, EvidenceConfidence.METADATA)
            )
    return tuple(evidence)


def sidecar_metadata_evidence(
    metadata: dict[str, Any], *, location: str
) -> tuple[FamilyEvidence, ...]:
    """Location-scoped evidence derived from a local sidecar JSON file.

    Every supported field present with a recognized value becomes its own
    evidence record; callers must not assume at most one exists.
    """

    evidence = []
    for _key, raw_value in _all_present(metadata, SIDECAR_BASE_MODEL_KEYS):
        family = _normalize_token(raw_value)
        if family is not None:
            evidence.append(
                FamilyEvidence(
                    family, "sidecar_metadata", raw_value, EvidenceConfidence.METADATA, location
                )
            )
    return tuple(evidence)


def filename_hint_evidence(filename: str, *, location: str) -> FamilyEvidence | None:
    """Weakest-tier evidence: an explicit family token literally in a filename."""

    family = _normalize_token(filename)
    if family is None:
        return None
    return FamilyEvidence(
        family, "filename", filename, EvidenceConfidence.FILENAME_HINT, location
    )


def resolve_compatibility_profile(evidence: tuple[FamilyEvidence, ...]) -> CompatibilityProfile:
    """Resolve one profile from all gathered evidence without discarding any of it.

    Metadata-tier evidence (embedded + sidecar) always outranks filename-hint
    evidence; filename hints are only consulted when no metadata evidence
    exists at all. Within whichever tier is consulted, more than one distinct
    family is an explicit conflict, never a first-wins/last-wins pick.
    """

    metadata_tier = tuple(item for item in evidence if item.confidence is EvidenceConfidence.METADATA)
    tier = metadata_tier or tuple(
        item for item in evidence if item.confidence is EvidenceConfidence.FILENAME_HINT
    )
    if not tier:
        return CompatibilityProfile(CompatibilityStatus.UNKNOWN, None, evidence)
    families = {item.family for item in tier}
    if len(families) > 1:
        return CompatibilityProfile(CompatibilityStatus.CONFLICTING, None, evidence)
    return CompatibilityProfile(CompatibilityStatus.RESOLVED, next(iter(families)), evidence)
