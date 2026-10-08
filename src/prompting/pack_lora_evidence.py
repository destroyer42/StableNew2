"""Complete exact-admission evidence for explicit fresh PromptPack preflight."""

from typing import Any

from src.assets import AssetKind
from src.image_backends.forge_klein_lora import (
    classify_klein_lora,
    find_lora_record,
    unavailable_decision,
)
from src.image_backends.model_policy_lora import LoraEvidenceContext
from src.prompting.pack_lora_selection import KleinSelectionError


def prepare_selection_evidence(registry: Any, *, cancelled: Any = None) -> LoraEvidenceContext:
    if not registry.webui_root or not registry.webui_root.is_dir():
        raise KleinSelectionError(
            "Local LoRA evidence root is unavailable; configure assets and rebuild Preview"
        )
    roots = [root for kind, root in registry.supported_roots() if kind is AssetKind.LORA]
    if not any(root.is_dir() for root in roots):
        raise KleinSelectionError(
            "Local LoRA directories are unavailable; configure assets and rebuild Preview"
        )
    try:
        snapshot = registry.refresh(kinds={AssetKind.LORA}, cancelled=cancelled).snapshot
    except Exception as exc:
        raise KleinSelectionError(
            "LoRA evidence preparation failed; refresh assets and rebuild Preview"
        ) from exc

    def resolve(name: str) -> Any:
        record, reason = find_lora_record(snapshot, name)
        if record is None:
            return unavailable_decision(name, reason)
        if record.embedded_metadata_error or any(
            location.sidecar_error for location in record.locations
        ):
            raise KleinSelectionError(
                "LoRA metadata could not be assessed; repair evidence and rebuild Preview"
            )
        return classify_klein_lora(name, record)

    return LoraEvidenceContext(resolve)
