# Subsystem: Queue
# Role: Pure operator-facing classification of persisted job failures (PR-BATCH-OPS-201).

"""Classify a FAILED job from the typed evidence that was persisted with it.

Typed facts only: the content-free ``failure_evidence`` block (PR-QUEUE-WEBUI-171/172), the persisted error
envelope's exception type and recovery context, and the restart-recovery marker. Message text is displayed
(bounded) but is never searched for keywords to decide a category or a safety verdict. A historical failure
without typed evidence stays ``OTHER`` / unclassified and is never described as safe to replay.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.api.types import GenerateErrorCode
from src.api.webui_failure_evidence import (
    EVIDENCE_CONTRACT,
    METADATA_KEY,
    DispatchCertainty,
    FailureCategory,
    assess_evidence,
)
from src.queue.job_history_store import INTERRUPTED_RESTART_ACTION_REQUIRED

MAX_SUMMARY_CHARS = 240


class TriageCategory(str, Enum):
    PRE_DISPATCH_UNAVAILABLE = "pre_dispatch_unavailable"
    READINESS_OR_IDENTITY = "readiness_or_identity_refusal"
    OUTCOME_UNKNOWN = "dispatched_outcome_unknown"
    HTTP_REJECTION = "definitive_http_rejection"
    INVALID_CONFIGURATION = "invalid_configuration"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    OTHER = "other_unclassified"


CATEGORY_LABELS: dict[TriageCategory, str] = {
    TriageCategory.PRE_DISPATCH_UNAVAILABLE: "Backend unavailable (before dispatch)",
    TriageCategory.READINESS_OR_IDENTITY: "Endpoint readiness / runtime identity refusal",
    TriageCategory.OUTCOME_UNKNOWN: "Dispatched - outcome unknown",
    TriageCategory.HTTP_REJECTION: "Backend rejected the request (HTTP)",
    TriageCategory.INVALID_CONFIGURATION: "Invalid model/configuration or unsupported operation",
    TriageCategory.RESOURCE_EXHAUSTION: "Resource exhaustion (out of memory)",
    TriageCategory.OTHER: "Other / unclassified",
}

# Exact exception *types* recorded by the error envelope (never message text).
_RESOURCE_TYPES = frozenset({"SVDOutOfMemoryError", "ResourceLimitError"})
_CONFIGURATION_TYPES = frozenset(
    {
        "SVDConfigError",
        "SVDInputError",
        "ConfigError",
        "OperationNotSupportedError",
        "AnimateDiffRetiredError",
        "SecondaryMotionRetiredError",
    }
)
_IDENTITY_TYPES = frozenset({"WebUIRuntimeIdentityMismatch"})
_CONFIGURATION_CODES = frozenset(
    {
        GenerateErrorCode.INVALID_MODEL.value,
        GenerateErrorCode.INVALID_SAMPLER.value,
        GenerateErrorCode.INVALID_SCHEDULER.value,
        GenerateErrorCode.ADETAILER_CONFIG.value,
        GenerateErrorCode.PAYLOAD_VALIDATION.value,
    }
)

OUTCOME_UNKNOWN_ACK_TEXT = (
    "The previous request may have produced output even though the job is reported as failed. "
    "Inspect the existing outputs first; a new generation can duplicate work."
)


@dataclass(frozen=True, slots=True)
class FailureTriage:
    category: TriageCategory
    summary: str
    stage: str | None
    #: ``not_dispatched`` / ``dispatched`` / ``unknown`` / ``not_applicable`` / ``untyped``.
    dispatch_certainty: str
    #: True only when the classification came from persisted typed evidence.
    typed: bool
    #: A new generation needs explicit operator acknowledgement (outcome unknown / request may have run).
    acknowledgement_required: bool
    action_required: bool
    error_type: str | None = None

    @property
    def label(self) -> str:
        return CATEGORY_LABELS[self.category]

    @property
    def acknowledgement_text(self) -> str | None:
        return OUTCOME_UNKNOWN_ACK_TEXT if self.acknowledgement_required else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def bounded_message(text: Any, limit: int = MAX_SUMMARY_CHARS) -> str:
    """First line of an error message, whitespace-collapsed and length-bounded (never a payload dump)."""

    first = next((line for line in str(text or "").splitlines() if line.strip()), "")
    collapsed = re.sub(r"\s+", " ", first).strip()
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1].rstrip() + "…"


def _envelope_fields(envelope: Any) -> tuple[str | None, str | None, Mapping[str, Any], str]:
    if envelope is None:
        return None, None, {}, ""
    if isinstance(envelope, Mapping):
        return (
            str(envelope.get("error_type") or "") or None,
            str(envelope.get("stage") or "") or None,
            _mapping(envelope.get("context")),
            str(envelope.get("message") or ""),
        )
    return (
        str(getattr(envelope, "error_type", "") or "") or None,
        str(getattr(envelope, "stage", "") or "") or None,
        _mapping(getattr(envelope, "context", None)),
        str(getattr(envelope, "message", "") or ""),
    )


def triage_failure(
    *,
    error_message: str | None,
    envelope: Any = None,
    result: Mapping[str, Any] | None = None,
    last_control_action: str | None = None,
) -> FailureTriage:
    """Classify one failed job. ``envelope`` may be a ``UnifiedErrorEnvelope`` or its serialized mapping."""

    error_type, envelope_stage, context, envelope_message = _envelope_fields(envelope)
    metadata = _mapping(_mapping(result).get("metadata"))
    evidence = _mapping(metadata.get(METADATA_KEY)) or _mapping(_mapping(result).get(METADATA_KEY))
    summary = bounded_message(error_message or envelope_message or _mapping(result).get("error"))
    action_required = bool(
        metadata.get("action_required") or context.get("action_required") is True
    )

    def build(
        category: TriageCategory,
        *,
        certainty: str,
        typed: bool,
        stage: str | None = None,
        acknowledge: bool = False,
    ) -> FailureTriage:
        return FailureTriage(
            category=category,
            summary=summary or CATEGORY_LABELS[category],
            stage=stage or envelope_stage,
            dispatch_certainty=certainty,
            typed=typed,
            acknowledgement_required=acknowledge,
            action_required=action_required or acknowledge,
            error_type=error_type,
        )

    # The restart-recovery marker is the repository's own typed statement that the outcome is ambiguous.
    if (
        error_type == INTERRUPTED_RESTART_ACTION_REQUIRED
        or context.get("generation_outcome") == "ambiguous"
        or last_control_action == "restart_interrupted_action_required"
    ):
        return build(
            TriageCategory.OUTCOME_UNKNOWN,
            certainty=DispatchCertainty.UNKNOWN.value,
            typed=True,
            acknowledge=True,
        )

    if evidence and evidence.get("contract") == EVIDENCE_CONTRACT:
        assessment = assess_evidence(evidence)
        stage = assessment.stage
        may_have_run = evidence.get("request_may_have_executed") is True or bool(
            evidence.get("crash_suspected")
        )
        certainty = assessment.certainty.value
        category = assessment.category
        if category is FailureCategory.OUTCOME_UNKNOWN or category is FailureCategory.TIMEOUT:
            return build(
                TriageCategory.OUTCOME_UNKNOWN,
                certainty=certainty,
                typed=True,
                stage=stage,
                acknowledge=True,
            )
        if category is FailureCategory.PRE_DISPATCH_UNAVAILABLE:
            return build(
                TriageCategory.PRE_DISPATCH_UNAVAILABLE, certainty=certainty, typed=True, stage=stage
            )
        if category is FailureCategory.READINESS_FAILURE:
            return build(
                TriageCategory.READINESS_OR_IDENTITY, certainty=certainty, typed=True, stage=stage
            )
        if category is FailureCategory.DISPATCHED_HTTP_ERROR:
            return build(
                TriageCategory.HTTP_REJECTION,
                certainty=certainty,
                typed=True,
                stage=stage,
                acknowledge=may_have_run,
            )
        if category is FailureCategory.ORDINARY:
            if evidence.get("identity_refused"):
                return build(
                    TriageCategory.READINESS_OR_IDENTITY, certainty=certainty, typed=True, stage=stage
                )
            if assessment.error_code in _CONFIGURATION_CODES:
                return build(
                    TriageCategory.INVALID_CONFIGURATION,
                    certainty=certainty,
                    typed=True,
                    stage=stage,
                )
            return build(TriageCategory.OTHER, certainty=certainty, typed=True, stage=stage)

    if error_type in _RESOURCE_TYPES:
        return build(
            TriageCategory.RESOURCE_EXHAUSTION,
            certainty=DispatchCertainty.NOT_APPLICABLE.value,
            typed=True,
        )
    if error_type in _CONFIGURATION_TYPES:
        return build(
            TriageCategory.INVALID_CONFIGURATION,
            certainty=DispatchCertainty.NOT_APPLICABLE.value,
            typed=True,
        )
    if error_type in _IDENTITY_TYPES:
        return build(
            TriageCategory.READINESS_OR_IDENTITY,
            certainty=DispatchCertainty.NOT_DISPATCHED.value,
            typed=True,
        )
    # No typed evidence: never retroactively safe, never guessed from text.
    return build(TriageCategory.OTHER, certainty="untyped", typed=False)


__all__ = [
    "CATEGORY_LABELS",
    "OUTCOME_UNKNOWN_ACK_TEXT",
    "FailureTriage",
    "TriageCategory",
    "bounded_message",
    "triage_failure",
]
