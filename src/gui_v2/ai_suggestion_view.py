"""Toolkit-neutral AI suggestion review: immutable source identity and content-free outcome copy."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.ai_assist.contracts import (
    AssistOutcome,
    AssistRequest,
    AssistSuggestion,
    OutcomeCode,
    RuntimeDetail,
    SuggestionKind,
)
from src.ai_assist.preview import PREVIEW_LABEL, PreviewState
from src.ai_assist.remote_preview import REMOTE_PREVIEW_LABEL
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
    OutcomeCode.NOT_INSTALLED: "AI Assist needs an installed runtime and model (qualified, or an enabled Preview model).",
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
    document: dict[str, Any] = {
        "schema": s.schema,
        "status": "ok",
        "kind": s.kind.value,
        "positive": s.positive_text,
        "negative": s.negative_text,
        "target": s.target,
        "workflow": s.workflow,
        "changes": list(s.changes),
    }
    if request.kind is SuggestionKind.PLAN_PROPOSAL:
        document["steps"] = [
            {
                "stage": step.stage,
                "target": step.target,
                "workflow": step.workflow,
                "count": step.count,
                "rationale": step.rationale,
            }
            for step in s.steps
        ]
    if request.kind is SuggestionKind.SLOT_PROPOSAL:
        document["proposals"] = [
            {
                "slot_name": entry.slot_name,
                "values": list(entry.values),
                "insertion_point": entry.insertion_point,
                "rationale": entry.rationale,
            }
            for entry in s.slot_proposals
        ]
    if request.kind is SuggestionKind.PHRASE_SLOT:
        document["phrase_slots"] = [
            {
                "slot_name": entry.slot_name,
                "values": list(entry.values),
                "rationale": entry.rationale,
            }
            for entry in s.phrase_slots
        ]
    if request.kind is SuggestionKind.SLOT_VARIETY:
        document["slots"] = [
            {"slot": entry.slot, "values": list(entry.values), "rationale": entry.rationale}
            for entry in s.slot_values
        ]
    return validate_output(json.dumps(document), request).suggestion


def result_provider_label(outcome: AssistOutcome) -> str:
    preview = outcome.details.get("trust_tier") == "preview"
    if outcome.details.get("provider") == "remote":
        label = REMOTE_PREVIEW_LABEL if preview else "Remote AI Assist"
        model = outcome.details.get("model_name")
        return f"{label} · Ollama · {model}" if isinstance(model, str) else label
    if outcome.details.get("fallback") is True:
        label = "Local fallback (remote unavailable)"
        return f"{label}. {PREVIEW_LABEL}" if preview else label
    if outcome.details.get("provider") == "local":
        return f"Local AI Assist. {PREVIEW_LABEL}" if preview else "Local AI Assist"
    return PREVIEW_LABEL if preview else ""


def provider_outcome_text(outcome: AssistOutcome) -> str:
    if outcome.reason == "remote_approval_required":
        return "Select an approved Ollama model in AI Preview."
    if outcome.reason == "remote_identity_mismatch":
        return (
            "The Ollama endpoint, version, or model identity did not match the selected approval."
        )
    if outcome.details.get("fallback") is True:
        if outcome.code is OutcomeCode.GENERATION_ACTIVE:
            return "Remote unavailable. Local AI is blocked by generation or GPU quarantine."
        return f"Remote unavailable. {OUTCOME_TEXT[outcome.code]}"
    if outcome.reason == "remote_response_lost":
        return "The connection dropped after Ollama may have received the request. Try again when ready."
    if outcome.reason == "remote_generation_http_error":
        return "The remote worker returned an inference error. Authored work is unchanged."
    if outcome.reason == "remote_health_http_error":
        return "The remote worker returned a readiness error. Authored work is unchanged."
    return OUTCOME_TEXT[outcome.code]


def outcome_review(outcome: AssistOutcome, kind: SuggestionKind) -> SuggestionReview:
    # Never expose raw model refusal text, details, exception messages or malformed stdout.
    return SuggestionReview(provider_outcome_text(outcome), KIND_LABELS[kind])


RUNTIME_DETAIL_BUTTON = "Show runtime detail"
RUNTIME_DETAIL_HIDE_BUTTON = "Hide runtime detail"
RUNTIME_DETAIL_LABEL = (
    "Raw runtime output, not reviewed by StableNew. It is shown here only, is never saved, and may contain "
    "fragments of your own text."
)


def runtime_detail_text(detail: RuntimeDetail | None) -> str:
    """The text behind the "Show runtime detail" control, or ``""`` when the request has nothing to show.

    Held in memory by the dialog only; the exit code is the one value that is also recorded (as an integer) in the event log."""

    if detail is None:
        return ""
    lines: list[str] = []
    if detail.exit_code is not None:
        lines.append(f"Exit code: {detail.exit_code}")
    if detail.reason:
        lines.append(f"Reason: {detail.reason}")
    # The model's own output first: the stderr tail is long and can push it out of the small detail box (AI-202c).
    if detail.stdout_head:
        lines += ["", "stdout (first part):", detail.stdout_head]
    if detail.stderr_tail:
        lines += ["", "stderr (last part):", detail.stderr_tail]
    return "\n".join(lines).strip()


_PREVIEW_MISSING = {
    "pinned_build": "No runtime build is pinned in config/managed_ai_runtime.json. Pin one by reviewed change first.",
    "imported_model": "No runtime and model are imported and activated. Import them from local files first.",
    "integrity": "The installed files do not match their pinned identities. Re-import them from verified local files.",
    "enablement": "AI Assist Preview is not enabled yet.",
    "attestation": "The outbound firewall restriction is not attested. Record the attestation before any request can run.",
}


def preview_status_text(state: PreviewState) -> str:
    """Exact, content-free explanation of the Preview state and of the next missing prerequisite."""

    if state.trust == "qualified":
        return "The installed model is qualified. AI Assist Preview is not needed."
    detail = f" ({state.model_name}, runtime {state.build_id})" if state.model_name else ""
    if state.enabled:
        text = f"AI Assist Preview is ENABLED for the installed model{detail}. Revoke it to stop using it."
    elif state.can_enable:
        text = f"A verified but unqualified model is installed{detail}. Enable Preview to allow suggestions from it."
    else:
        text = "AI Assist Preview cannot be enabled yet."
    reason = _PREVIEW_MISSING.get(state.missing, "")
    return f"{text} {reason}".strip()
