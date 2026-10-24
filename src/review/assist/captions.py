"""Caption suggestions as untrusted, bounded, visibility-aware text (PR-IMG-REVIEW-320).

Model output is data. It is sanitized (control, format and bidirectional characters removed, whitespace collapsed, length
capped), labelled as a suggestion in the UI, passed through ``ContentVisibilityResolver`` before display, and written to a
prompt draft only by an explicit operator action that can be undone. Nothing here evaluates, parses as configuration or
persists the text, and no rating, Learning record, PromptPack or metadata is touched.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from src.controller.content_visibility_resolver import REDACTED_TEXT, ContentVisibilityResolver
from src.review.assist.contracts import (
    MAX_CAPTION_CHARS,
    MAX_LABEL_CHARS,
    MAX_OBJECTS,
    CaptionOutput,
    CaptionProposal,
    ObjectLabel,
    RawObject,
    SourceIdentity,
)

_WHITESPACE = re.compile(r"\s+")
#: Prompt-syntax characters (LoRA/extra-network tags, wildcards, weighting, alternation) are never kept: a caption is
#: descriptive prose, and a crafted image must not be able to smuggle prompt directives into the operator's draft.
_PROMPT_SYNTAX = re.compile(r"[<>{}\[\]()|]|_{2,}")
_DROPPED_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}


def sanitize_text(raw: object, limit: int) -> tuple[str, bool]:
    """``(clean, truncated)``: printable text only, single-spaced, at most ``limit`` characters."""

    text = raw if isinstance(raw, str) else ""
    kept = []
    for char in text:
        category = unicodedata.category(char)
        if char in "\t\r\n":
            kept.append(" ")
        elif category not in _DROPPED_CATEGORIES:
            kept.append(char)
    clean = _WHITESPACE.sub(" ", _PROMPT_SYNTAX.sub(" ", "".join(kept))).strip()
    if len(clean) > limit:
        return clean[: limit - 1].rstrip() + "…", True
    return clean, False


def bounded_objects(
    raw: tuple[RawObject, ...], identity: SourceIdentity
) -> tuple[ObjectLabel, ...]:
    """At most ``MAX_OBJECTS`` labelled boxes, each label sanitized and each box clipped to the image."""

    objects: list[ObjectLabel] = []
    for item in raw[:MAX_OBJECTS]:
        label, _ = sanitize_text(item.label, MAX_LABEL_CHARS)
        try:
            x1, y1, x2, y2 = (float(value) for value in item.box)
        except (TypeError, ValueError):
            continue
        if not all(map(_finite, (x1, y1, x2, y2))) or not label:
            continue
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        box = (
            int(min(max(left, 0), identity.width - 1)),
            int(min(max(top, 0), identity.height - 1)),
            int(min(max(right, 0), identity.width - 1)),
            int(min(max(bottom, 0), identity.height - 1)),
        )
        if box[2] > box[0] and box[3] > box[1]:
            objects.append(ObjectLabel(label, box))
    return tuple(objects)


def _finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def build_caption_proposal(
    ticket: int, identity: SourceIdentity, output: CaptionOutput
) -> CaptionProposal:
    text, truncated = sanitize_text(output.text, MAX_CAPTION_CHARS)
    return CaptionProposal(
        ticket=ticket,
        identity=identity,
        text=text,
        truncated=truncated,
        objects=bounded_objects(output.objects, identity),
        model=output.model,
    )


@dataclass(frozen=True, slots=True)
class CaptionView:
    text: str
    hidden: bool
    can_apply: bool


def present_caption(text: str, resolver: ContentVisibilityResolver) -> CaptionView:
    """What the operator may see. Hidden text can neither be shown nor applied to a draft."""

    shown = resolver.redact_text(text, item={"description": text, "positive_prompt": text})
    hidden = shown == REDACTED_TEXT
    return CaptionView(shown, hidden, bool(text.strip()) and not hidden)


def present_label(label: str, resolver: ContentVisibilityResolver) -> str:
    return resolver.redact_text(label, item={"label": label})


class DraftBinding(Protocol):
    def get(self) -> str: ...

    def set(self, text: str) -> None: ...


def compose_draft(original: str, suggestion: str) -> str:
    base = original.rstrip()
    if not base:
        return suggestion
    return f"{base}, {suggestion}" if not base.endswith((",", ".", ";")) else f"{base} {suggestion}"


class CaptionApplication:
    """One reversible, explicit application of a suggestion to one draft field."""

    def __init__(self, binding: DraftBinding, on_change: Callable[[], None] | None = None) -> None:
        self._binding = binding
        self._on_change = on_change
        self._original: str | None = None
        self._applied: str | None = None

    @property
    def applied(self) -> bool:
        return self._applied is not None

    def apply(self, suggestion: str) -> bool:
        """Write the suggestion once. A second call changes nothing until it is undone."""

        if self.applied or not suggestion.strip():
            return False
        self._original = self._binding.get()
        self._applied = compose_draft(self._original, suggestion)
        self._binding.set(self._applied)
        if self._on_change is not None:
            self._on_change()
        return True

    def undo(self) -> bool:
        """Restore the draft as it was, unless the operator has edited it since (their edits are never discarded)."""

        if self._applied is None or self._original is None:
            return False
        if self._binding.get() != self._applied:
            return False
        self._binding.set(self._original)
        self._original = self._applied = None
        if self._on_change is not None:
            self._on_change()
        return True

    def forget(self) -> None:
        """Keep the applied text as the operator's own; this application can no longer be undone."""

        self._original = self._applied = None


__all__ = [
    "CaptionApplication",
    "CaptionView",
    "DraftBinding",
    "bounded_objects",
    "build_caption_proposal",
    "compose_draft",
    "present_caption",
    "present_label",
    "sanitize_text",
]
