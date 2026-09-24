"""StableNew-owned local asset identity, enrichment, and compatibility facts."""

from .metadata import (
    ActivationRequirement,
    AssetEnrichmentSnapshot,
    AssetMetadata,
    AssetMetadataService,
    CompatibilityProfile,
    CompatibilityStatus,
    EvidenceStrength,
    LegacyKeywordRecord,
    MetadataConflict,
    MetadataProvenance,
    MetadataSource,
    MetadataValue,
    ModelFamily,
    WeightGuidance,
)
from .registry import AssetKind, AssetRegistry, AssetRegistrySnapshot, RefreshResult

__all__ = [
    "ActivationRequirement",
    "AssetEnrichmentSnapshot",
    "AssetKind",
    "AssetMetadata",
    "AssetMetadataService",
    "AssetRegistry",
    "AssetRegistrySnapshot",
    "CompatibilityProfile",
    "CompatibilityStatus",
    "EvidenceStrength",
    "LegacyKeywordRecord",
    "MetadataConflict",
    "MetadataProvenance",
    "MetadataSource",
    "MetadataValue",
    "ModelFamily",
    "RefreshResult",
    "WeightGuidance",
]
