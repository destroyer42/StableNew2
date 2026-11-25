"""Typed, versioned contracts for Offline AI Assist.

A suggestion is data for the operator to read and accept; it has no field that can become an executable payload. Every
non-success is a distinct, stable outcome code: none is converted into another, and none is repaired or sanitised.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SUGGESTION_SCHEMA_ID = "ai_assist.suggestion/1"

#: Bounds on authored text handed to the model and on what comes back.
MAX_TEXT_CHARS = 8000
MAX_LIST_ITEMS = 256
MAX_NAME_CHARS = 200
#: A model's display label (its id plus the policy's display name) as stated to the model for a plan request (AI-211).
MAX_LABEL_CHARS = 400
MAX_REFUSAL_REASON_CHARS = 400
#: Planning bounds (P3). Exceeding any of them is a rejection, never a truncation.
MAX_GOAL_CHARS = 1000
MAX_PLAN_STEPS = 6
MAX_STEP_COUNT = 8
MAX_PLAN_TOTAL_COUNT = 24
MAX_RATIONALE_CHARS = 240
#: Slot-variety bounds (AI-212). The request side keeps the frame plus the answer budget inside the runtime's context.
MAX_VARIETY_SLOTS = 12
MAX_VARIETY_SLOT_NAME_CHARS = 64
MAX_VARIETY_EXISTING_VALUES = 64
MAX_VARIETY_INPUT_CHARS = 6000
MAX_VARIETY_NEW_VALUES = 6
MAX_VARIETY_VALUE_CHARS = 80
MAX_VARIETY_RATIONALE_CHARS = 160
#: Slot-variety coverage controls (AI-214): requested values per selected slot, the aggregate bound and the goal focus.
DEFAULT_VARIETY_PER_SLOT = 3
MAX_VARIETY_REQUESTED_TOTAL = 12
#: Worst-case answer size against the runtime's 768-token answer budget (``RuntimeLimits.max_new_tokens``), at about three
#: characters per token: each slot entry costs its JSON structure plus a maximal rationale, each value a maximal phrase.
#: A request whose worst case exceeds the budget is refused before inference rather than risking a truncated answer.
VARIETY_ANSWER_TOKEN_BUDGET = 768
_VARIETY_TOKENS_BASE = 30
_VARIETY_TOKENS_PER_SLOT = 68
_VARIETY_TOKENS_PER_VALUE = 27


def variety_answer_tokens(slot_count: int, per_slot: int) -> int:
    """Conservative worst-case token estimate of a full answer to ``slot_count`` slots at ``per_slot`` values each."""

    return (
        _VARIETY_TOKENS_BASE
        + _VARIETY_TOKENS_PER_SLOT * slot_count
        + _VARIETY_TOKENS_PER_VALUE * slot_count * per_slot
    )


#: New-slot proposal bounds (AI-213). The sentence is capped lower than a rewrite's so the frame, the closed list of
#: insertion points and the answer budget fit the runtime's context.
MAX_PROPOSALS = 3
MIN_PROPOSAL_VALUES = 3
MAX_PROPOSAL_VALUES = 6
MAX_PROPOSAL_SLOT_NAME_CHARS = 64
MAX_PROPOSAL_SENTENCE_CHARS = 2000
MAX_PROPOSAL_POINTS = 8
MAX_PROPOSAL_POINT_CHARS = 120
MAX_PROPOSAL_EXISTING_SLOTS = 64

#: Phrase-to-slot bounds (AI-230g). The operator selects one short phrase of the sentence; the model proposes a slot name and
#: alternatives for it. The phrase itself becomes the slot's first value in code, so the model gives 2 to 5 alternatives and the
#: slot ends up with 3 to 6 values, the same row size as a new-slot proposal.
MAX_PHRASE_CHARS = 80
MAX_PHRASE_SLOTS = 3
MIN_PHRASE_VALUES = 2
MAX_PHRASE_VALUES = 5

VARIETY_FOCUS_DIRECT = "direct"
VARIETY_FOCUS_EXPLORE = "explore"
VARIETY_FOCUS_MODES: frozenset[str] = frozenset({VARIETY_FOCUS_DIRECT, VARIETY_FOCUS_EXPLORE})
#: The one stage that takes a workflow; every other allowed stage takes a model target.
VIDEO_STAGE = "video"
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class SuggestionKind(str, Enum):
    PROMPT_REWRITE = "prompt_rewrite"
    TARGET_FIT_ADVICE = "target_fit_advice"
    WORKFLOW_CHOICE = "workflow_choice"
    #: Advisory, read-only step list (owner decision D17). Never an executable plan; see ``PlanStep``.
    PLAN_PROPOSAL = "plan_proposal"
    #: More values for the pack's existing matrix slots (AI-212). Each value is added only by an explicit operator action.
    SLOT_VARIETY = "slot_variety"
    #: A brand-new matrix slot and where to put its ``[[marker]]`` in the sentence (AI-213). Added only by an explicit
    #: per-proposal operator action, never by this layer.
    SLOT_PROPOSAL = "slot_proposal"
    #: A slot name and alternatives for ONE phrase the operator selected in the sentence (AI-230g). Applied only by an explicit
    #: per-proposal operator action that replaces exactly that span with the slot's ``[[marker]]``.
    PHRASE_SLOT = "phrase_slot"


class OutcomeCode(str, Enum):
    SUGGESTION = "suggestion"
    REFUSED_BY_MODEL = "refused_by_model"
    MALFORMED = "malformed"
    #: The request itself cannot be framed safely (for example authored text contains a reserved delimiter).
    INVALID_REQUEST = "invalid_request"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    RESOURCE_INSUFFICIENT = "resource_insufficient"
    BUSY = "busy"
    UNAVAILABLE = "unavailable"
    NOT_INSTALLED = "not_installed"
    INTEGRITY_FAILED = "integrity_failed"
    EGRESS_NOT_ATTESTED = "egress_not_attested"
    #: Refused at admission because generation owns the machine (a RUNNING job, an active GPU quarantine, or no answer).
    GENERATION_ACTIVE = "generation_active"
    #: Terminated while running because generation started or a conflict appeared. The operator may simply ask again.
    YIELDED_TO_GENERATION = "yielded_to_generation"


#: Closed set of reason codes a rewrite may report; anything else is MALFORMED.
CHANGE_CODES: frozenset[str] = frozenset(
    {
        "clarified_wording",
        "reordered_terms",
        "removed_redundancy",
        "adapted_dialect",
        "added_detail",
        "shortened",
        "no_change",
    }
)

CONTENT_CLASSES: frozenset[str] = frozenset({"standard", "sensitive"})


class AiCancelToken:
    """Request-scoped cancellation for one AI request (owner decision D9).

    Deliberately not the controller's ``CancelToken`` (``src.controller.runtime_state``) and not connected to any job:
    cancelling an AI request can never cancel, requeue or alter a job, and job cancellation can never be routed through
    this type.
    """

    __slots__ = ("_cancelled",)

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


@dataclass(frozen=True, slots=True)
class AssistRequest:
    """One explicit operator request. Authored text is DATA for the model, never an instruction to this code."""

    request_id: str
    kind: SuggestionKind
    positive_text: str = ""
    negative_text: str = ""
    target_policy_id: str = ""
    content_class: str = "standard"
    #: Closed lists the model may choose from. The model can never name something that is not in them.
    allowed_targets: tuple[str, ...] = ()
    allowed_workflows: tuple[str, ...] = ()
    #: ``PLAN_PROPOSAL`` only: the operator's goal in their own words (data for the model) and the closed stage list.
    goal_text: str = ""
    allowed_stages: tuple[str, ...] = ()
    #: ``PLAN_PROPOSAL`` only (AI-211): the model the operator has selected in Pipeline, empty when none is usable. It is
    #: exactly one of ``allowed_targets``; the label and the stages its policy supports (a subset of ``allowed_stages``)
    #: come from the same closed-list authority and are stated to the model. Never derived from the goal text.
    current_target: str = ""
    current_target_label: str = ""
    current_target_stages: tuple[str, ...] = ()
    #: ``SLOT_VARIETY`` only: the pack's existing matrix slots as ``(name, existing values)`` (authored data for the model).
    matrix_slots: tuple[tuple[str, tuple[str, ...]], ...] = ()
    #: ``SLOT_VARIETY`` only (AI-214): requested new values for each slot in ``matrix_slots`` (a target, not a promise) and
    #: whether proposals should directly support the goal or explore related variations. Instruction data only.
    variety_per_slot: int = DEFAULT_VARIETY_PER_SLOT
    variety_focus: str = VARIETY_FOCUS_DIRECT
    #: ``SLOT_PROPOSAL`` only (AI-213): the pack's existing slot names (so the model avoids them) and the closed list of
    #: insertion points, each a short code-made snippet of the sentence with the position marked. The model names a point
    #: by its index in this tuple; it can never name a position that is not in it.
    existing_slot_names: tuple[str, ...] = ()
    insertion_points: tuple[str, ...] = ()
    #: ``PHRASE_SLOT`` only (AI-230g): the phrase the operator selected. It is a span of ``positive_text`` (the sentence, given
    #: as context); ``existing_slot_names`` is used as for a slot proposal. There is no list of positions: the span is the
    #: operator's own selection and the model can never move it.
    phrase_text: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not _REQUEST_ID.match(self.request_id):
            raise ValueError("request_id must be 1-64 characters of letters, digits, '_' or '-'")
        if not isinstance(self.kind, SuggestionKind):
            raise ValueError("kind must be a SuggestionKind")
        if self.content_class not in CONTENT_CLASSES:
            raise ValueError("content_class must be 'standard' or 'sensitive'")
        for label, text in (
            ("positive_text", self.positive_text),
            ("negative_text", self.negative_text),
        ):
            if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
                raise ValueError(f"{label} must be text of at most {MAX_TEXT_CHARS} characters")
        for label, names in (
            ("allowed_targets", self.allowed_targets),
            ("allowed_workflows", self.allowed_workflows),
            ("allowed_stages", self.allowed_stages),
        ):
            if not isinstance(names, tuple) or len(names) > MAX_LIST_ITEMS:
                raise ValueError(f"{label} must be a tuple of at most {MAX_LIST_ITEMS} names")
            for name in names:
                if not isinstance(name, str) or not name or len(name) > MAX_NAME_CHARS:
                    raise ValueError(f"{label} holds an invalid name")
        if not isinstance(self.goal_text, str) or len(self.goal_text) > MAX_GOAL_CHARS:
            raise ValueError(f"goal_text must be text of at most {MAX_GOAL_CHARS} characters")
        if self.kind is SuggestionKind.PLAN_PROPOSAL:
            if not self.goal_text.strip():
                raise ValueError("a plan request needs a goal")
            if not self.allowed_stages or not (self.allowed_targets or self.allowed_workflows):
                raise ValueError(
                    "a plan request needs closed lists of stages and models or workflows"
                )
        elif self.kind is SuggestionKind.SLOT_VARIETY:
            self._check_variety()
        elif self.kind is SuggestionKind.SLOT_PROPOSAL:
            self._check_proposal()
        elif self.kind is SuggestionKind.PHRASE_SLOT:
            self._check_phrase()
        elif self.goal_text or self.allowed_stages:
            raise ValueError("goal_text and allowed_stages belong to plan requests only")
        self._check_current_target()
        if self.kind is not SuggestionKind.SLOT_VARIETY and (
            self.variety_per_slot != DEFAULT_VARIETY_PER_SLOT
            or self.variety_focus != VARIETY_FOCUS_DIRECT
        ):
            raise ValueError(
                "variety_per_slot and variety_focus belong to slot-variety requests only"
            )
        if self.matrix_slots and self.kind is not SuggestionKind.SLOT_VARIETY:
            raise ValueError("matrix_slots belong to slot-variety requests only")
        if self.insertion_points and self.kind is not SuggestionKind.SLOT_PROPOSAL:
            raise ValueError("insertion_points belong to slot proposals only")
        if self.existing_slot_names and self.kind not in (
            SuggestionKind.SLOT_PROPOSAL,
            SuggestionKind.PHRASE_SLOT,
        ):
            raise ValueError("existing_slot_names belong to slot proposals and phrase slots only")
        if self.phrase_text and self.kind is not SuggestionKind.PHRASE_SLOT:
            raise ValueError("phrase_text belongs to phrase-slot requests only")
        if self.kind is SuggestionKind.PROMPT_REWRITE and not self.positive_text.strip():
            raise ValueError("a rewrite request needs a positive prompt")
        if self.kind is SuggestionKind.TARGET_FIT_ADVICE and not self.allowed_targets:
            raise ValueError("target advice needs a closed list of targets")
        if self.kind is SuggestionKind.WORKFLOW_CHOICE and not self.allowed_workflows:
            raise ValueError("workflow advice needs a closed list of workflows")

    def _check_current_target(self) -> None:
        stages = self.current_target_stages
        if not isinstance(self.current_target, str) or not isinstance(
            self.current_target_label, str
        ):
            raise ValueError("current_target and its label must be text")
        if not isinstance(stages, tuple):
            raise ValueError("current_target_stages must be a tuple")
        if not (self.current_target or self.current_target_label or stages):
            return
        if self.kind is not SuggestionKind.PLAN_PROPOSAL:
            raise ValueError("current_target belongs to plan requests only")
        if not self.current_target:
            raise ValueError("a target label or stages need a current_target")
        if self.current_target not in self.allowed_targets:
            raise ValueError("current_target must be one of allowed_targets")
        label = self.current_target_label
        if len(label) > MAX_LABEL_CHARS or not label.isprintable():
            raise ValueError("current_target_label must be short printable text")
        if not stages or not all(s in self.allowed_stages and s != VIDEO_STAGE for s in stages):
            raise ValueError("current_target_stages must be image stages from allowed_stages")

    def _check_variety(self) -> None:
        if not self.goal_text.strip():
            raise ValueError("a slot-variety request needs a goal")
        if (
            self.positive_text
            or self.negative_text
            or self.target_policy_id
            or self.allowed_targets
            or self.allowed_workflows
            or self.allowed_stages
        ):
            raise ValueError("a slot-variety request carries only a goal and the matrix slots")
        slots = self.matrix_slots
        if not isinstance(slots, tuple) or not 1 <= len(slots) <= MAX_VARIETY_SLOTS:
            raise ValueError(f"a slot-variety request needs 1 to {MAX_VARIETY_SLOTS} matrix slots")
        names: set[str] = set()
        for entry in slots:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise ValueError("a matrix slot is a (name, values) pair")
            name, values = entry
            if (
                not isinstance(name, str)
                or not name.strip()
                or len(name) > MAX_VARIETY_SLOT_NAME_CHARS
            ):
                raise ValueError("a matrix slot name must be 1-64 characters of text")
            if name in names:
                raise ValueError("matrix slot names must be unique")
            names.add(name)
            if not isinstance(values, tuple) or len(values) > MAX_VARIETY_EXISTING_VALUES:
                raise ValueError(
                    f"a matrix slot holds a tuple of at most {MAX_VARIETY_EXISTING_VALUES} values"
                )
            if not all(isinstance(value, str) for value in values):
                raise ValueError("matrix slot values must be text")
        per_slot = self.variety_per_slot
        if (
            isinstance(per_slot, bool)
            or not isinstance(per_slot, int)
            or not 1 <= per_slot <= MAX_VARIETY_NEW_VALUES
        ):
            raise ValueError(
                f"suggestions per slot must be a whole number from 1 to {MAX_VARIETY_NEW_VALUES}"
            )
        if per_slot * len(slots) > MAX_VARIETY_REQUESTED_TOTAL:
            raise ValueError(
                f"a request may ask for at most {MAX_VARIETY_REQUESTED_TOTAL} values in total: "
                "reduce the count per slot or the selected slots"
            )
        if variety_answer_tokens(len(slots), per_slot) > VARIETY_ANSWER_TOKEN_BUDGET:
            raise ValueError(
                "the answer to this many slots and values could exceed the runtime's answer budget: "
                "reduce the count per slot or the selected slots"
            )
        if self.variety_focus not in VARIETY_FOCUS_MODES:
            raise ValueError("variety_focus must be 'direct' or 'explore'")
        if self.matrix_chars() > MAX_VARIETY_INPUT_CHARS:
            raise ValueError(
                f"matrix slot names and values must total at most {MAX_VARIETY_INPUT_CHARS} characters"
            )

    def _check_proposal(self) -> None:
        if not self.goal_text.strip():
            raise ValueError("a slot proposal request needs a goal")
        if not self.positive_text.strip() or len(self.positive_text) > MAX_PROPOSAL_SENTENCE_CHARS:
            raise ValueError(
                f"a slot proposal request needs a positive prompt of at most {MAX_PROPOSAL_SENTENCE_CHARS} characters"
            )
        if (
            self.negative_text
            or self.target_policy_id
            or self.allowed_targets
            or self.allowed_workflows
            or self.allowed_stages
            or self.matrix_slots
        ):
            raise ValueError(
                "a slot proposal request carries only a goal, the sentence, the slot names and the insertion points"
            )
        points = self.insertion_points
        self._check_existing_slot_names()
        if not isinstance(points, tuple) or not 1 <= len(points) <= MAX_PROPOSAL_POINTS:
            raise ValueError(
                f"a slot proposal request needs 1 to {MAX_PROPOSAL_POINTS} insertion points"
            )
        for point in points:
            if (
                not isinstance(point, str)
                or not point.strip()
                or len(point) > MAX_PROPOSAL_POINT_CHARS
            ):
                raise ValueError("an insertion point must be short text")

    def _check_existing_slot_names(self) -> None:
        names = self.existing_slot_names
        if not isinstance(names, tuple) or len(names) > MAX_PROPOSAL_EXISTING_SLOTS:
            raise ValueError(
                f"a slot request lists at most {MAX_PROPOSAL_EXISTING_SLOTS} existing slot names"
            )
        for name in names:
            if (
                not isinstance(name, str)
                or not name.strip()
                or len(name) > MAX_PROPOSAL_SLOT_NAME_CHARS
            ):
                raise ValueError("an existing slot name must be 1-64 characters of text")

    def _check_phrase(self) -> None:
        """A phrase request: the sentence (context), one selected phrase that is a span of it, the existing slot names and an
        optional goal. Nothing else; the phrase is never the whole of anything the model could be steered by."""

        sentence, phrase = self.positive_text, self.phrase_text
        if not sentence.strip() or len(sentence) > MAX_PROPOSAL_SENTENCE_CHARS:
            raise ValueError(
                f"a phrase request needs a positive prompt of at most {MAX_PROPOSAL_SENTENCE_CHARS} characters"
            )
        if (
            self.negative_text
            or self.target_policy_id
            or self.allowed_targets
            or self.allowed_workflows
            or self.allowed_stages
            or self.matrix_slots
            or self.insertion_points
        ):
            raise ValueError(
                "a phrase request carries only the sentence, the phrase, the slot names and an optional goal"
            )
        if (
            not isinstance(phrase, str)
            or not phrase.strip()
            or phrase != phrase.strip()
            or len(phrase) > MAX_PHRASE_CHARS
            or "\n" in phrase
            or "\r" in phrase
        ):
            raise ValueError(
                f"a phrase request needs one single-line phrase of at most {MAX_PHRASE_CHARS} characters"
            )
        if phrase not in sentence:
            raise ValueError("the phrase must be part of the sentence")
        self._check_existing_slot_names()

    def matrix_chars(self) -> int:
        return sum(
            len(name) + sum(len(value) for value in values) for name, values in self.matrix_slots
        )

    def input_chars(self) -> int:
        return (
            len(self.positive_text)
            + len(self.negative_text)
            + len(self.goal_text)
            + self.matrix_chars()
            + sum(len(name) for name in self.existing_slot_names)
            + sum(len(point) for point in self.insertion_points)
            + len(self.phrase_text)
        )

    def digest(self) -> str:
        """Short content digest for correlation. The text itself is never persisted or logged."""

        payload = "\x1f".join(
            (
                self.kind.value,
                self.positive_text,
                self.negative_text,
                self.target_policy_id,
                "|".join(self.allowed_targets),
                "|".join(self.allowed_workflows),
                self.goal_text,
                "|".join(self.allowed_stages),
                # Appended only when a plan request carries a selection, so every other request keeps its digest (AI-211).
                *(
                    (
                        "current:" + self.current_target,
                        self.current_target_label,
                        "|".join(self.current_target_stages),
                    )
                    if self.current_target
                    else ()
                ),
            )
        )
        if self.matrix_slots:
            # Appended only when present, so the digests of the other kinds are unchanged.
            payload += "\x1f" + "\x1e".join(
                "\x1d".join((name, *values)) for name, values in self.matrix_slots
            )
            # AI-214: the requested quantity and goal focus are part of the request identity.
            payload += f"\x1fvariety:{self.variety_per_slot}:{self.variety_focus}"
        if self.kind is SuggestionKind.SLOT_PROPOSAL:
            # Appended only for this kind, so every other kind keeps its digest.
            payload += "proposal:" + "".join(self.existing_slot_names)
            payload += "" + "".join(self.insertion_points)
        if self.kind is SuggestionKind.PHRASE_SLOT:
            # Appended only for this kind, so every other kind keeps its digest (AI-230g).
            payload += "phrase:" + self.phrase_text
            payload += "" + "".join(self.existing_slot_names)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One advisory step. Identifiers come from the request's closed lists; ``rationale`` is display text only.

    There is deliberately no field here that could carry a path, a payload, a seed, a prompt or any value an executor
    could consume: a step names *which* stage/model/workflow would fit, nothing more.
    """

    stage: str
    target: str | None
    workflow: str | None
    count: int
    rationale: str


@dataclass(frozen=True, slots=True)
class SlotValues:
    """New values proposed for one existing matrix slot (AI-212). ``slot`` comes from the request's closed list.

    Proposals only: each value still faces the deterministic judge and is added solely by an explicit operator action
    through the Matrix editor's own edit path. ``rationale`` is display text."""

    slot: str
    values: tuple[str, ...]
    rationale: str


@dataclass(frozen=True, slots=True)
class SlotProposal:
    """One proposed new matrix slot (AI-213): ``insertion_point`` indexes the request's closed list.

    A proposal only. The deterministic judge checks it and the slot plus its single marker are added solely by an explicit
    operator action through the Matrix tab's and prompt editor's own edit paths. ``rationale`` is display text."""

    slot_name: str
    values: tuple[str, ...]
    insertion_point: int
    rationale: str


@dataclass(frozen=True, slots=True)
class PhraseSlot:
    """One proposed slot for the operator's selected phrase (AI-230g): a name and 2 to 5 alternatives. There is no position:
    the span is the operator's selection. The phrase becomes the slot's first value in code, never by the model's word.

    A proposal only. The deterministic judge checks it and the slot plus the replaced span are applied solely by an explicit
    operator action through the Matrix tab's and prompt editor's own edit paths. ``rationale`` is display text."""

    slot_name: str
    values: tuple[str, ...]
    rationale: str


@dataclass(frozen=True, slots=True)
class AssistSuggestion:
    """A validated suggestion. Text fields are proposals for an editing buffer, not payloads."""

    schema: str
    kind: SuggestionKind
    request_id: str
    positive_text: str | None = None
    negative_text: str | None = None
    target: str | None = None
    workflow: str | None = None
    changes: tuple[str, ...] = ()
    #: ``PLAN_PROPOSAL`` only. Advice, not a plan: no field converts these to Intent, a job or a queue entry.
    steps: tuple[PlanStep, ...] = ()
    #: ``SLOT_VARIETY`` only.
    slot_values: tuple[SlotValues, ...] = ()
    #: ``SLOT_PROPOSAL`` only.
    slot_proposals: tuple[SlotProposal, ...] = ()
    #: ``PHRASE_SLOT`` only.
    phrase_slots: tuple[PhraseSlot, ...] = ()

    def to_diagnostics(self) -> dict[str, Any]:
        """Content-free view (kind, counts, codes) safe for logs and the event record."""

        return {
            "schema": self.schema,
            "kind": self.kind.value,
            "changes": list(self.changes),
            "positive_chars": None if self.positive_text is None else len(self.positive_text),
            "negative_chars": None if self.negative_text is None else len(self.negative_text),
            "has_target": self.target is not None,
            "has_workflow": self.workflow is not None,
            "step_count": len(self.steps),
            "slot_count": len(self.slot_values),
            "value_count": sum(len(entry.values) for entry in self.slot_values),
            "proposal_count": len(self.slot_proposals),
            "phrase_slot_count": len(self.phrase_slots),
        }


#: The most raw runtime output kept for an operator who asks to see why a request failed (AI-202a).
MAX_RUNTIME_DETAIL_BYTES = 2048


@dataclass(frozen=True, slots=True)
class RuntimeDetail:
    """Raw runtime output for the operator's "Show runtime detail" control. In memory only, never persisted.

    ``stderr_tail`` is the end of the child's stderr and ``stdout_head`` the start of its stdout (kept for ``MALFORMED``
    only), each at most :data:`MAX_RUNTIME_DETAIL_BYTES` bytes. Both are NOT reviewed content: stdout can echo authored text,
    so neither is ever written to ``events.jsonl``, a log or a file, and neither appears in ``repr``."""

    exit_code: int | None = None
    stderr_tail: str = field(default="", repr=False)
    stdout_head: str = field(default="", repr=False)
    #: The outcome's machine-readable reason code (for example ``kind_mismatch``): a fixed token, never model text, so it is
    #: safe to show and to repeat in ``repr``.
    reason: str = ""

    @property
    def has_text(self) -> bool:
        return bool(self.stderr_tail or self.stdout_head)


@dataclass(frozen=True, slots=True)
class AssistOutcome:
    """The only thing a request returns. ``suggestion`` is set if and only if ``code`` is SUGGESTION."""

    code: OutcomeCode
    request_id: str
    reason: str = ""
    suggestion: AssistSuggestion | None = None
    elapsed_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)
    runtime_detail: RuntimeDetail | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (self.code is OutcomeCode.SUGGESTION) != (self.suggestion is not None):
            raise ValueError("a suggestion accompanies exactly the SUGGESTION outcome")

    @property
    def ok(self) -> bool:
        return self.code is OutcomeCode.SUGGESTION


__all__ = [
    "CHANGE_CODES",
    "CONTENT_CLASSES",
    "DEFAULT_VARIETY_PER_SLOT",
    "MAX_VARIETY_REQUESTED_TOTAL",
    "VARIETY_ANSWER_TOKEN_BUDGET",
    "variety_answer_tokens",
    "VARIETY_FOCUS_DIRECT",
    "VARIETY_FOCUS_EXPLORE",
    "VARIETY_FOCUS_MODES",
    "MAX_GOAL_CHARS",
    "MAX_LABEL_CHARS",
    "MAX_LIST_ITEMS",
    "MAX_NAME_CHARS",
    "MAX_PLAN_STEPS",
    "MAX_PLAN_TOTAL_COUNT",
    "MAX_RUNTIME_DETAIL_BYTES",
    "MAX_RATIONALE_CHARS",
    "MAX_REFUSAL_REASON_CHARS",
    "MAX_STEP_COUNT",
    "MAX_TEXT_CHARS",
    "MAX_PROPOSALS",
    "MIN_PROPOSAL_VALUES",
    "MAX_PROPOSAL_VALUES",
    "MAX_PROPOSAL_SLOT_NAME_CHARS",
    "MAX_PROPOSAL_SENTENCE_CHARS",
    "MAX_PROPOSAL_POINTS",
    "MAX_PROPOSAL_POINT_CHARS",
    "MAX_PROPOSAL_EXISTING_SLOTS",
    "MAX_PHRASE_CHARS",
    "MAX_PHRASE_SLOTS",
    "MIN_PHRASE_VALUES",
    "MAX_PHRASE_VALUES",
    "PhraseSlot",
    "SlotProposal",
    "MAX_VARIETY_EXISTING_VALUES",
    "MAX_VARIETY_INPUT_CHARS",
    "MAX_VARIETY_NEW_VALUES",
    "MAX_VARIETY_RATIONALE_CHARS",
    "MAX_VARIETY_SLOTS",
    "MAX_VARIETY_SLOT_NAME_CHARS",
    "MAX_VARIETY_VALUE_CHARS",
    "SUGGESTION_SCHEMA_ID",
    "VIDEO_STAGE",
    "AiCancelToken",
    "AssistOutcome",
    "AssistRequest",
    "AssistSuggestion",
    "OutcomeCode",
    "PlanStep",
    "RuntimeDetail",
    "SlotValues",
    "SuggestionKind",
]
