"""Registry-backed LoRA identity and compatibility projection for Learning composition.

Pure over existing ``AssetRegistry`` evidence: the cache-only resolver reads the persisted snapshot (never scans or
hashes, so it is safe on the Tk thread), and the browse projection consumes the ``LoRAResource`` mapping the
existing tracked discovery worker already returns. ``ModelPolicy`` and the backend keep final admission authority.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.assets.compatibility import CompatibilityStatus, EvidenceConfidence
from src.gui_v2.lora_browser import visible_resource
from src.image_backends.forge_klein_lora import RegistryLoraResolver
from src.learning.lora_composition import (
    STATUS_AMBIGUOUS,
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_MISSING,
    STATUS_UNCERTAIN,
    AssetResolver,
    LoraAsset,
)

STATUS_LABELS = {
    STATUS_COMPATIBLE: "Available; family evidence matches the target (pair not physically qualified)",
    STATUS_UNCERTAIN: "Available; compatibility uncertain (no non-filename family evidence)",
    STATUS_INCOMPATIBLE: "Incompatible with the target model",
    STATUS_MISSING: "Missing or stale inventory",
    STATUS_AMBIGUOUS: "Ambiguous name (matches more than one local file)",
}


def asset_from_record(name: str, record: Any | None, reason: str, family: str) -> LoraAsset:
    """Classify one registry record against the target family; filename hints never decide compatibility."""
    if record is None:
        status = (
            STATUS_AMBIGUOUS
            if "more than one" in reason or "mbiguous" in reason
            else STATUS_MISSING
        )
        return LoraAsset(name, status, reason=reason)
    sha256 = str(getattr(record, "sha256", "") or "")
    profile = getattr(record, "compatibility", None)
    evidence = tuple(
        item
        for item in (getattr(profile, "evidence", ()) or ())
        if item.confidence is not EvidenceConfidence.FILENAME_HINT
    )
    sources = ", ".join(sorted({item.source for item in evidence}))
    detected = profile.family.value if profile is not None and profile.family is not None else ""
    if profile is not None and profile.status is CompatibilityStatus.CONFLICTING:
        return LoraAsset(
            name,
            STATUS_INCOMPATIBLE,
            sha256,
            detected,
            sources,
            "conflicting model-family evidence",
        )
    if (
        profile is not None
        and profile.status is CompatibilityStatus.RESOLVED
        and evidence
        and detected
    ):
        if detected == family:
            return LoraAsset(name, STATUS_COMPATIBLE, sha256, detected, sources)
        return LoraAsset(
            name, STATUS_INCOMPATIBLE, sha256, detected, sources, f"{detected} family evidence"
        )
    return LoraAsset(
        name, STATUS_UNCERTAIN, sha256, detected, sources, "no non-filename family evidence"
    )


def registry_resolver(family: str, registry: Any | None = None) -> AssetResolver:
    """Cache-only identity resolver over the existing AssetRegistry; refresh is a separate, tracked worker."""
    resolver = RegistryLoraResolver(registry, cache_only=True)

    def resolve(name: str) -> LoraAsset:
        record, reason = resolver.record_for(name)
        return asset_from_record(name, record, reason, family)

    return resolve


@dataclass(frozen=True)
class InventoryRow:
    name: str
    asset: LoraAsset
    fixed: bool
    in_baseline: bool

    @property
    def selectable(self) -> bool:
        return self.asset.usable and not self.fixed

    @property
    def label(self) -> str:
        place = (
            "Fixed LoRA (unchanged)"
            if self.fixed
            else "In baseline prompt"
            if self.in_baseline
            else "Installed"
        )
        return f"{place}. {STATUS_LABELS[self.asset.status]}"


def asset_from_resource(resource: Any, family: str) -> LoraAsset:
    errors = tuple(getattr(resource, "errors", ()) or ())
    record = getattr(resource, "record", None)
    if record is None and any("mbiguous" in error for error in errors):
        return LoraAsset(resource.name, STATUS_AMBIGUOUS, reason="Ambiguous local adapter name")
    if record is None:
        return LoraAsset(resource.name, STATUS_MISSING, reason="No registry record")
    return asset_from_record(resource.name, record, "", family)


def inventory_rows(
    resources: Mapping[str, Any],
    family: str,
    *,
    mode: str,
    query: str = "",
    fixed: Iterable[str] = (),
    baseline: Iterable[str] = (),
    visible: Callable[[Any, str], bool] = visible_resource,
) -> list[InventoryRow]:
    """Case-insensitively sorted rows for the installed inventory, honoring the SFW/NSFW visibility policy."""
    fixed_keys = {str(name).casefold() for name in fixed}
    baseline_keys = {str(name).casefold() for name in baseline}
    rows = []
    for name, resource in sorted(resources.items(), key=lambda item: item[0].casefold()):
        if query.casefold() not in name.casefold() or not visible(resource, mode):
            continue
        rows.append(
            InventoryRow(
                name,
                asset_from_resource(resource, family),
                name.casefold() in fixed_keys,
                name.casefold() in baseline_keys,
            )
        )
    return rows


def inventory_resolver(resources: Mapping[str, Any], family: str) -> AssetResolver:
    """Identity from the explicitly refreshed in-memory discovery (no persistence, no scan, no hashing here)."""
    by_key = {name.casefold(): resource for name, resource in resources.items()}

    def resolve(name: str) -> LoraAsset:
        resource = by_key.get(str(name).strip().casefold().replace("\\", "/"))
        if resource is None:
            return LoraAsset(
                name,
                STATUS_MISSING,
                reason="not in the last LoRA discovery; refresh the installed LoRAs",
            )
        return asset_from_resource(resource, family)

    return resolve


def discover_loras(cancelled: Callable[[], bool]) -> dict[str, Any]:
    """The existing read-only scanner path, for the tracked background worker (never call on the Tk thread)."""
    from src.utils.lora_scanner import get_lora_scanner

    return dict(get_lora_scanner(None).scan_loras(read_only=True, cancelled=cancelled))
