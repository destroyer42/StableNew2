"""StableNew-owned local asset identity and discovery."""

from .compatibility import (
    CompatibilityProfile,
    CompatibilityStatus,
    EvidenceConfidence,
    FamilyEvidence,
    ModelFamily,
)
from .registry import (
    AssetKind,
    AssetLocation,
    AssetRecord,
    AssetRegistry,
    AssetRegistrySnapshot,
    RefreshResult,
)

__all__ = [
    "AssetKind",
    "AssetLocation",
    "AssetRecord",
    "AssetRegistry",
    "AssetRegistrySnapshot",
    "CompatibilityProfile",
    "CompatibilityStatus",
    "EvidenceConfidence",
    "FamilyEvidence",
    "ModelFamily",
    "RefreshResult",
]
