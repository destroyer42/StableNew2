"""Toolkit-neutral slot variety (AI-212): the matrix snapshot, the deterministic per-value judge and the review model.

A ``SLOT_VARIETY`` suggestion proposes new values for the pack's *existing* matrix slots. The model never judges its own
output: every proposed value is checked here against the matrix state read from the Prompt tab's workspace (the one
authority, ``PromptWorkspaceState.get_matrix_config()``), and a value that fails any check is shown as rejected with its
reason, never repaired, trimmed or offered. Adding an offered value is the operator's explicit, per-value action and goes
through the Matrix editor's own edit path (``MatrixTabPanel.append_slot_value``); nothing here edits, saves, compiles or
queues anything, creates a slot, or touches an existing value or the prompt sentence.

Pure: no Tk, no I/O.
"""

from __future__ import annotations

import copy
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from src.ai_assist.contracts import (
    DEFAULT_VARIETY_PER_SLOT,
    MAX_VARIETY_NEW_VALUES,
    MAX_VARIETY_REQUESTED_TOTAL,
    MAX_VARIETY_SLOTS,
    MAX_VARIETY_VALUE_CHARS,
    VARIETY_ANSWER_TOKEN_BUDGET,
    VARIETY_FOCUS_DIRECT,
    VARIETY_FOCUS_EXPLORE,
    VARIETY_FOCUS_MODES,
    AssistRequest,
    AssistSuggestion,
    SuggestionKind,
    variety_answer_tokens,
)
from src.ai_assist.framing import VARIETY_RESERVED_MARKERS
from src.utils.prompt_pack_utils import matrix_slot_round_trips as slot_round_trips
from src.utils.prompt_pack_utils import normalize_matrix_slot_name

VARIETY_LABEL = "Matrix slot variety (suggestions)"
VARIETY_NOTICE = (
    "Suggestions only. A value is added to its matrix slot only when you press Apply on it (Apply selected and Apply all offered press it for each card in turn), and it "
    "is added exactly as if you had typed it at the end of that slot in the Matrix tab: the pack becomes modified and "
    "unsaved. No slot is created, no existing value or prompt is changed, and nothing is saved, queued or generated. "
    "Values can only be suggested for slots that already exist in this pack's Matrix tab (listed below); to use a new "
    "slot, add it in the Matrix tab first."
)
VARIETY_REFUSED_HINT = (
    " If your goal does not fit any slot listed above, add a fitting slot in the Matrix tab and try again, or "
    "describe the goal in terms of an existing slot."
)
#: The complete set of things a variety review lets the operator do.
VARIETY_REVIEW_ACTIONS: tuple[str, ...] = ("add_selected_value",)

REASON_TEXT: dict[str, str] = {
    "slot_missing": "This slot no longer exists in the pack.",
    "slot_not_editable": "This slot cannot take a value without changing its existing values or name.",
    "hidden": "Hidden by the current visibility mode.",
    "empty": "The value is empty.",
    "surrounding_whitespace": "The value starts or ends with a space.",
    "too_long": f"Longer than {MAX_VARIETY_VALUE_CHARS} characters.",
    "line_break": "Contains a line break or control character.",
    "comma": "Contains a comma, which would split it into several values.",
    "matrix_marker": "Contains [ or ], which the matrix uses for [[slot]] markers.",
    "angle_token": "Contains < or >, which prompts use for LoRA and embedding tokens.",
    "wildcard_marker": "Contains __, which prompts use for wildcard tokens.",
    "reserved_marker": "Contains a reserved AI Assist marker.",
    "duplicate_existing": "Already a value of this slot.",
    "duplicate_suggestion": "Suggested more than once for this slot.",
}
HIDDEN_TEXT = "(hidden by the current visibility mode)"
#: Control characters and line/paragraph separators: a slot's Values entry is one line.
_BREAKING_CATEGORIES = frozenset({"Cc", "Cs", "Co", "Cn", "Zl", "Zp"})


@dataclass(frozen=True, slots=True)
class SlotState:
    """One matrix slot as read from the workspace. ``values`` keeps the stored objects (deep-copied) so any change shows."""

    name: str
    values: tuple[Any, ...] = field(repr=False)
    #: Unique, non-empty name and a name/value list that survives the Matrix editor's re-parse unchanged.
    editable: bool


@dataclass(frozen=True, slots=True)
class VarietyContext:
    """Identity of what a slot-variety request was built from. Acceptance requires the workspace to still equal it."""

    pack_identity: int
    matrix_identity: int
    slots: tuple[SlotState, ...] = field(repr=False)
    visibility_mode: str

    @property
    def excluded_count(self) -> int:
        return sum(not slot.editable for slot in self.slots)

    def with_value_added(self, index: int, value: str) -> VarietyContext:
        """The state expected after ``value`` is appended to slot ``index`` through the Matrix editor."""

        slot = self.slots[index]
        values = (*slot.values, value)
        changed = SlotState(
            slot.name, values, slot.editable and slot_round_trips(slot.name, list(values))
        )
        return replace(self, slots=(*self.slots[:index], changed, *self.slots[index + 1 :]))


def matrix_state(slots: Sequence[Any]) -> tuple[SlotState, ...]:
    """Snapshot ``MatrixSlot``-like objects (``name``, ``values``) without keeping a reference to them."""

    raw = [(getattr(slot, "name", ""), list(getattr(slot, "values", []) or [])) for slot in slots]
    keys = [
        normalize_matrix_slot_name(name) if isinstance(name, str) else "" for name, _values in raw
    ]
    counts = Counter(keys)
    return tuple(
        SlotState(
            name if isinstance(name, str) else str(name),
            tuple(copy.deepcopy(values)),
            bool(key) and counts[key] == 1 and slot_round_trips(name, values),
        )
        for (name, values), key in zip(raw, keys, strict=True)
    )


FOCUS_LABELS: dict[str, str] = {
    VARIETY_FOCUS_DIRECT: "Directly supports the goal",
    VARIETY_FOCUS_EXPLORE: "Explore related variations",
}
UNVERIFIED_LABEL = (
    "Model-proposed, not independently relevance-verified. You decide whether a value is useful."
)
NO_SELECTION_TEXT = "Select at least one target slot first."
SLOT_DISABLED_REASON = "needs a unique name and text values without commas"


def selected_slot_names(slots: Sequence[SlotState], chosen: Sequence[str]) -> tuple[str, ...]:
    """Validate an operator selection against the matrix state. Fails closed with ``ValueError``; never truncates."""

    if not chosen:
        raise ValueError(NO_SELECTION_TEXT)
    if len(set(chosen)) != len(chosen):
        raise ValueError("A slot was selected more than once.")
    if len(chosen) > MAX_VARIETY_SLOTS:
        raise ValueError(f"Select at most {MAX_VARIETY_SLOTS} slots.")
    editable = {slot.name for slot in slots if slot.editable}
    if any(name not in editable for name in chosen):
        raise ValueError("A selected slot is no longer available. Review the target slots.")
    return tuple(chosen)


def check_variety_quantity(per_slot: Any, slot_count: int) -> int:
    """The per-slot count (a whole number, 1 to 6) and the aggregate bound, checked before any inference."""

    if (
        isinstance(per_slot, bool)
        or not isinstance(per_slot, int)
        or not 1 <= per_slot <= MAX_VARIETY_NEW_VALUES
    ):
        raise ValueError(
            f"Suggestions per slot must be a whole number from 1 to {MAX_VARIETY_NEW_VALUES}."
        )
    total = per_slot * slot_count
    if total > MAX_VARIETY_REQUESTED_TOTAL:
        raise ValueError(
            f"{total} values requested; at most {MAX_VARIETY_REQUESTED_TOTAL} per request. "
            "Reduce the suggestions per slot or the selected slots."
        )
    if variety_answer_tokens(slot_count, per_slot) > VARIETY_ANSWER_TOKEN_BUDGET:
        raise ValueError(
            f"{total} values over {slot_count} slots could exceed the model's answer budget. "
            "Reduce the suggestions per slot or the selected slots."
        )
    return per_slot


def build_variety_request(
    request_id: str,
    goal_text: str,
    slots: Sequence[SlotState],
    *,
    content_class: str,
    selected: Sequence[str],
    per_slot: int = DEFAULT_VARIETY_PER_SLOT,
    focus: str = VARIETY_FOCUS_DIRECT,
) -> AssistRequest:
    """The only constructor of a slot-variety request: the goal plus the explicitly selected editable slots, nothing else
    (no model list, no stage list, no prompt, no unselected slot). Raises ``ValueError`` when a bound is not met."""

    names = selected_slot_names(slots, selected)
    check_variety_quantity(per_slot, len(names))
    if focus not in VARIETY_FOCUS_MODES:
        raise ValueError("Unsupported goal focus.")
    by_name = {slot.name: slot for slot in slots if slot.editable}
    return AssistRequest(
        request_id,
        SuggestionKind.SLOT_VARIETY,
        content_class=content_class,
        goal_text=goal_text,
        matrix_slots=tuple(
            (name, tuple(str(value) for value in by_name[name].values)) for name in names
        ),
        variety_per_slot=per_slot,
        variety_focus=focus,
    )


@dataclass(frozen=True, slots=True)
class SlotCoverage:
    slot: str
    requested: int
    returned: int
    eligible: int
    rejected: int
    added: int

    @property
    def missing(self) -> int:
        return max(0, self.requested - self.returned)


@dataclass(frozen=True, slots=True)
class VarietyCoverage:
    """Deterministic counts for a structurally valid answer. Says nothing about semantic relevance."""

    focus: str
    slots: tuple[SlotCoverage, ...]

    @property
    def requested(self) -> int:
        return sum(s.requested for s in self.slots)

    @property
    def returned(self) -> int:
        return sum(s.returned for s in self.slots)

    @property
    def eligible(self) -> int:
        return sum(s.eligible for s in self.slots)

    @property
    def rejected(self) -> int:
        return sum(s.rejected for s in self.slots)

    @property
    def added(self) -> int:
        return sum(s.added for s in self.slots)

    @property
    def missing(self) -> int:
        return sum(s.missing for s in self.slots)

    @property
    def partial(self) -> bool:
        return self.missing > 0


def variety_coverage(
    request: AssistRequest, rows: Sequence[VarietyRow], *, added: frozenset[int] = frozenset()
) -> VarietyCoverage:
    """Per selected slot: requested, returned, eligible (offered and not yet added), rejected and added counts. A selected
    slot the model omitted reports ``0 returned``. Rows for slots outside the request cannot occur (the validator's closed
    list) and are ignored."""

    out: list[SlotCoverage] = []
    for name, _existing in request.matrix_slots:
        mine = [row for row in rows if row.slot == name]
        out.append(
            SlotCoverage(
                name,
                request.variety_per_slot,
                len(mine),
                sum(row.offered for row in mine),
                sum(not row.offered for row in mine),
                sum(row.index in added for row in mine),
            )
        )
    return VarietyCoverage(request.variety_focus, tuple(out))


def coverage_status(coverage: VarietyCoverage) -> str:
    """One compact line. Partial coverage is named; a full count is never presented as verified relevance."""

    line = f"{coverage.returned} of {coverage.requested} requested values returned"
    if coverage.partial:
        return f"Partial coverage: {line}. Review the available suggestions or adjust the scope and request again."
    return f"Requested count returned ({line}); relevance is not verified."


def coverage_lines(coverage: VarietyCoverage) -> list[str]:
    mode = "Direct" if coverage.focus == VARIETY_FOCUS_DIRECT else "Explore"
    per = coverage.slots[0].requested if coverage.slots else 0
    lines = [
        f"Mode: {mode}",
        f"Selected slots: {', '.join(s.slot for s in coverage.slots)}",
        f"Requested: {per} per slot / {coverage.requested} total",
        "",
        "Coverage:",
    ]
    for slot in coverage.slots:
        lines.append(
            f"{slot.slot}  {slot.requested} requested / {slot.returned} returned / {slot.eligible} eligible"
        )
    lines += [
        "",
        "Overall:",
        f"{coverage.requested} requested",
        f"{coverage.returned} returned",
        f"{coverage.eligible} eligible",
        f"{coverage.rejected} rejected",
        f"{coverage.added} added",
    ]
    if coverage.partial:
        lines += [
            "",
            "PARTIAL COVERAGE",
            f"{coverage.missing} requested value(s) were not returned.",
        ]
    return lines


def value_key(text: str) -> str:
    """Duplicate key: case-insensitive, whitespace collapsed."""

    return " ".join(str(text).split()).casefold()


def _format_problem(value: str) -> str:
    if not value.strip():
        return "empty"
    if value != value.strip():
        return "surrounding_whitespace"
    if len(value) > MAX_VARIETY_VALUE_CHARS:
        return "too_long"
    if any(unicodedata.category(char) in _BREAKING_CATEGORIES for char in value):
        return "line_break"
    if "," in value:
        return "comma"
    if "[" in value or "]" in value:
        return "matrix_marker"
    if "<" in value or ">" in value:
        return "angle_token"
    if "__" in value:
        return "wildcard_marker"
    if any(marker in value for marker in VARIETY_RESERVED_MARKERS):
        return "reserved_marker"
    return ""


#: Public name for the per-value format rules, shared with the new-slot proposal judge (AI-213).
value_problem = _format_problem


@dataclass(frozen=True, slots=True)
class VarietyRow:
    """One proposed value and its verdict. ``reason`` is empty exactly when the value may be offered for acceptance."""

    index: int
    slot: str
    value: str = field(repr=False)
    reason: str = ""

    @property
    def offered(self) -> bool:
        return not self.reason


def judge_variety(
    suggestion: AssistSuggestion,
    slots: Sequence[SlotState],
    *,
    is_visible: Callable[[str], bool],
) -> tuple[VarietyRow, ...]:
    """Judge every proposed value against ``slots`` (the workspace state now). Deterministic; never repairs."""

    by_name: dict[str, list[SlotState]] = {}
    for slot in slots:
        by_name.setdefault(slot.name, []).append(slot)
    rows: list[VarietyRow] = []
    for entry in suggestion.slot_values:
        matches = by_name.get(entry.slot, [])
        existing = {value_key(value) for slot in matches for value in slot.values}
        earlier: set[str] = set()
        for value in entry.values:
            text = value if isinstance(value, str) else ""
            if not matches:
                reason = "slot_missing"
            elif len(matches) != 1 or not matches[0].editable:
                reason = "slot_not_editable"
            elif not is_visible(text):
                reason = "hidden"
            else:
                reason = _format_problem(text)
                if not reason and value_key(text) in existing:
                    reason = "duplicate_existing"
                elif not reason and value_key(text) in earlier:
                    reason = "duplicate_suggestion"
            if text.strip():
                earlier.add(value_key(text))
            rows.append(VarietyRow(len(rows), entry.slot, text, reason))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class VarietyReview:
    """What the dialog shows. ``rows`` are every proposal with its verdict; ``added`` the rows already added."""

    status: str
    trust_label: str = ""
    rows: tuple[VarietyRow, ...] = field(default=(), repr=False)
    #: ``(slot, rationale)`` in answer order; a hidden rationale is replaced by :data:`HIDDEN_TEXT`.
    rationales: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    added: frozenset[int] = frozenset()
    notice: str = VARIETY_NOTICE
    actions: tuple[str, ...] = ()
    coverage: VarietyCoverage | None = field(default=None, repr=False)
    #: Change cards built by the Prompt tab owner (AI-230); empty when the caller supplies none.
    cards: tuple[Any, ...] = field(default=(), repr=False)

    @property
    def coverage_line(self) -> str:
        return coverage_status(self.coverage) if self.coverage is not None else ""

    @property
    def offered_rows(self) -> tuple[VarietyRow, ...]:
        return tuple(row for row in self.rows if row.offered and row.index not in self.added)


def variety_review(
    rows: tuple[VarietyRow, ...],
    suggestion: AssistSuggestion,
    *,
    is_visible: Callable[[str], bool],
    trust_label: str = "",
    added: frozenset[int] = frozenset(),
    excluded_count: int = 0,
    request: AssistRequest | None = None,
) -> VarietyReview:
    offered = sum(row.offered and row.index not in added for row in rows)
    rejected = sum(not row.offered and row.index not in added for row in rows)
    status = f"{offered} value(s) can be added, {rejected} rejected, {len(added)} added."
    coverage = variety_coverage(request, rows, added=added) if request is not None else None
    if coverage is not None:
        status = f"{coverage_status(coverage)} {status}"
    if excluded_count:
        status += f" {excluded_count} slot(s) were not offered: a unique name and text values without commas are needed."
    return VarietyReview(
        status=status,
        trust_label=trust_label,
        rows=rows,
        rationales=tuple(
            (entry.slot, entry.rationale if is_visible(entry.rationale) else HIDDEN_TEXT)
            for entry in suggestion.slot_values
        ),
        added=added,
        actions=VARIETY_REVIEW_ACTIONS if offered else (),
        coverage=coverage,
    )


def unavailable_variety_review(status: str, *, trust_label: str = "") -> VarietyReview:
    return VarietyReview(status=status, trust_label=trust_label)


def offered_label(row: VarietyRow) -> str:
    return f"{row.slot}: {row.value}"


def variety_text(review: VarietyReview) -> str:
    """Plain-text rendering for the read-only display (the dialog shows exactly this)."""

    lines = [review.notice]
    if review.trust_label:
        lines.append(review.trust_label)
    lines += ["", review.status]
    if review.coverage is not None:
        lines += ["", UNVERIFIED_LABEL, ""]
        lines += coverage_lines(review.coverage)
    rationales = dict(review.rationales)
    slot = None
    for row in review.rows:
        if row.slot != slot:
            slot = row.slot
            lines += ["", f"Slot {slot}", f"   Why (model's words): {rationales.get(slot, '')}"]
        if row.index in review.added:
            lines.append(f"   [added] {row.value}")
        elif row.offered:
            lines.append(f"   [can add] {row.value}")
        else:
            # Quoted so an empty value or a stray space is visible; a hidden value is never shown.
            shown = HIDDEN_TEXT if row.reason == "hidden" else repr(row.value)
            lines.append(f"   [rejected] {shown}: {REASON_TEXT[row.reason]}")
    return "\n".join(lines).rstrip()


_SLOT_LINE_LIMIT = 12


def slots_line(slots: Sequence[SlotState], *, is_visible: Callable[[str], bool]) -> str:
    """One read-only line naming the matrix slots a request can add values to (the editable ones), so the limit is visible.

    A name hidden by the current visibility mode is replaced, never shown; a long list is cut with a count."""

    names = [slot.name for slot in slots if slot.editable]
    if not names:
        return "Slots the model can add values to: none. Add slots in the Matrix tab first."
    shown = [name if is_visible(name) else HIDDEN_TEXT for name in names[:_SLOT_LINE_LIMIT]]
    more = len(names) - len(shown)
    tail = f" (+{more} more)" if more > 0 else ""
    skipped = sum(not slot.editable for slot in slots)
    note = f" {skipped} other slot(s) cannot take a new value." if skipped else ""
    return f"Slots the model can add values to: {', '.join(shown)}{tail}.{note}"


__all__ = [
    "FOCUS_LABELS",
    "NO_SELECTION_TEXT",
    "SLOT_DISABLED_REASON",
    "UNVERIFIED_LABEL",
    "SlotCoverage",
    "VarietyCoverage",
    "check_variety_quantity",
    "coverage_lines",
    "coverage_status",
    "selected_slot_names",
    "variety_coverage",
    "HIDDEN_TEXT",
    "REASON_TEXT",
    "VARIETY_LABEL",
    "VARIETY_NOTICE",
    "VARIETY_REFUSED_HINT",
    "slots_line",
    "VARIETY_REVIEW_ACTIONS",
    "SlotState",
    "VarietyContext",
    "VarietyReview",
    "VarietyRow",
    "build_variety_request",
    "judge_variety",
    "matrix_state",
    "offered_label",
    "unavailable_variety_review",
    "value_key",
    "value_problem",
    "variety_review",
    "variety_text",
]
