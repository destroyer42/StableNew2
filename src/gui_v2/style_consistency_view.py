"""Toolkit-neutral presentation of the Style Consistency selector (GUI-540).

The catalog (``data/style_loras.json``) lists styles; it is not proof a weight file is installed. Availability is
classified from inventory a tracked discovery worker already returned, so building choices never scans. A saved
selection is always representable, whatever its availability, and nothing here edits the pack.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from src.config.style_lora_config import StyleLoRADefinition
from src.controller.content_visibility_resolver import REDACTED_TEXT
from src.training.style_lora_manager import (
    STYLE_AVAILABLE,
    STYLE_FILE_MISSING,
    STYLE_NOT_INSTALLED,
    STYLE_UNVERIFIED,
    ResolvedStyleLoRA,
    classify_style_availability,
)

NONE_LABEL = "(None)"
SHOW_UNAVAILABLE_LABEL = "Show examples and unavailable styles"

_CHOICE_SUFFIX = {
    STYLE_NOT_INSTALLED: "example, LoRA not installed",
    STYLE_FILE_MISSING: "weight file missing",
    STYLE_UNVERIFIED: "unverified, LoRA inventory not checked",
}
_AVAILABILITY_TEXT = {
    STYLE_AVAILABLE: "installed LoRA found",
    STYLE_NOT_INSTALLED: "catalog example; the matching LoRA is not installed",
    STYLE_FILE_MISSING: "the configured weight file is missing",
    STYLE_UNVERIFIED: "availability not verified yet",
}


@dataclass(frozen=True)
class StyleChoice:
    style_id: str
    label: str
    availability: str = STYLE_AVAILABLE
    saved: bool = False


def _find(definitions: Sequence[StyleLoRADefinition], style_id: str) -> StyleLoRADefinition | None:
    key = style_id.strip().lower()
    return next((item for item in definitions if item.style_id.lower() == key), None)


def build_style_choices(
    definitions: Sequence[StyleLoRADefinition],
    installed_lora_names: Collection[str] | None,
    saved_style_id: str,
    show_unavailable: bool,
) -> list[StyleChoice]:
    """(None), every available style, the saved style whatever its state, and optionally the rest of the catalog."""

    saved = str(saved_style_id or "").strip()
    choices = [StyleChoice("", NONE_LABEL)]
    labels = {NONE_LABEL}
    saved_listed = False

    def add(style_id: str, label: str, availability: str) -> None:
        if label in labels:
            label = f"{label} [{style_id}]"
        labels.add(label)
        choices.append(
            StyleChoice(style_id, label, availability, style_id.lower() == saved.lower())
        )

    for definition in definitions:
        availability = classify_style_availability(definition, installed_lora_names)
        is_saved = bool(saved) and definition.style_id.lower() == saved.lower()
        if availability != STYLE_AVAILABLE and not show_unavailable and not is_saved:
            continue
        suffix = _CHOICE_SUFFIX.get(availability)
        label = definition.display_name
        if suffix:
            label = f"{label} ({'saved, ' if is_saved else ''}{suffix})"
        add(definition.style_id, label, availability)
        saved_listed = saved_listed or is_saved
    if saved and not saved_listed:
        add(saved, f"{saved} (saved, not in the style catalog)", STYLE_NOT_INSTALLED)
    return choices


def selector_empty_state(
    definitions: Sequence[StyleLoRADefinition],
    installed_lora_names: Collection[str] | None,
    show_unavailable: bool,
) -> str:
    """Why the primary selector offers nothing, or an empty string when it does."""

    if not definitions:
        return "No style LoRAs are cataloged yet. Add entries to data/style_loras.json to enable pack-level styles."
    available = [
        item
        for item in definitions
        if classify_style_availability(item, installed_lora_names) == STYLE_AVAILABLE
    ]
    if available:
        return ""
    if installed_lora_names is None:
        return "Checking installed LoRAs; no style is confirmed available yet."
    hint = (
        ""
        if show_unavailable
        else f" Tick '{SHOW_UNAVAILABLE_LABEL}' to browse the catalog examples."
    )
    return "No cataloged style has a matching installed LoRA." + hint


def describe_style(
    style_id: str,
    definitions: Sequence[StyleLoRADefinition],
    installed_lora_names: Collection[str] | None,
    resolved: ResolvedStyleLoRA | None,
    *,
    pending: bool = False,
    phrase_visible: bool = True,
) -> str:
    """The selected style's name, availability, strength, catalog trigger ownership and warnings."""

    definition = _find(definitions, style_id)
    if definition is None:
        return (
            f"{style_id}: saved style that is not in the style catalog. The selection is kept as saved and "
            "nothing is added to prompts until it is available."
            + (
                f" {resolved.warning}"
                if resolved is not None and getattr(resolved, "warning", None)
                else ""
            )
        )
    availability = classify_style_availability(definition, installed_lora_names)
    if (
        availability == STYLE_UNVERIFIED
        and resolved is not None
        and getattr(resolved, "available", False)
    ):
        availability = STYLE_AVAILABLE
    lines = [f"{definition.display_name}: {_AVAILABILITY_TEXT[availability]}."]
    strength = resolved.weight if resolved is not None else definition.weight
    detail = f"Strength {strength:g}."
    if definition.compatible_model_families:
        detail += (
            f" Catalog families: {', '.join(definition.compatible_model_families)}. "
            "A family match is not checkpoint-pair qualification."
        )
    lines.append(detail)
    phrase = definition.trigger_phrase if phrase_visible else REDACTED_TEXT
    applied = resolved is not None and resolved.applied
    if resolved is None and pending:
        lines.append(
            f"Trigger phrase '{phrase}' is added automatically during prompt resolution while this style is active."
        )
        lines.append(
            "Compatibility with the current target model is evaluated when the style is next resolved. "
            "Your saved selection is kept unchanged."
        )
    elif applied:
        lines.append(
            f"Trigger phrase '{phrase}' and <lora:{definition.lora_name}:{strength:g}> are added automatically "
            "to every generated prompt; do not paste the phrase into the prompt."
        )
    else:
        lines.append(
            f"Catalog trigger phrase '{phrase}' (not applied while this style is inactive)."
        )
        warning = resolved.warning if resolved is not None else None
        lines.append(warning or f"{definition.display_name} is selected but currently inactive.")
        lines.append("Your saved selection is kept unchanged.")
    return "\n".join(lines)


__all__ = [
    "NONE_LABEL",
    "SHOW_UNAVAILABLE_LABEL",
    "StyleChoice",
    "build_style_choices",
    "describe_style",
    "selector_empty_state",
]
