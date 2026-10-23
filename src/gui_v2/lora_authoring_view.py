"""Toolkit-neutral presentation of a selected LoRA inside the Prompt tab (GUI-540).

Evidence comes only from the worker-returned ``LoRAResource`` (the existing scanner/AssetRegistry projection) and the
existing ``project_adapter`` compatibility vocabulary. Nothing here reads files, invents trigger words from names or
previews, or rewrites a saved selection.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from src.assets.compatibility import CompatibilityProfile
from src.controller.content_visibility_resolver import REDACTED_TEXT
from src.gui_v2.lora_browser import project_adapter
from src.image_backends.model_policy import ModelPolicy
from src.utils.lora_scanner import LoRAResource

NO_TRIGGER_METADATA = (
    "No trigger-word metadata available. The LoRA can still be selected, subject to compatibility "
    "and backend validation."
)
KEYWORD_READ_ERROR = "Local keyword metadata unavailable"
AMBIGUOUS_NAME_ERROR = "Ambiguous local adapter name"

TRIGGER_SOURCE_LABELS = {
    "civitai": "Civitai info file next to the weights",
    "txt": "text sidecar next to the weights",
    "readme": "README sidecar next to the weights",
}

AVAILABILITY_UNVERIFIED = "Inventory not verified; selection retained"
AVAILABILITY_VERIFIED = "Verified local asset reference (pairing unqualified)"
AVAILABILITY_MISSING = "Missing asset: not found in the local inventory; selection retained"
AVAILABILITY_AMBIGUOUS = "Unverified: the local name is ambiguous; selection retained"


@dataclass(frozen=True)
class SelectedLoraView:
    availability: str
    compatibility: str
    trigger_words: tuple[str, ...]
    trigger_line: str
    warnings: tuple[str, ...] = ()

    @property
    def can_insert(self) -> bool:
        return bool(self.trigger_words)


def project_selected_lora(
    resource: LoRAResource | None,
    *,
    verified: bool,
    hidden: bool,
    policy: ModelPolicy | None,
    target: CompatibilityProfile | None,
) -> SelectedLoraView:
    if hidden:
        return SelectedLoraView(
            AVAILABILITY_UNVERIFIED if resource is None else AVAILABILITY_VERIFIED,
            f"Compatibility: {REDACTED_TEXT}",
            (),
            f"Trigger words: {REDACTED_TEXT}",
        )
    if resource is None:
        if not verified:
            return SelectedLoraView(
                AVAILABILITY_UNVERIFIED,
                "Compatibility: cannot be assessed until the local inventory is verified.",
                (),
                "Trigger words: not loaded until the local inventory is verified.",
            )
        return SelectedLoraView(
            AVAILABILITY_MISSING,
            "Compatibility: cannot be assessed because the weight file was not found.",
            (),
            "Trigger words: none can be read for a missing asset.",
            ("Missing asset: the backend will reject this LoRA unless the file is restored.",),
        )

    ambiguous = AMBIGUOUS_NAME_ERROR in resource.errors
    projected = project_adapter(resource, policy, target)
    compatibility = f"{projected.compatibility} — {projected.family} ({projected.source})"
    availability = AVAILABILITY_AMBIGUOUS if ambiguous else AVAILABILITY_VERIFIED
    words = tuple(resource.keywords)
    keyword_error = KEYWORD_READ_ERROR in resource.errors
    warnings: list[str] = []
    if words:
        source = TRIGGER_SOURCE_LABELS.get(resource.source, "local metadata")
        line = (
            f"Trigger words from the {source}: {', '.join(words)}. "
            "The metadata does not state whether they are required."
        )
        if keyword_error:
            line += " Some metadata could not be read."
    elif keyword_error:
        line = (
            "Trigger-word metadata could not be read (unreadable sidecar). No words were assumed."
        )
    else:
        line = NO_TRIGGER_METADATA
    if resource.errors and not ambiguous:
        warnings.append("Local metadata was unavailable; compatibility is unverified.")
    return SelectedLoraView(availability, compatibility, words, line, tuple(warnings))


def split_keywords(keywords: str | Iterable[str]) -> tuple[str, ...]:
    """The words offered for insertion: a sequence verbatim, or a comma-separated string split into phrases."""

    items = keywords.split(",") if isinstance(keywords, str) else keywords
    seen: set[str] = set()
    words: list[str] = []
    for item in items:
        word = str(item or "").strip()
        if word and word.casefold() not in seen:
            seen.add(word.casefold())
            words.append(word)
    return tuple(words)


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, flags=re.IGNORECASE) is not None


@dataclass(frozen=True)
class TriggerInsertionPlan:
    inserted: tuple[str, ...]
    already_present: tuple[str, ...]
    auto_applied: tuple[str, ...]

    def new_text(self, existing: str) -> str:
        """``existing`` with the new words appended; the existing text is never altered or reordered."""

        if not self.inserted:
            return existing
        addition = ", ".join(self.inserted)
        if not existing.strip():
            return addition
        if existing.rstrip().endswith(","):
            return existing + ("" if existing[-1:].isspace() else " ") + addition
        return existing + ", " + addition

    def summary(self) -> str:
        parts: list[str] = []
        if self.inserted:
            parts.append(
                f"Inserted {len(self.inserted)} trigger word(s) at the end of the positive prompt."
            )
        if self.already_present:
            parts.append(f"Already in the prompt: {', '.join(self.already_present)}.")
        if self.auto_applied:
            parts.append(
                f"Supplied automatically by Style Consistency (not inserted): {', '.join(self.auto_applied)}."
            )
        return " ".join(parts) or "No trigger words to insert."


def plan_trigger_insertion(
    existing_text: str, words: Sequence[str], auto_applied_phrases: Sequence[str] = ()
) -> TriggerInsertionPlan:
    """Which words to add. Words already present, or owned by the resolver's automatic style trigger, are skipped."""

    owned_tokens = {
        token.strip().casefold()
        for phrase in auto_applied_phrases
        for token in str(phrase or "").split(",")
        if token.strip()
    }
    owned_text = ", ".join(str(phrase or "") for phrase in auto_applied_phrases)
    inserted: list[str] = []
    present: list[str] = []
    owned: list[str] = []
    for word in split_keywords(words):
        if word.casefold() in owned_tokens or (owned_text and _contains_phrase(owned_text, word)):
            owned.append(word)
        elif _contains_phrase(existing_text, word):
            present.append(word)
        else:
            inserted.append(word)
    return TriggerInsertionPlan(tuple(inserted), tuple(present), tuple(owned))


__all__ = [
    "AVAILABILITY_MISSING",
    "AVAILABILITY_UNVERIFIED",
    "AVAILABILITY_VERIFIED",
    "NO_TRIGGER_METADATA",
    "SelectedLoraView",
    "TriggerInsertionPlan",
    "plan_trigger_insertion",
    "project_selected_lora",
    "split_keywords",
]
