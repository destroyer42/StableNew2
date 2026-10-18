# Subsystem: Queue
# Role: The one dispatch-certainty verdict that decides whether a RUNNING job may return to QUEUED.

"""Dispatch evidence for returning a RUNNING job to the queue (PR-RUNTIME-QUEUE-TRANSITION-ATOMICITY).

A job that was RUNNING may go back to QUEUED, under the same identity, only when the typed evidence of this attempt
*positively* shows that generation never started: ``FailureAssessment.safe_to_requeue``, the rule the outage
coordinator has always applied (``src/api/webui_failure_evidence.py``). Absence of evidence is not evidence: an empty
stage-checkpoint list, a result without typed failure evidence, a timeout or an unclassified exception all leave the
verdict at "do not requeue". This module owns that single rule so the outage requeue and the operator's Cancel and
Return cannot drift apart; it holds no state and performs no I/O.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.api.webui_failure_evidence import (
    DispatchCertainty,
    FailureAssessment,
    FailureCategory,
    assess_exception,
    assess_result,
    completed_work,
)
from src.queue.backend_dependency import BackendDependency, classify_job
from src.queue.job_history_store import (
    CANCEL_RETURN_REFUSED_DISPATCH_UNCERTAIN,
    RETURN_REFUSED_CONTROL_ACTION,
)
from src.queue.job_model import Job
from src.utils.error_envelope_v2 import UnifiedErrorEnvelope

#: The run callable was never invoked for this claim, so no stage and no backend request can have started. This is
#: the only fact available when a stop request lands between the claim and the call; it is established by the worker
#: itself, never inferred from missing data.
NEVER_INVOKED = FailureAssessment(
    FailureCategory.NOT_WEBUI, DispatchCertainty.NOT_DISPATCHED, safe_to_requeue=True
)

#: Nothing was established about this attempt (a caller that supplied no evidence): never grounds to requeue.
NO_EVIDENCE = FailureAssessment(FailureCategory.NOT_WEBUI, DispatchCertainty.UNKNOWN)

REFUSAL_MESSAGE = (
    "Cancel and Return was not applied: it could not be shown that this job never started generation, so it "
    "may have produced output or still be running on the backend. It was cancelled instead of being returned "
    "to the queue. Inspect the outputs and backend state, then use Replay Job only if you intentionally want "
    "a new run."
)
REFUSAL_REMEDIATION = (
    "Inspect available artifacts and backend state, then use Replay Job only if you intentionally want a new "
    "execution."
)


def withhold_requeue_after_progress(
    assessment: FailureAssessment, job: Job, result: dict[str, Any] | None = None
) -> FailureAssessment:
    """Recorded progress (a stage checkpoint or completed output) always overrides a "safe to requeue" verdict."""

    if (
        job.execution_metadata.stage_checkpoints
        or completed_work(result or {})
        or completed_work(getattr(job, "result", None) or {})
    ):
        return replace(assessment, safe_to_requeue=False)
    return assessment


def assess_dispatch(
    job: Job,
    *,
    result: dict[str, Any] | None = None,
    exc: BaseException | None = None,
) -> tuple[FailureAssessment, bool]:
    """Classify one finished attempt: ``(assessment, job_runs_a_webui_stage)``.

    The assessment is already reduced to "not safe to requeue" when the job recorded any progress.
    """

    runs_webui = classify_job(job).dependency is not BackendDependency.INDEPENDENT_VIDEO
    if exc is not None:
        assessment = assess_exception(exc, job_runs_webui_stage=runs_webui)
    else:
        assessment = assess_result(result, job_runs_webui_stage=runs_webui)
    return withhold_requeue_after_progress(assessment, job, result), runs_webui


def refusal_envelope(job_id: str, assessment: FailureAssessment) -> UnifiedErrorEnvelope:
    """The operator-facing record of a Cancel and Return that was refused (surfaced by the job-failed event)."""

    return UnifiedErrorEnvelope(
        error_type=CANCEL_RETURN_REFUSED_DISPATCH_UNCERTAIN,
        subsystem="queue",
        severity="ERROR",
        message=REFUSAL_MESSAGE,
        cause=None,
        stack="",
        job_id=job_id,
        stage=assessment.stage,
        remediation=REFUSAL_REMEDIATION,
        context={
            "recovery_identifier": CANCEL_RETURN_REFUSED_DISPATCH_UNCERTAIN,
            "action_required": True,
            "generation_outcome": "ambiguous",
            "automatic_replay": False,
            "requested_action": "return_to_queue",
            "control_action": RETURN_REFUSED_CONTROL_ACTION,
            "dispatch_certainty": assessment.certainty.value,
            "failure_category": assessment.category.value,
        },
    )


__all__ = [
    "NEVER_INVOKED",
    "NO_EVIDENCE",
    "REFUSAL_MESSAGE",
    "assess_dispatch",
    "refusal_envelope",
    "withhold_requeue_after_progress",
]
