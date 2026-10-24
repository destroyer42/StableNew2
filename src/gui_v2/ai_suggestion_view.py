"""Toolkit-neutral AI suggestion review: immutable source identity and content-free outcome copy."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from src.ai_assist.contracts import (
    AssistOutcome,
    AssistRequest,
    AssistSuggestion,
    OutcomeCode,
    SuggestionKind,
)
from src.ai_assist.validators import validate_output
from src.gui_v2.prompt_adaptation_preview import AdaptationPreviewModel

KIND_LABELS = {
    SuggestionKind.PROMPT_REWRITE: "Rewrite Prompt",
    SuggestionKind.TARGET_FIT_ADVICE: "Target Fit",
    SuggestionKind.WORKFLOW_CHOICE: "Workflow Choice",
}

OUTCOME_TEXT = {
    OutcomeCode.SUGGESTION: "Suggestion ready. Review the changes; quality improvement is not established.",
    OutcomeCode.REFUSED_BY_MODEL: "The model refused this request. Authored content is unchanged.",
    OutcomeCode.MALFORMED: "The response failed validation. It cannot be accepted.",
    OutcomeCode.INVALID_REQUEST: "The authored input cannot be framed safely for this request.",
    OutcomeCode.NOT_INSTALLED: "AI Assist needs an installed, qualified runtime and model.",
    OutcomeCode.INTEGRITY_FAILED: "AI integrity check failed. Open Operator Readiness for diagnostics.",
    OutcomeCode.EGRESS_NOT_ATTESTED: "Operator-managed outbound restriction must be attested before AI can run.",
    OutcomeCode.GENERATION_ACTIVE: "Generation is running, GPU dispatch is quarantined, or queue activity is unreadable. Retry after it clears.",
    OutcomeCode.YIELDED_TO_GENERATION: "AI stopped to prioritize generation or because queue activity became unreadable.",
    OutcomeCode.RESOURCE_INSUFFICIENT: "Available RAM, commit headroom or owned-worker memory does not meet AI limits. Retry when resources permit.",
    OutcomeCode.BUSY: "Another AI request is already running. Retry when it finishes.",
    OutcomeCode.TIMEOUT: "The request exceeded its time limit and was stopped.",
    OutcomeCode.CANCELLED: "AI request cancelled. Authored work is unchanged.",
    OutcomeCode.UNAVAILABLE: "The AI service or runtime is unavailable. This is not a model refusal.",
}


@dataclass(frozen=True, slots=True, repr=False)
class SuggestionSnapshot:
    request: AssistRequest
    fingerprint: str
    targets: tuple[tuple[str, str], ...] = ()
    workflows: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class SuggestionReview:
    status: str
    kind: str
    original: str = field(default="", repr=False)
    proposed: str = field(default="", repr=False)
    changes: tuple[str, ...] = ()
    compatibility: AdaptationPreviewModel | None = field(default=None, repr=False)
    can_accept: bool = False


def checked_suggestion(outcome: AssistOutcome, request: AssistRequest) -> AssistSuggestion | None:
    """Keep the existing strict validator as the sole authority, including at the UI trust boundary."""
    s = outcome.suggestion
    if outcome.request_id != request.request_id or s is None or s.request_id != request.request_id:
        return None
    document = {
        "schema": s.schema,
        "status": "ok",
        "kind": s.kind.value,
        "positive": s.positive_text,
        "negative": s.negative_text,
        "target": s.target,
        "workflow": s.workflow,
        "changes": list(s.changes),
    }
    return validate_output(json.dumps(document), request).suggestion


def outcome_review(outcome: AssistOutcome, kind: SuggestionKind) -> SuggestionReview:
    # Never expose raw model refusal text, details, exception messages or malformed stdout.
    return SuggestionReview(OUTCOME_TEXT[outcome.code], KIND_LABELS[kind])
