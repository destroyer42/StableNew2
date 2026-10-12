"""Bounded, content-free classification of WebUI execution failures (PR-QUEUE-WEBUI-171).

One pure vocabulary shared by the pipeline (which attaches typed evidence to a normalized failed result) and the queue
worker (which assesses it). It reads only typed facts - ``GenerateErrorCode``, diagnostics contexts, HTTP status,
dispatch certainty and stage evidence - never prompts or paths, and it is not driven by message keywords alone.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.api.types import GenerateErrorCode

EVIDENCE_CONTRACT = "webui_failure_evidence/1"
METADATA_KEY = "failure_evidence"


class FailureCategory(str, Enum):
    #: The configured WebUI could not be reached and no request left the process.
    PRE_DISPATCH_UNAVAILABLE = "pre_dispatch_unavailable"
    #: The runtime failed its readiness gate before the request was sent (never dispatched).
    READINESS_FAILURE = "readiness_failure"
    #: The server answered a dispatched generation POST with an HTTP error.
    DISPATCHED_HTTP_ERROR = "dispatched_http_error"
    #: The POST may have executed and its response was lost.
    OUTCOME_UNKNOWN = "outcome_unknown"
    #: Timeout without proof the backend failed.
    TIMEOUT = "timeout"
    #: Invalid model/sampler/payload/configuration or resource exhaustion: restarting does not help.
    ORDINARY = "ordinary_failure"
    #: Not a WebUI failure (SVD/Comfy/training or no typed WebUI evidence).
    NOT_WEBUI = "not_webui_failure"


class DispatchCertainty(str, Enum):
    NOT_DISPATCHED = "not_dispatched"
    DISPATCHED = "dispatched"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class FailureAssessment:
    category: FailureCategory
    certainty: DispatchCertainty
    stage: str | None = None
    http_status: int | None = None
    error_code: str | None = None
    #: Typed signal that the endpoint itself looked unavailable (a fresh health assessment must confirm it).
    suspects_outage: bool = False
    #: Positive evidence that no part of the job executed, so restoring it to QUEUED is safe.
    safe_to_requeue: bool = False
    identity_gap: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "dispatch_certainty": self.certainty.value,
            "stage": self.stage,
            "http_status": self.http_status,
            "error_code": self.error_code,
            "suspects_outage": self.suspects_outage,
            "safe_to_requeue": self.safe_to_requeue,
            "identity_gap": self.identity_gap,
        }


_WEBUI_STAGES = frozenset({"txt2img", "img2img", "adetailer", "upscale", "animatediff"})
_TIMEOUT_KEYWORDS = ("read timed out", "readtimeout", "timed out", "timeout")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _diagnostics_of(exc: BaseException) -> Mapping[str, Any]:
    from src.utils.error_envelope_v2 import get_attached_envelope

    error = getattr(exc, "error", None)
    details = _mapping(getattr(error, "details", None))
    diagnostics = _mapping(details.get("diagnostics"))
    if diagnostics:
        return diagnostics
    envelope = get_attached_envelope(exc)
    if envelope is not None:
        diagnostics = _mapping(_mapping(envelope.context).get("diagnostics"))
        if diagnostics:
            return diagnostics
    return _mapping(getattr(exc, "diagnostics_context", None))


def build_failure_evidence(exc: BaseException) -> dict[str, Any]:
    """Content-free typed evidence of one raised failure (safe to store in result metadata)."""

    error = getattr(exc, "error", None)
    code = getattr(error, "code", None)
    from src.api.client import WebUIGenerationOutcomeUnknownError, WebUIUnavailableError

    if isinstance(exc, WebUIGenerationOutcomeUnknownError):
        code = GenerateErrorCode.OUTCOME_UNKNOWN
    elif isinstance(exc, WebUIUnavailableError):
        code = GenerateErrorCode.CONNECTION
    code_value = getattr(code, "value", code)
    details = _mapping(getattr(error, "details", None))
    diagnostics = _diagnostics_of(exc)
    summary = _mapping(diagnostics.get("request_summary"))
    try:
        status = int(summary.get("status"))
    except (TypeError, ValueError):
        status = None
    message = str(diagnostics.get("error_message") or exc).lower()
    stage = str(
        getattr(error, "stage", None) or summary.get("stage") or getattr(exc, "stage", None) or ""
    ).strip() or None
    may_have_executed = details.get("request_may_have_executed", getattr(exc, "request_may_have_executed", None))
    from src.utils.error_envelope_v2 import get_attached_envelope

    envelope = get_attached_envelope(exc)
    context = _mapping(envelope.context) if envelope is not None else {}
    try:
        recovery_attempts = int(context.get("recovery_attempt_count") or details.get("recovery_attempt_count") or 0)
    except (TypeError, ValueError):
        recovery_attempts = 0
    from src.api.webui_identity_attestation import identity_gap
    from src.api.webui_runtime_identity import WebUIRuntimeIdentityMismatch

    identity_failure = isinstance(exc, WebUIRuntimeIdentityMismatch)
    evidence = {
        "contract": EVIDENCE_CONTRACT,
        "error_code": str(code_value) if code_value else None,
        "stage": stage,
        "http_status": status,
        "method": str(summary.get("method") or "").upper() or None,
        "webui_unavailable": bool(diagnostics.get("webui_unavailable")),
        "crash_suspected": bool(diagnostics.get("crash_suspected")),
        "request_may_have_executed": bool(may_have_executed) if may_have_executed is not None else None,
        "timeout": any(keyword in message for keyword in _TIMEOUT_KEYWORDS),
        "recovery_attempts": recovery_attempts,
        "exception_type": type(exc).__name__,
        "identity_refused": identity_failure,
        "expected_identity": exc.backend_id if identity_failure else None,
        "observed_identity": exc.observed.identity if identity_failure else None,
        "identity_gap": identity_gap(exc.observed) if identity_failure else None,
        "recovery_classification": details.get("recovery_classification"),
        "transport_exception_type": details.get("original_exception") or (
            type(exc.original_exception).__name__ if getattr(exc, "original_exception", None) is not None else None
        ),
        "generation_endpoint": details.get("endpoint", getattr(exc, "endpoint", None)),
        "attempt_count": details.get("attempt_count", getattr(exc, "attempt_count", None)),
    }
    evidence["dispatch_certainty"] = assess_evidence(evidence).certainty.value
    return evidence


def completed_work(result: Mapping[str, Any]) -> bool:
    """True when the result shows any stage already produced output (re-running would duplicate it)."""

    if any(result.get(key) for key in ("variants", "output_paths", "stage_outputs", "stage_checkpoints")):
        return True
    metadata = _mapping(result.get("metadata"))
    if metadata.get("completed_output_paths") or metadata.get("completed_work"):
        return True
    for event in result.get("stage_events") or ():
        record = _mapping(event)
        if str(record.get("phase") or record.get("event") or "").lower() == "exit":
            return True
    return False


def assess_evidence(
    evidence: Mapping[str, Any] | None,
    *,
    job_runs_webui_stage: bool = True,
    completed_work: bool = False,
) -> FailureAssessment:
    """Assess typed evidence; ``None`` evidence is a failure we cannot attribute to the WebUI."""

    data = _mapping(evidence)
    if not data or not job_runs_webui_stage:
        return FailureAssessment(FailureCategory.NOT_WEBUI, DispatchCertainty.NOT_APPLICABLE)
    code = str(data.get("error_code") or "")
    stage = data.get("stage")
    stage = str(stage) if stage else None
    status = data.get("http_status")
    status = status if isinstance(status, int) else None

    def done(
        category: FailureCategory,
        certainty: DispatchCertainty,
        *,
        suspects: bool = False,
        requeue: bool = False,
    ) -> FailureAssessment:
        return FailureAssessment(
            category,
            certainty,
            stage=stage,
            http_status=status,
            error_code=code or None,
            suspects_outage=suspects,
            safe_to_requeue=requeue and not completed_work,
            identity_gap=str(data.get("identity_gap") or "") or None,
        )

    if code == GenerateErrorCode.OUTCOME_UNKNOWN.value or data.get("request_may_have_executed") is True:
        # The POST may have run: never replayed, never silently returned to the queue.
        return done(FailureCategory.OUTCOME_UNKNOWN, DispatchCertainty.UNKNOWN, suspects=True)
    if data.get("identity_refused"):
        from src.api.webui_identity_attestation import SETTLE_GAPS

        # Missing evidence may be an outage; positive contradictory identity is never a restart/fallback signal.
        missing = data.get("observed_identity") == "unknown" and data.get("identity_gap") in SETTLE_GAPS
        return done(
            FailureCategory.READINESS_FAILURE if missing else FailureCategory.ORDINARY,
            DispatchCertainty.NOT_DISPATCHED,
            suspects=missing,
            requeue=missing,
        )
    if data.get("recovery_classification") == "true_ready_timeout":
        return done(FailureCategory.READINESS_FAILURE, DispatchCertainty.NOT_DISPATCHED, suspects=True, requeue=True)
    if status is not None and status >= 400:
        return done(FailureCategory.DISPATCHED_HTTP_ERROR, DispatchCertainty.DISPATCHED, suspects=status >= 500)
    if data.get("crash_suspected"):
        # A prior HTTP 500 on the dispatched POST followed by a refused connection: the request did run.
        return done(FailureCategory.DISPATCHED_HTTP_ERROR, DispatchCertainty.DISPATCHED, suspects=True)
    if code == GenerateErrorCode.CONNECTION.value or data.get("webui_unavailable"):
        return done(
            FailureCategory.PRE_DISPATCH_UNAVAILABLE,
            DispatchCertainty.NOT_DISPATCHED,
            suspects=True,
            requeue=True,
        )
    if data.get("timeout"):
        return done(FailureCategory.TIMEOUT, DispatchCertainty.UNKNOWN)
    return done(FailureCategory.ORDINARY, DispatchCertainty.NOT_APPLICABLE)


def assess_result(result: Mapping[str, Any] | None, *, job_runs_webui_stage: bool = True) -> FailureAssessment:
    """Assess a normalized unsuccessful result (no exception required)."""

    data = _mapping(result)
    metadata = _mapping(data.get("metadata"))
    if str(metadata.get("execution_path") or "") == "ready_gate":
        # The application refused to dispatch because the runtime failed its readiness gate.
        return FailureAssessment(
            FailureCategory.READINESS_FAILURE,
            DispatchCertainty.NOT_DISPATCHED,
            suspects_outage=True,
            safe_to_requeue=job_runs_webui_stage and not completed_work(data),
        )
    evidence = _mapping(metadata.get(METADATA_KEY)) or _mapping(data.get(METADATA_KEY))
    return assess_evidence(
        evidence, job_runs_webui_stage=job_runs_webui_stage, completed_work=completed_work(data)
    )


def assess_exception(exc: BaseException, *, job_runs_webui_stage: bool = True) -> FailureAssessment:
    return assess_evidence(build_failure_evidence(exc), job_runs_webui_stage=job_runs_webui_stage)


__all__ = [
    "EVIDENCE_CONTRACT",
    "METADATA_KEY",
    "DispatchCertainty",
    "FailureAssessment",
    "FailureCategory",
    "assess_evidence",
    "assess_exception",
    "assess_result",
    "build_failure_evidence",
    "completed_work",
]
