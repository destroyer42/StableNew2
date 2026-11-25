"""Toolkit-neutral proposed-change cards and the apply journal for AI Assist (AI-230).

Every model function (slot variety, new slot, phrase to slot) and the deterministic Check tab produce the same kind of thing for
the same list: a :class:`ProposedChange` card with a summary, a before/after preview, an effect line, a verdict and a stable key.
The Prompt tab owner applies a card only on an explicit operator press, through the existing stale-checked mutators; this module
only describes cards and remembers, in memory, how to take an applied change back.

The journal is never persisted and holds no widget; closing the dialog, a pack/slot/visibility change or a failed check
clears or refuses it. Pure: no Tk, no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.gui_v2.ai_slot_phrase import (
    PhraseReview,
    PhraseSpan,
    marker_text,
    replace_span,
)
from src.gui_v2.ai_slot_phrase import (
    detail_text as phrase_detail_text,
)
from src.gui_v2.ai_slot_phrase import (
    growth_line as phrase_growth_line,
)
from src.gui_v2.ai_slot_proposal import (
    ProposalContext,
    ProposalReview,
    detail_text,
    growth_line,
    place_marker,
)
from src.gui_v2.ai_slot_variety import (
    HIDDEN_TEXT,
    REASON_TEXT,
    SlotState,
    VarietyReview,
)
from src.pipeline.matrix_expansion_plan import plan_matrix_expansion
from src.utils.prompt_pack_utils import normalize_matrix_slot_name

KIND_VARIETY_VALUE = "variety_value"
KIND_NEW_SLOT = "new_slot"
KIND_PHRASE_SLOT = "phrase_slot"
KIND_REMOVE_DUPLICATE = "remove_duplicate"
KIND_NOTE = "note"

#: How many previous values a variety card shows before it elides the rest.
_VALUES_SHOWN = 6
_WINDOW_CHARS = 70
_EXAMPLE_CHARS = 150
MAX_JOURNAL = 20

_MARKER = re.compile(r"\[\[([^\[\]]+)\]\]")


@dataclass(frozen=True, slots=True)
class ProposedChange:
    """One change the operator may apply. ``reason`` is empty exactly when it can be applied now."""

    key: str
    kind: str
    title: str
    before: str = field(default="", repr=False)
    after: str = field(default="", repr=False)
    effect: str = field(default="", repr=False)
    rationale: str = field(default="", repr=False)
    examples: tuple[str, ...] = field(default=(), repr=False)
    reason: str = ""
    #: The rejection reason in words (fixed copy); empty for an offered or applied card.
    detail: str = field(default="", repr=False)
    applied: bool = False

    @property
    def note(self) -> bool:
        """Information only: shown, never applied."""

        return self.kind == KIND_NOTE

    @property
    def offered(self) -> bool:
        """Can be applied now: no rejection reason, not already applied and not a note."""

        return not self.reason and not self.applied and not self.note

    @property
    def rejected(self) -> bool:
        return bool(self.reason) and not self.applied and not self.note


def _values_text(values: Sequence[Any]) -> str:
    shown = [str(v) for v in values]
    if len(shown) > _VALUES_SHOWN:
        shown = ["…", *shown[-_VALUES_SHOWN:]]
    return ", ".join(shown)


def variety_changes(
    review: VarietyReview, slots: Sequence[SlotState], *, is_visible: Callable[[str], bool]
) -> tuple[ProposedChange, ...]:
    """One card per proposed value, in answer order."""

    by_name = {slot.name: slot for slot in slots}
    rationales = dict(review.rationales)
    cards: list[ProposedChange] = []
    for row in review.rows:
        slot = by_name.get(row.slot)
        hidden = row.reason == "hidden" or not is_visible(row.slot)
        title = HIDDEN_TEXT if hidden else f"{row.slot}: {row.value}"
        if row.index in review.added:
            cards.append(
                ProposedChange(f"variety:{row.index}", KIND_VARIETY_VALUE, title, applied=True)
            )
            continue
        if hidden:
            cards.append(
                ProposedChange(
                    f"variety:{row.index}",
                    KIND_VARIETY_VALUE,
                    title,
                    reason=row.reason or "hidden",
                    detail=REASON_TEXT.get(row.reason or "hidden", ""),
                )
            )
            continue
        before = f"{row.slot}: {_values_text(slot.values)}" if slot is not None else ""
        after = (
            f"{row.slot}: {_values_text([*slot.values, row.value])}"
            if slot is not None and row.offered
            else ""
        )
        cards.append(
            ProposedChange(
                f"variety:{row.index}",
                KIND_VARIETY_VALUE,
                title,
                before=before,
                after=after,
                rationale=rationales.get(row.slot, ""),
                reason=row.reason,
                detail=REASON_TEXT.get(row.reason, "") if row.reason else "",
            )
        )
    return tuple(cards)


def marker_windows(sentence: str, offset: int, slot_name: str) -> tuple[str, str]:
    """``(before, after)`` windows of ``sentence`` around ``offset``: the second has the ``[[slot]]`` marker in place."""

    start = max(0, offset - _WINDOW_CHARS)
    end = min(len(sentence), offset + _WINDOW_CHARS)
    after_text = place_marker(sentence, offset, slot_name)
    extra = len(after_text) - len(sentence)
    lead = "…" if start > 0 else ""
    tail = "…" if end < len(sentence) else ""
    return (
        f"{lead}{sentence[start:end]}{tail}",
        f"{lead}{after_text[start : end + extra]}{tail}",
    )


def span_windows(sentence: str, span: PhraseSpan, slot_name: str) -> tuple[str, str]:
    """``(before, after)`` windows of ``sentence`` around the selected span: the second has the span replaced by the marker."""

    start = max(0, span.start - _WINDOW_CHARS)
    end = min(len(sentence), span.end + _WINDOW_CHARS)
    lead = "…" if start > 0 else ""
    tail = "…" if end < len(sentence) else ""
    before = sentence[start:end]
    after = sentence[start : span.start] + marker_text(slot_name) + sentence[span.end : end]
    return f"{lead}{before}{tail}", f"{lead}{after}{tail}"


def slot_examples(
    sentence_with_marker: str,
    slots: Sequence[SlotState],
    new_name: str,
    new_values: Sequence[str],
    *,
    count: int = 3,
) -> tuple[str, ...]:
    """The first few compiled sentences the matrix would produce with the new slot, from the planner's own expansion order
    (the last dimension varies fastest), so the operator sees the effect before applying. No model involved."""

    config = {
        "enabled": True,
        "slots": [
            *({"name": s.name, "values": list(s.values)} for s in slots if s.name and s.values),
            {"name": new_name, "values": list(new_values)},
        ],
    }
    plan = plan_matrix_expansion(config)
    if not plan.dimensions:
        return ()
    new_key = normalize_matrix_slot_name(new_name)
    lines: list[str] = []
    for position in range(min(count, plan.selected_count, plan.theoretical_count)):
        combo = plan.combination_at(position)
        mapping = {
            normalize_matrix_slot_name(dim.name): str(value)
            for dim, value in zip(plan.dimensions, combo, strict=False)
        }
        out: list[str] = []
        length = 0
        focus = 0
        cursor = 0
        for match in _MARKER.finditer(sentence_with_marker):
            key = normalize_matrix_slot_name(match.group(1))
            piece = sentence_with_marker[cursor : match.start()]
            out.append(piece)
            length += len(piece)
            if key == new_key and not focus:
                focus = length
            replacement = mapping.get(key, match.group(0))
            out.append(replacement)
            length += len(replacement)
            cursor = match.end()
        out.append(sentence_with_marker[cursor:])
        text = "".join(out)
        start = max(0, focus - _EXAMPLE_CHARS // 2)
        lines.append(("…" if start else "") + text[start : start + _EXAMPLE_CHARS])
    return tuple(lines)


def proposal_changes(
    review: ProposalReview,
    context: ProposalContext,
    *,
    is_visible: Callable[[str], bool],
) -> tuple[ProposedChange, ...]:
    """One card per proposed slot, in answer order, with the sentence shown with its marker in place and the first few
    compiled examples."""

    cards: list[ProposedChange] = []
    for row in review.rows:
        key = f"slot:{row.index}"
        hidden = row.reason == "hidden"
        title = HIDDEN_TEXT if hidden else f"{row.slot_name}: {', '.join(row.values)}"
        if row.index in review.added:
            cards.append(ProposedChange(key, KIND_NEW_SLOT, title, applied=True))
            continue
        if hidden or not row.offered:
            cards.append(
                ProposedChange(
                    key,
                    KIND_NEW_SLOT,
                    title,
                    effect="" if hidden else growth_line(row),
                    rationale="" if hidden else row.rationale,
                    reason=row.reason,
                    detail=detail_text(row),
                )
            )
            continue
        offset = context.offsets[row.point] if 0 <= row.point < len(context.offsets) else -1
        before = after = ""
        examples: tuple[str, ...] = ()
        if 0 <= offset <= len(context.sentence):
            before, after = marker_windows(context.sentence, offset, row.slot_name)
            examples = slot_examples(
                place_marker(context.sentence, offset, row.slot_name),
                context.slots,
                row.slot_name,
                row.values,
            )
        cards.append(
            ProposedChange(
                key,
                KIND_NEW_SLOT,
                title,
                before=before,
                after=after,
                effect=growth_line(row),
                rationale=row.rationale if is_visible(row.rationale) else HIDDEN_TEXT,
                examples=examples,
            )
        )
    return tuple(cards)


def phrase_changes(
    review: PhraseReview,
    context: ProposalContext,
    span: PhraseSpan,
    *,
    is_visible: Callable[[str], bool],
) -> tuple[ProposedChange, ...]:
    """One card per proposed slot for the selected phrase, in answer order: the sentence before and after the span is replaced
    by the marker, and the first compiled examples (the first one reads exactly as the sentence did)."""

    cards: list[ProposedChange] = []
    for row in review.rows:
        key = f"phrase:{row.index}"
        hidden = row.reason == "hidden"
        title = HIDDEN_TEXT if hidden else f"{row.slot_name}: {', '.join(row.values)}"
        if row.index in review.added:
            cards.append(ProposedChange(key, KIND_PHRASE_SLOT, title, applied=True))
            continue
        if hidden or not row.offered:
            cards.append(
                ProposedChange(
                    key,
                    KIND_PHRASE_SLOT,
                    title,
                    effect="" if hidden else phrase_growth_line(row),
                    rationale="" if hidden else row.rationale,
                    reason=row.reason,
                    detail=phrase_detail_text(row),
                )
            )
            continue
        before, after = span_windows(context.sentence, span, row.slot_name)
        cards.append(
            ProposedChange(
                key,
                KIND_PHRASE_SLOT,
                title,
                before=before,
                after=after,
                effect=phrase_growth_line(row),
                rationale=row.rationale if is_visible(row.rationale) else HIDDEN_TEXT,
                examples=slot_examples(
                    replace_span(context.sentence, span, row.slot_name),
                    context.slots,
                    row.slot_name,
                    row.values,
                ),
            )
        )
    return tuple(cards)


@dataclass(slots=True)
class ApplyRecord:
    """One applied change and how to take it back. ``undo`` re-checks that the workspace still equals the state the apply
    produced and returns ``""`` on success or fixed refusal copy; it never raises for a changed workspace."""

    kind: str
    label: str
    pack_identity: int
    slot_index: int
    undo: Callable[[], str]


class ApplyJournal:
    """In-memory stack of applied changes. Never persisted; holds closures over workspace identities, not content."""

    def __init__(self) -> None:
        self._records: list[ApplyRecord] = []

    def __len__(self) -> int:
        return len(self._records)

    @property
    def last(self) -> ApplyRecord | None:
        return self._records[-1] if self._records else None

    def push(self, record: ApplyRecord) -> None:
        self._records.append(record)
        del self._records[: max(0, len(self._records) - MAX_JOURNAL)]

    def pop(self) -> ApplyRecord | None:
        return self._records.pop() if self._records else None

    def clear(self) -> None:
        self._records.clear()


__all__ = [
    "KIND_NEW_SLOT",
    "KIND_NOTE",
    "KIND_PHRASE_SLOT",
    "KIND_REMOVE_DUPLICATE",
    "KIND_VARIETY_VALUE",
    "MAX_JOURNAL",
    "ApplyJournal",
    "ApplyRecord",
    "ProposedChange",
    "marker_windows",
    "phrase_changes",
    "proposal_changes",
    "slot_examples",
    "span_windows",
    "variety_changes",
]
