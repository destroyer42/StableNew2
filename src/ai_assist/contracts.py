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
MAX_REFUSAL_REASON_CHARS = 400
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class SuggestionKind(str, Enum):
    PROMPT_REWRITE = "prompt_rewrite"
    TARGET_FIT_ADVICE = "target_fit_advice"
    WORKFLOW_CHOICE = "workflow_choice"


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
        ):
            if not isinstance(names, tuple) or len(names) > MAX_LIST_ITEMS:
                raise ValueError(f"{label} must be a tuple of at most {MAX_LIST_ITEMS} names")
            for name in names:
                if not isinstance(name, str) or not name or len(name) > MAX_NAME_CHARS:
                    raise ValueError(f"{label} holds an invalid name")
        if self.kind is SuggestionKind.PROMPT_REWRITE and not self.positive_text.strip():
            raise ValueError("a rewrite request needs a positive prompt")
        if self.kind is SuggestionKind.TARGET_FIT_ADVICE and not self.allowed_targets:
            raise ValueError("target advice needs a closed list of targets")
        if self.kind is SuggestionKind.WORKFLOW_CHOICE and not self.allowed_workflows:
            raise ValueError("workflow advice needs a closed list of workflows")

    def input_chars(self) -> int:
        return len(self.positive_text) + len(self.negative_text)

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
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


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
        }


@dataclass(frozen=True, slots=True)
class AssistOutcome:
    """The only thing a request returns. ``suggestion`` is set if and only if ``code`` is SUGGESTION."""

    code: OutcomeCode
    request_id: str
    reason: str = ""
    suggestion: AssistSuggestion | None = None
    elapsed_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (self.code is OutcomeCode.SUGGESTION) != (self.suggestion is not None):
            raise ValueError("a suggestion accompanies exactly the SUGGESTION outcome")

    @property
    def ok(self) -> bool:
        return self.code is OutcomeCode.SUGGESTION


__all__ = [
    "CHANGE_CODES",
    "CONTENT_CLASSES",
    "MAX_LIST_ITEMS",
    "MAX_NAME_CHARS",
    "MAX_REFUSAL_REASON_CHARS",
    "MAX_TEXT_CHARS",
    "SUGGESTION_SCHEMA_ID",
    "AiCancelToken",
    "AssistOutcome",
    "AssistRequest",
    "AssistSuggestion",
    "OutcomeCode",
    "SuggestionKind",
]
