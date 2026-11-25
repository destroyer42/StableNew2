"""Toolkit-neutral phrase to slot (AI-230g): the selected span, the deterministic judge and the review model.

A ``PHRASE_SLOT`` suggestion proposes a *new* matrix slot for one phrase the operator selected in the positive prompt: the model
gives a slot name and 2 to 5 alternatives; this module puts the operator's own phrase first, so the slot's first value is exactly
what was selected and the first compiled prompt reads exactly as the sentence did before. Applying one proposal replaces the
selected span, and nothing else, with ``[[slot_name]]``.

The model never judges its own output and never names a position: the span is the operator's selection, checked here against the
sentence read from the Prompt tab's workspace (whole words, one line, no protected token touched, a legal slot value). Every
proposal is judged here against the matrix state; one that fails any check is shown as rejected with its reason, never repaired,
trimmed or offered. The model's alternatives are never merged with, or written over, the selected phrase.

Pure: no Tk, no I/O.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import Any

from src.ai_assist.contracts import (
    MAX_PHRASE_CHARS,
    MAX_PROPOSAL_EXISTING_SLOTS,
    MAX_PROPOSAL_SENTENCE_CHARS,
    AssistRequest,
    AssistSuggestion,
    SuggestionKind,
)
from src.ai_assist.framing import PHRASE_RESERVED_MARKERS
from src.gui_v2.ai_slot_proposal import (
    REASON_TEXT as PROPOSAL_REASON_TEXT,
)
from src.gui_v2.ai_slot_proposal import (
    ProposalContext,
    matrix_growth,
    protected_spans,
    slot_name_problem,
)
from src.gui_v2.ai_slot_variety import (
    HIDDEN_TEXT,
    SlotState,
    matrix_state,
    near_key,
    value_key,
    value_problem,
)
from src.gui_v2.ai_slot_variety import (
    REASON_TEXT as VALUE_REASON_TEXT,
)
from src.utils.prompt_pack_utils import normalize_matrix_slot_name

PHRASE_LABEL = "Slot from a selected phrase (suggestions)"
PHRASE_NOTICE = (
    "Select a phrase in your positive prompt (whole words, on one line, no comma, bracket or marker), then press Suggest slot "
    "from phrase. Suggestions only. When you press Apply on ONE proposal, two things change in this pack: a new slot is added "
    "to the Matrix tab with your selected phrase as its FIRST value followed by the proposed alternatives, and exactly the "
    "selected words in your positive prompt are replaced by the marker [[slot_name]]; nothing else in the sentence is "
    "reworded. Because your phrase is the first value, the first compiled prompt reads exactly as the sentence did before. The "
    "pack becomes modified and unsaved. Nothing is saved, previewed, compiled, queued or generated, no existing slot or value "
    "is edited, and no model, workflow or setting is touched."
)
PHRASE_REVERT_TEXT = (
    "To undo an applied proposal: press Undo last (it works while nothing else in the pack has changed since), or delete the "
    "slot's row in the Matrix tab (its Delete button) and type your original words back in place of the [[slot_name]] marker."
)
PHRASE_UNVERIFIED = (
    "Model-proposed, not independently relevance-verified. You decide whether a slot is useful."
)
NO_PHRASE_TEXT = "No phrase selected. Drag over a few words in your positive prompt; the selection is shown here."
SELECTION_PREFIX = "Selected phrase: "
PHRASE_REVIEW_ACTIONS: tuple[str, ...] = ("add_slot_and_replace_phrase",)

#: Reasons only this feature reports; every other reason code is shared with new-slot proposals and value checks.
PHRASE_REASON_TEXT: dict[str, str] = {
    "value_repeats_phrase": "A proposed value repeats the selected phrase, which is already the slot's first value.",
    "phrase_taken": "The selected phrase was already replaced by an earlier addition.",
}
REASON_TEXT: dict[str, str] = {**PROPOSAL_REASON_TEXT, **PHRASE_REASON_TEXT}

STALE_TEXT = "The pack, its matrix or the prompt sentence changed since the request. Nothing was changed; request again."
UNREADABLE_TEXT = "The matrix, the selection or the prompt sentence could not be read safely."


@dataclass(frozen=True, slots=True)
class PhraseSpan:
    """The operator's selection: ``text`` is exactly ``sentence[start:end]``, trimmed of surrounding whitespace."""

    start: int
    end: int
    text: str = field(repr=False)


def trim_selection(sentence: str, start: int, end: int) -> PhraseSpan | None:
    """The selection ``[start, end)`` without surrounding whitespace, or ``None`` when nothing but whitespace (or an invalid
    range) is selected. Deterministic; never widens a selection."""

    if not 0 <= start < end <= len(sentence):
        return None
    chunk = sentence[start:end]
    lead = len(chunk) - len(chunk.lstrip())
    trail = len(chunk) - len(chunk.rstrip())
    if lead + trail >= len(chunk):
        return None
    start, end = start + lead, end - trail
    return PhraseSpan(start, end, sentence[start:end])


def _word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def span_problem(sentence: str, span: PhraseSpan) -> str:
    """Why ``span`` cannot become a slot, in words, or ``""``."""

    start, end, text = span.start, span.end, span.text
    if not 0 <= start < end <= len(sentence) or sentence[start:end] != text:
        return "The selection no longer matches the prompt. Select the phrase again."
    if not text.strip() or text != text.strip():
        return "Select a phrase of words, without leading or trailing spaces."
    if "\n" in text or "\r" in text:
        return "Select a phrase on one line."
    if len(text) > MAX_PHRASE_CHARS:
        return f"The selected phrase is longer than {MAX_PHRASE_CHARS} characters. Select a shorter phrase."
    if any(marker in text or marker in sentence for marker in PHRASE_RESERVED_MARKERS):
        return "The prompt or the selection contains a reserved marker word and cannot be sent."
    if any(s < end and e > start for s, e in protected_spans(sentence)):
        return "The selection touches a protected token (<lora:...>, [[marker]] or __wildcard__). Select plain words only."
    inner = value_problem(text)
    if inner:
        return f"The selected phrase cannot be a slot value: {VALUE_REASON_TEXT[inner]}"
    if start > 0 and _word_char(sentence[start - 1]) and _word_char(sentence[start]):
        return "The selection starts inside a word. Select whole words."
    if end < len(sentence) and _word_char(sentence[end - 1]) and _word_char(sentence[end]):
        return "The selection ends inside a word. Select whole words."
    return ""


def phrase_blocker(sentence: str, slots: Sequence[SlotState], span: PhraseSpan | None) -> str:
    """Why a phrase request cannot be built at all, or ``""``."""

    if not sentence.strip():
        return "Enter an authored positive prompt first."
    if len(sentence) > MAX_PROPOSAL_SENTENCE_CHARS:
        return f"The positive prompt is longer than {MAX_PROPOSAL_SENTENCE_CHARS} characters."
    if len(slots) > MAX_PROPOSAL_EXISTING_SLOTS:
        return "The pack has too many matrix slots for this request."
    if span is None:
        return NO_PHRASE_TEXT
    return span_problem(sentence, span)


def build_phrase_request(
    request_id: str,
    goal_text: str,
    sentence: str,
    span: PhraseSpan,
    slots: Sequence[SlotState],
    *,
    content_class: str,
) -> AssistRequest:
    """The only constructor of a phrase request: the optional goal, the sentence, the selected phrase and the existing slot
    names. Raises ``ValueError`` when a bound is not met."""

    blocker = phrase_blocker(sentence, slots, span)
    if blocker:
        raise ValueError(blocker)
    return AssistRequest(
        request_id,
        SuggestionKind.PHRASE_SLOT,
        positive_text=sentence,
        content_class=content_class,
        goal_text=goal_text.strip(),
        existing_slot_names=tuple(s.name for s in slots if s.name.strip()),
        phrase_text=span.text,
    )


def marker_text(slot_name: str) -> str:
    return f"[[{slot_name}]]"


def replace_span(sentence: str, span: PhraseSpan, slot_name: str) -> str:
    """``sentence`` with exactly the selected span replaced by the slot's marker. Nothing else changes, byte for byte."""

    return sentence[: span.start] + marker_text(slot_name) + sentence[span.end :]


def restore_span(sentence: str, span: PhraseSpan, slot_name: str) -> str:
    """The inverse of :func:`replace_span`: the marker at ``span.start`` replaced by the original phrase."""

    marker = marker_text(slot_name)
    return sentence[: span.start] + span.text + sentence[span.start + len(marker) :]


def with_phrase_applied(
    context: ProposalContext, span: PhraseSpan, slot_name: str, values: Sequence[str]
) -> ProposalContext:
    """The workspace state expected after the slot is added and the span replaced by its marker."""

    raw = [SimpleNamespace(name=s.name, values=list(s.values)) for s in context.slots]
    raw.append(SimpleNamespace(name=slot_name, values=list(values)))
    return replace(
        context,
        sentence=replace_span(context.sentence, span, slot_name),
        slots=matrix_state(raw),
    )


@dataclass(frozen=True, slots=True)
class PhraseRow:
    """One proposal and its verdict. ``values`` is the phrase first, then the model's alternatives; ``reason`` is empty exactly
    when it may be offered for acceptance."""

    index: int
    slot_name: str = field(repr=False)
    values: tuple[str, ...] = field(repr=False)
    rationale: str = field(repr=False)
    reason: str = ""
    growth: tuple[int, int, int] | None = None

    @property
    def offered(self) -> bool:
        return not self.reason


def _alternatives_problem(phrase: str, alternatives: Sequence[str]) -> str:
    phrase_near = near_key(phrase)
    earlier: set[str] = set()
    for text in alternatives:
        if value_problem(text):
            return "values_invalid"
        if near_key(text) == phrase_near:
            # The phrase is already the first value, so a repeat of it (or a near repeat) is the model's mistake, not a
            # value to be quietly dropped.
            return "value_repeats_phrase"
        if value_key(text) in earlier:
            return "values_invalid"
        earlier.add(value_key(text))
    return ""


def judge_phrase_slots(
    suggestion: AssistSuggestion,
    context: ProposalContext,
    span: PhraseSpan,
    *,
    matrix_mapping: Any,
    is_visible: Callable[[str], bool],
    phrase_taken: bool = False,
) -> tuple[PhraseRow, ...]:
    """Judge every proposal against ``context`` (the workspace state now). Deterministic; never repairs. ``phrase_taken`` is set
    once one proposal has replaced the span, after which no other proposal for it can be applied."""

    taken = Counter(normalize_matrix_slot_name(slot.name) for slot in context.slots)
    seen: set[str] = set()
    rows: list[PhraseRow] = []
    for index, entry in enumerate(suggestion.phrase_slots):
        name = entry.slot_name if isinstance(entry.slot_name, str) else ""
        alternatives = tuple(v if isinstance(v, str) else "" for v in entry.values)
        values = (span.text, *alternatives)
        key = normalize_matrix_slot_name(name)
        growth: tuple[int, int, int] | None = None
        reason = ""
        if not all(is_visible(t) for t in (name, entry.rationale, *alternatives)):
            reason = "hidden"
        else:
            reason = slot_name_problem(name)
            if not reason and taken.get(key):
                reason = "slot_name_exists"
            elif not reason and key in seen:
                reason = "slot_name_collision"
            if not reason:
                reason = _alternatives_problem(span.text, alternatives)
            if not reason and phrase_taken:
                reason = "phrase_taken"
            if not reason:
                growth = matrix_growth(matrix_mapping, name, values)
        if key and not slot_name_problem(name) and not taken.get(key):
            seen.add(key)
        rows.append(PhraseRow(index, name, values, entry.rationale, reason, growth))
    return tuple(rows)


def detail_text(row: PhraseRow) -> str:
    """The rejection reason in words; a value problem names the first failing rule."""

    if row.reason == "values_invalid":
        for text in row.values[1:]:
            inner = value_problem(text)
            if inner:
                return (
                    f"One of the proposed values breaks the value rules: {VALUE_REASON_TEXT[inner]}"
                )
        return REASON_TEXT["values_invalid"]
    return REASON_TEXT[row.reason]


def growth_line(row: PhraseRow) -> str:
    if row.growth is None:
        return ""
    now, after, limit = row.growth
    return (
        f"Possible combinations go from {now:,} to {after:,}; compiled per prompt row: "
        f"{min(after, limit):,} (limit {limit:,})."
    )


@dataclass(frozen=True, slots=True)
class PhraseReview:
    """What the dialog shows. ``rows`` are every proposal with its verdict; ``added`` the rows already applied."""

    status: str
    trust_label: str = ""
    rows: tuple[PhraseRow, ...] = field(default=(), repr=False)
    added: frozenset[int] = frozenset()
    notice: str = PHRASE_NOTICE
    revert: str = PHRASE_REVERT_TEXT
    actions: tuple[str, ...] = ()
    #: Change cards built by the Prompt tab owner (AI-230); empty when the caller supplies none.
    cards: tuple[Any, ...] = field(default=(), repr=False)

    @property
    def offered_rows(self) -> tuple[PhraseRow, ...]:
        return tuple(row for row in self.rows if row.offered and row.index not in self.added)


def phrase_review(
    rows: tuple[PhraseRow, ...], *, trust_label: str = "", added: frozenset[int] = frozenset()
) -> PhraseReview:
    offered = sum(row.offered and row.index not in added for row in rows)
    rejected = sum(not row.offered and row.index not in added for row in rows)
    status = f"{offered} proposal(s) can be applied, {rejected} rejected, {len(added)} applied."
    return PhraseReview(
        status=status,
        trust_label=trust_label,
        rows=rows,
        added=added,
        actions=PHRASE_REVIEW_ACTIONS if offered else (),
    )


def unavailable_phrase_review(status: str, *, trust_label: str = "") -> PhraseReview:
    return PhraseReview(status=status, trust_label=trust_label)


def phrase_text(review: PhraseReview) -> str:
    """Plain-text rendering for the read-only display (the dialog shows exactly this)."""

    lines = [review.notice, review.revert]
    if review.trust_label:
        lines.append(review.trust_label)
    lines += ["", review.status, "", PHRASE_UNVERIFIED]
    for row in review.rows:
        lines.append("")
        hidden = row.reason == "hidden"
        title = HIDDEN_TEXT if hidden else row.slot_name
        lines.append(f"Proposal {row.index + 1}: slot {title}")
        if hidden:
            lines.append(f"   [rejected] {REASON_TEXT['hidden']}")
            continue
        lines.append(f"   Values (your phrase first): {', '.join(row.values)}")
        lines.append(f"   Why (model's words): {row.rationale}")
        if row.index in review.added:
            lines.append("   [applied]")
        elif row.offered:
            lines.append(f"   [can apply] {growth_line(row)}")
        else:
            extra = f" {growth_line(row)}" if row.growth is not None else ""
            lines.append(f"   [rejected] {detail_text(row)}{extra}")
    return "\n".join(lines).rstrip()


__all__ = [
    "NO_PHRASE_TEXT",
    "PHRASE_LABEL",
    "PHRASE_NOTICE",
    "PHRASE_REASON_TEXT",
    "PHRASE_REVERT_TEXT",
    "PHRASE_REVIEW_ACTIONS",
    "PHRASE_UNVERIFIED",
    "REASON_TEXT",
    "SELECTION_PREFIX",
    "STALE_TEXT",
    "UNREADABLE_TEXT",
    "PhraseReview",
    "PhraseRow",
    "PhraseSpan",
    "SlotState",
    "build_phrase_request",
    "detail_text",
    "growth_line",
    "judge_phrase_slots",
    "marker_text",
    "phrase_blocker",
    "phrase_review",
    "phrase_text",
    "replace_span",
    "restore_span",
    "span_problem",
    "trim_selection",
    "unavailable_phrase_review",
    "with_phrase_applied",
]
