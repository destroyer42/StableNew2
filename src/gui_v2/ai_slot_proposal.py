"""Toolkit-neutral new-slot proposals (AI-213): insertion points, the deterministic judge and the review model.

A ``SLOT_PROPOSAL`` suggestion proposes a *new* matrix slot (name and starting values) and the position in the pack's positive
prompt sentence where its ``[[slot_name]]`` marker would go. The model never judges its own output and never names a position
itself: the closed list of insertion points is computed here from the sentence, and every proposal is checked here against the
matrix state and the sentence read from the Prompt tab's workspace. A proposal that fails any check is shown as rejected with
its reason, never repaired, trimmed or offered.

Adding a proposal is the operator's explicit, per-proposal action. The Prompt tab does it through the Matrix tab's and the
prompt editor's own edit paths (``MatrixTabPanel.append_slot`` and the editor insert); nothing here edits, saves, previews,
compiles or queues anything. The only change an accepted proposal makes to the sentence is the marker (plus at most one
separating space on each side of it).

Pure: no Tk, no I/O.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.ai_assist.contracts import (
    MAX_PROPOSAL_EXISTING_SLOTS,
    MAX_PROPOSAL_POINTS,
    MAX_PROPOSAL_SENTENCE_CHARS,
    MAX_PROPOSAL_SLOT_NAME_CHARS,
    MIN_PROPOSAL_VALUES,
    AssistRequest,
    AssistSuggestion,
    SuggestionKind,
)
from src.ai_assist.framing import PROPOSAL_RESERVED_MARKERS
from src.gui_v2.ai_slot_variety import (
    HIDDEN_TEXT,
    SlotState,
    matrix_state,
    value_key,
    value_problem,
)
from src.gui_v2.ai_slot_variety import (
    REASON_TEXT as VALUE_REASON_TEXT,
)
from src.pipeline.matrix_expansion_plan import plan_matrix_expansion
from src.prompting.prompt_compatibility import NON_PROSE_PATTERN
from src.utils.prompt_pack_utils import normalize_matrix_slot_name

PROPOSAL_LABEL = "New matrix slot (suggestions)"
PROPOSAL_NOTICE = (
    "Suggestions only. When you press Apply on ONE proposal, two things change in this pack: a new "
    "slot with its values is added to the Matrix tab, and the marker [[slot_name]] is inserted at the position shown in "
    "your positive prompt sentence (with at most one separating space on each side); nothing else in the sentence is "
    "reworded. The pack becomes modified and unsaved. Nothing is saved, previewed, compiled, queued or generated, no "
    "existing slot or value is edited, and no model, workflow or setting is touched."
)
#: Slot plus marker are two edits (a Matrix row and a prompt-editor insert) and neither editor keeps an undo stack, so the
#: window keeps its own in-memory journal (AI-230): Undo last takes back the most recent addition while nothing else changed.
PROPOSAL_REVERT_TEXT = (
    "To undo an added proposal: press Undo last (it works while nothing else in the pack has changed since), or delete "
    "the slot's row in the Matrix tab (its Delete button) and the [[slot_name]] marker from the prompt sentence (and a "
    "separating space, if one was added)."
)
PROPOSAL_REVIEW_ACTIONS: tuple[str, ...] = ("add_slot_and_place_marker",)
PROPOSAL_UNVERIFIED = (
    "Model-proposed, not independently relevance-verified. You decide whether a slot is useful."
)
STALE_TEXT = "The pack, its matrix or the prompt sentence changed since the request. Nothing was changed; request again."
UNREADABLE_TEXT = "The matrix or the prompt sentence could not be read safely."

REASON_TEXT: dict[str, str] = {
    "hidden": "Hidden by the current visibility mode.",
    "slot_name_empty": "The slot name is empty.",
    "slot_name_whitespace": "The slot name starts or ends with a space.",
    "slot_name_too_long": f"The slot name is longer than {MAX_PROPOSAL_SLOT_NAME_CHARS} characters.",
    "slot_name_chars": "The slot name has a line break, comma, bracket, < or >, __ or a reserved marker.",
    "slot_name_exists": "A slot with this name (ignoring case, spaces and punctuation) already exists.",
    "slot_name_collision": "Another proposal uses the same slot name; only the first is offered.",
    "values_invalid": "One of the proposed values breaks the value rules.",
    "point_taken": "That position already received a marker from an earlier addition.",
    "point_protected": "That position is inside a protected token.",
    **{f"value:{key}": f"Value problem: {text}" for key, text in VALUE_REASON_TEXT.items()},
}

_WILDCARD = re.compile(r"__[^_\s][^\n]*?__")
_DELIMITERS = ",;."
_SNIPPET_SIDE = 30
HERE = "|HERE|"


@dataclass(frozen=True, slots=True)
class InsertionPoint:
    """A closed-list position: character ``offset`` in the sentence and the snippet shown to the model and the operator."""

    offset: int
    snippet: str


def _protected_spans(text: str) -> list[tuple[int, int]]:
    return [
        (match.start(), match.end())
        for pattern in (NON_PROSE_PATTERN, _WILDCARD)
        for match in pattern.finditer(text)
    ]


def inside_protected_token(text: str, offset: int) -> bool:
    """Whether ``offset`` falls strictly inside ``<lora:...>``/``<embedding...>``, ``[[slot]]`` or ``__wildcard__``."""

    return any(start < offset < end for start, end in _protected_spans(text))


def _snippet(text: str, offset: int) -> str:
    before = text[max(0, offset - _SNIPPET_SIDE) : offset]
    after = text[offset : offset + _SNIPPET_SIDE]
    lead = "…" if offset > _SNIPPET_SIDE else ""
    tail = "…" if offset + _SNIPPET_SIDE < len(text) else ""
    return " ".join(f"{lead}{before}{HERE}{after}{tail}".split())


def compute_insertion_points(sentence: str) -> tuple[InsertionPoint, ...]:
    """Positions between clauses: just before each ``,`` ``;`` ``.`` and at the end of the text. Never inside a protected
    token. At most :data:`MAX_PROPOSAL_POINTS`, evenly sampled when there are more. Deterministic."""

    spans = _protected_spans(sentence)
    offsets: list[int] = []
    for position, char in enumerate(sentence):
        if char in _DELIMITERS and position > 0 and sentence[:position].strip():
            offsets.append(position)
    end = len(sentence.rstrip())
    if end and sentence[end - 1] not in _DELIMITERS:
        offsets.append(end)
    offsets = sorted({o for o in offsets if not any(s < o < e for s, e in spans)})
    if len(offsets) > MAX_PROPOSAL_POINTS:
        last = len(offsets) - 1
        offsets = [
            offsets[round(i * last / (MAX_PROPOSAL_POINTS - 1))] for i in range(MAX_PROPOSAL_POINTS)
        ]
        offsets = sorted(set(offsets))
    return tuple(InsertionPoint(offset, _snippet(sentence, offset)) for offset in offsets)


def marker_insertion(sentence: str, offset: int, slot_name: str) -> str:
    """The exact text inserted at ``offset``: the marker, plus one space on a side only where it would otherwise be glued
    to a neighbouring word. Removing it restores the sentence exactly."""

    before = sentence[offset - 1] if offset > 0 else ""
    after = sentence[offset] if offset < len(sentence) else ""
    lead = " " if before and not before.isspace() and before not in "(" else ""
    trail = " " if after and not after.isspace() and after not in _DELIMITERS + ")" else ""
    return f"{lead}[[{slot_name}]]{trail}"


def place_marker(sentence: str, offset: int, slot_name: str) -> str:
    return sentence[:offset] + marker_insertion(sentence, offset, slot_name) + sentence[offset:]


@dataclass(frozen=True, slots=True)
class ProposalContext:
    """What a new-slot request was built from. Acceptance requires the workspace to still equal it (plus what this review
    has already added)."""

    pack_identity: int
    matrix_identity: int
    slot_index: int
    sentence: str = field(repr=False)
    slots: tuple[SlotState, ...] = field(repr=False)
    #: Current character offset of each closed-list point; ``-1`` once a marker was placed there.
    offsets: tuple[int, ...] = field(repr=False)
    visibility_mode: str = ""

    def with_proposal_added(
        self, point: int, slot_name: str, values: Sequence[str]
    ) -> ProposalContext:
        """The state expected after the slot is added and its marker placed at closed-list ``point``."""

        offset = self.offsets[point]
        inserted = marker_insertion(self.sentence, offset, slot_name)
        shifted = tuple(
            -1 if i == point or o == offset else (o + len(inserted) if o > offset else o)
            for i, o in enumerate(self.offsets)
        )
        raw = [_Raw(s.name, list(s.values)) for s in self.slots] + [_Raw(slot_name, list(values))]
        return ProposalContext(
            self.pack_identity,
            self.matrix_identity,
            self.slot_index,
            place_marker(self.sentence, offset, slot_name),
            matrix_state(raw),
            shifted,
            self.visibility_mode,
        )


@dataclass(frozen=True, slots=True)
class _Raw:
    name: str
    values: list[Any]


def build_context(
    pack_identity: int,
    matrix_identity: int,
    slot_index: int,
    sentence: str,
    matrix_slots: Sequence[Any],
    points: Sequence[InsertionPoint],
    visibility_mode: str,
) -> ProposalContext:
    return ProposalContext(
        pack_identity,
        matrix_identity,
        slot_index,
        sentence,
        matrix_state(matrix_slots),
        tuple(p.offset for p in points),
        visibility_mode,
    )


def proposal_blocker(sentence: str, slots: Sequence[SlotState]) -> str:
    """Why a request cannot be built at all, or ``""``."""

    if not sentence.strip():
        return "Enter an authored positive prompt first."
    if len(sentence) > MAX_PROPOSAL_SENTENCE_CHARS:
        return f"The positive prompt is longer than {MAX_PROPOSAL_SENTENCE_CHARS} characters."
    if len(slots) > MAX_PROPOSAL_EXISTING_SLOTS:
        return "The pack has too many matrix slots for this request."
    if not compute_insertion_points(sentence):
        return "The positive prompt has no safe place for a new marker."
    return ""


def build_proposal_request(
    request_id: str,
    goal_text: str,
    sentence: str,
    slots: Sequence[SlotState],
    *,
    content_class: str,
) -> tuple[AssistRequest, tuple[InsertionPoint, ...]]:
    """The only constructor of a new-slot request: the goal, the sentence, the existing slot names and the closed list of
    insertion points. Raises ``ValueError`` when a bound is not met."""

    blocker = proposal_blocker(sentence, slots)
    if blocker:
        raise ValueError(blocker)
    points = compute_insertion_points(sentence)
    request = AssistRequest(
        request_id,
        SuggestionKind.SLOT_PROPOSAL,
        positive_text=sentence,
        content_class=content_class,
        goal_text=goal_text,
        existing_slot_names=tuple(s.name for s in slots if s.name.strip()),
        insertion_points=tuple(p.snippet for p in points),
    )
    return request, points


def matrix_growth(mapping: Any, new_name: str, new_values: Sequence[str]) -> tuple[int, int, int]:
    """``(A, B, limit)``: the matrix's combination count now, with the proposed slot added, and the limit in effect. Uses the
    pipeline's own planner on a copy; the matrix is shown as if enabled, like the Matrix tab's own counts."""

    base = dict(mapping) if isinstance(mapping, Mapping) else {}
    slots = list(base.get("slots", [])) if isinstance(base.get("slots", []), list | tuple) else []
    now = plan_matrix_expansion({**base, "enabled": True, "slots": slots})
    after = plan_matrix_expansion(
        {**base, "enabled": True, "slots": [*slots, {"name": new_name, "values": list(new_values)}]}
    )
    return now.theoretical_count, after.theoretical_count, now.effective_limit


def _name_problem(name: str) -> str:
    if not name.strip():
        return "slot_name_empty"
    if name != name.strip():
        return "slot_name_whitespace"
    if len(name) > MAX_PROPOSAL_SLOT_NAME_CHARS:
        return "slot_name_too_long"
    if (
        any(ord(c) < 32 or ord(c) == 127 for c in name)
        or any(c in name for c in ",[]<>")
        or "__" in name
        or any(marker in name for marker in PROPOSAL_RESERVED_MARKERS)
        or not normalize_matrix_slot_name(name)
    ):
        return "slot_name_chars"
    return ""


@dataclass(frozen=True, slots=True)
class ProposalRow:
    """One proposal and its verdict. ``reason`` is empty exactly when it may be offered for acceptance."""

    index: int
    slot_name: str = field(repr=False)
    values: tuple[str, ...] = field(repr=False)
    point: int
    snippet: str = field(repr=False)
    rationale: str = field(repr=False)
    reason: str = ""
    growth: tuple[int, int, int] | None = None

    @property
    def offered(self) -> bool:
        return not self.reason


def judge_proposals(
    suggestion: AssistSuggestion,
    request: AssistRequest,
    context: ProposalContext,
    *,
    matrix_mapping: Any,
    is_visible: Callable[[str], bool],
) -> tuple[ProposalRow, ...]:
    """Judge every proposal against ``context`` (the workspace state now). Deterministic; never repairs."""

    taken = Counter(normalize_matrix_slot_name(slot.name) for slot in context.slots)
    seen: set[str] = set()
    rows: list[ProposalRow] = []
    for index, entry in enumerate(suggestion.slot_proposals):
        name = entry.slot_name if isinstance(entry.slot_name, str) else ""
        values = tuple(v if isinstance(v, str) else "" for v in entry.values)
        point = entry.insertion_point
        in_list = (
            isinstance(point, int)
            and not isinstance(point, bool)
            and 0 <= point < min(len(request.insertion_points), len(context.offsets))
        )
        snippet = request.insertion_points[point] if in_list else ""
        key = normalize_matrix_slot_name(name)
        growth: tuple[int, int, int] | None = None
        reason = ""
        if not all(is_visible(t) for t in (name, entry.rationale, *values)):
            reason = "hidden"
        elif not in_list:
            reason = "point_invalid"
        else:
            reason = _name_problem(name)
            if not reason and taken.get(key):
                reason = "slot_name_exists"
            elif not reason and key in seen:
                reason = "slot_name_collision"
            if not reason:
                reason = _values_problem(values)
            if not reason:
                offset = context.offsets[point]
                if offset < 0:
                    reason = "point_taken"
                elif offset > len(context.sentence) or inside_protected_token(
                    context.sentence, offset
                ):
                    reason = "point_protected"
            if not reason:
                # AI-230a: growth is information, never a verdict. The matrix limit only caps how many combinations
                # compile per prompt row (``selected = min(possible, limit)``); a matrix already past it must still be
                # able to take a new slot.
                growth = matrix_growth(matrix_mapping, name, values)
        if key and not _name_problem(name) and not (taken.get(key)):
            seen.add(key)
        rows.append(
            ProposalRow(
                index,
                name,
                values,
                point if in_list else -1,
                snippet,
                entry.rationale,
                reason,
                growth,
            )
        )
    return tuple(rows)


def _values_problem(values: Sequence[str]) -> str:
    if len(values) < MIN_PROPOSAL_VALUES:
        return "values_invalid"
    earlier: set[str] = set()
    for text in values:
        problem = value_problem(text)
        if problem or value_key(text) in earlier:
            return "values_invalid"
        earlier.add(value_key(text))
    return ""


def _first_value_problem(values: Sequence[str]) -> str:
    earlier: set[str] = set()
    for text in values:
        problem = value_problem(text)
        if problem:
            return problem
        if value_key(text) in earlier:
            return "duplicate_suggestion"
        earlier.add(value_key(text))
    return ""


def detail_text(row: ProposalRow) -> str:
    """The rejection reason in words; a value problem names the first failing rule."""

    if row.reason == "values_invalid":
        inner = _first_value_problem(row.values)
        if inner:
            return f"One of the proposed values breaks the value rules: {VALUE_REASON_TEXT[inner]}"
        return REASON_TEXT["values_invalid"]
    if row.reason == "point_invalid":
        return "The model named a position that is not in the list."
    return REASON_TEXT[row.reason]


@dataclass(frozen=True, slots=True)
class ProposalReview:
    """What the dialog shows. ``rows`` are every proposal with its verdict; ``added`` the rows already added."""

    status: str
    trust_label: str = ""
    rows: tuple[ProposalRow, ...] = field(default=(), repr=False)
    added: frozenset[int] = frozenset()
    notice: str = PROPOSAL_NOTICE
    revert: str = PROPOSAL_REVERT_TEXT
    actions: tuple[str, ...] = ()
    #: Change cards built by the Prompt tab owner (AI-230); empty when the caller supplies none.
    cards: tuple[Any, ...] = field(default=(), repr=False)

    @property
    def offered_rows(self) -> tuple[ProposalRow, ...]:
        return tuple(row for row in self.rows if row.offered and row.index not in self.added)


def proposal_review(
    rows: tuple[ProposalRow, ...],
    *,
    trust_label: str = "",
    added: frozenset[int] = frozenset(),
) -> ProposalReview:
    offered = sum(row.offered and row.index not in added for row in rows)
    rejected = sum(not row.offered and row.index not in added for row in rows)
    status = f"{offered} proposal(s) can be added, {rejected} rejected, {len(added)} added."
    return ProposalReview(
        status=status,
        trust_label=trust_label,
        rows=rows,
        added=added,
        actions=PROPOSAL_REVIEW_ACTIONS if offered else (),
    )


def unavailable_proposal_review(status: str, *, trust_label: str = "") -> ProposalReview:
    return ProposalReview(status=status, trust_label=trust_label)


def offered_label(row: ProposalRow) -> str:
    return f"{row.slot_name}: {', '.join(row.values)}"


def growth_line(row: ProposalRow) -> str:
    if row.growth is None:
        return ""
    now, after, limit = row.growth
    return (
        f"Possible combinations go from {now:,} to {after:,}; compiled per prompt row: "
        f"{min(after, limit):,} (limit {limit:,})."
    )


def proposal_text(review: ProposalReview) -> str:
    """Plain-text rendering for the read-only display (the dialog shows exactly this)."""

    lines = [review.notice, review.revert]
    if review.trust_label:
        lines.append(review.trust_label)
    lines += ["", review.status, "", PROPOSAL_UNVERIFIED]
    for row in review.rows:
        lines.append("")
        hidden = row.reason == "hidden"
        title = HIDDEN_TEXT if hidden else row.slot_name
        lines.append(f"Proposal {row.index + 1}: slot {title}")
        if hidden:
            lines.append(f"   [rejected] {REASON_TEXT['hidden']}")
            continue
        lines.append(f"   Values: {', '.join(row.values)}")
        lines.append(f"   Marker position: {row.snippet or '(none)'}")
        lines.append(f"   Why (model's words): {row.rationale}")
        if row.index in review.added:
            lines.append("   [added]")
        elif row.offered:
            lines.append(f"   [can add] {growth_line(row)}")
        else:
            extra = f" {growth_line(row)}" if row.growth is not None else ""
            lines.append(f"   [rejected] {detail_text(row)}{extra}")
    return "\n".join(lines).rstrip()


__all__ = [
    "HERE",
    "PROPOSAL_LABEL",
    "PROPOSAL_NOTICE",
    "PROPOSAL_REVERT_TEXT",
    "PROPOSAL_REVIEW_ACTIONS",
    "PROPOSAL_UNVERIFIED",
    "REASON_TEXT",
    "STALE_TEXT",
    "UNREADABLE_TEXT",
    "InsertionPoint",
    "ProposalContext",
    "ProposalReview",
    "ProposalRow",
    "build_context",
    "build_proposal_request",
    "compute_insertion_points",
    "detail_text",
    "growth_line",
    "inside_protected_token",
    "judge_proposals",
    "marker_insertion",
    "matrix_growth",
    "matrix_state",
    "offered_label",
    "place_marker",
    "proposal_blocker",
    "proposal_review",
    "proposal_text",
    "unavailable_proposal_review",
]
