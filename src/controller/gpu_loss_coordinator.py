# Subsystem: Controller
# Role: GPU device-loss assessment, queue quarantine and operator-gated release (PR-QUEUE-GPU-180).

"""Contain a confirmed GPU device loss inside the existing queue/worker boundaries.

A narrow coordination service, not an authority: the queue still owns claims and lifecycle (the quarantine is a
dispatch-eligibility flag persisted through the repository's settings), the one single-node worker still executes, and
process managers remain the only lifecycle owners. This service

* assesses a failed GPU-dependent job against typed facts and, only when the failure warrants it, one bounded read-only
  host GPU query (``nvidia-smi`` enumeration);
* on a *confirmed* loss applies the queue's GPU dispatch quarantine before the worker can claim anything else;
* releases the quarantine only on an explicit operator confirmation **and** fresh positive host evidence.

It never restarts or stops a runtime, resets a driver, reboots, kills a process, replays a job or issues a generation
probe, and it never alters a job's identity, status, order or recorded failure. A healthy WebUI response is not an
input to any decision here.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.queue.backend_dependency import classify_job
from src.queue.gpu_loss_assessment import (
    GpuLossAssessment,
    GpuLossEvidenceClass,
    assess_gpu_loss,
    facts_from_failure,
    needs_host_evidence,
)
from src.utils import LogContext, log_with_ctx
from src.utils.gpu_device_health import (
    AcceleratorFault,
    HostGpuEvidence,
    HostGpuState,
    default_host_probe,
)

logger = logging.getLogger(__name__)

QUARANTINE_SCHEMA = "stablenew.gpu-dispatch-quarantine.v1"
RELEASE_REQUIREMENTS = ("positive_host_gpu_evidence", "operator_confirmation")

#: Stable refusal / outcome codes of :meth:`GpuLossCoordinator.release`.
RELEASED = "released"
NOT_QUARANTINED = "not_quarantined"
CONFIRMATION_REQUIRED = "operator_confirmation_required"
INCIDENT_MISMATCH = "incident_mismatch"
NO_POSITIVE_EVIDENCE = "no_positive_recovery_evidence"
RELEASE_NOT_DURABLE = "release_not_durable"

_RECOVERY_STEPS = (
    "Recover the GPU on the host. NVIDIA reports a lost GPU as needing a system reboot; StableNew does not "
    "reboot, reset the driver, restart Forge/Comfy or kill any process.",
    "Relaunch StableNew and the image/video runtimes you use. Held jobs stay queued and unchanged.",
    "Confirm recovery in Operator Readiness. StableNew then re-checks, read-only, that the GPU enumerates again "
    "before it releases the held jobs in their original order.",
)


@dataclass(frozen=True, slots=True)
class GpuReleaseResult:
    released: bool
    #: One of the stable outcome codes above.
    reason: str
    incident_id: str | None = None
    host: HostGpuEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "released": self.released,
            "reason": self.reason,
            "incident_id": self.incident_id,
            "host_evidence": self.host.to_dict() if self.host is not None else None,
        }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class GpuLossCoordinator:
    """Per-queue GPU device-loss assessment and quarantine coordination (thread-safe, no background thread)."""

    def __init__(
        self,
        job_queue: Any,
        *,
        probe: Callable[[], HostGpuEvidence] | None = None,
        now: Callable[[], str] = _utc_now,
    ) -> None:
        self._queue = job_queue
        self._probe = probe or default_host_probe
        self._now = now
        self._lock = threading.RLock()
        self._last: GpuLossAssessment | None = None
        self._last_refusal: dict[str, Any] | None = None
        self._events: deque[dict[str, Any]] = deque(maxlen=8)

    # -- host evidence -----------------------------------------------------------------------------------------------

    def _probe_host(self) -> HostGpuEvidence:
        try:
            evidence = self._probe()
        except Exception:  # noqa: BLE001 - a failing probe is "evidence unavailable", never "lost"
            logger.debug("GPU host probe raised", exc_info=True)
            return HostGpuEvidence(HostGpuState.UNAVAILABLE, "probe_error")
        return evidence if isinstance(evidence, HostGpuEvidence) else HostGpuEvidence(
            HostGpuState.UNAVAILABLE, "probe_invalid"
        )

    # -- assessment --------------------------------------------------------------------------------------------------

    def assess_failure(
        self,
        job: Any,
        *,
        result: dict[str, Any] | None = None,
        exc: BaseException | None = None,
    ) -> GpuLossAssessment | None:
        """Assess one failed job; a confirmed loss quarantines GPU dispatch before this returns."""

        if self._queue_quarantined():
            # Already contained: no further probe, and nothing about the failed record is touched.
            self._record("failure_under_quarantine", job_id=getattr(job, "job_id", None))
            return None
        facts = facts_from_failure(job, result=result, exc=exc)
        host = self._probe_host() if needs_host_evidence(facts) else None
        assessment = assess_gpu_loss(facts, host)
        with self._lock:
            self._last = assessment
        if assessment.confirmed:
            self._establish(job, assessment)
        elif facts.fault is AcceleratorFault.DEVICE_FAULT and assessment.evidence_class in {
            GpuLossEvidenceClass.SUSPECTED_DEVICE_LOSS,
            GpuLossEvidenceClass.EVIDENCE_UNAVAILABLE,
        }:
            self._record(assessment.evidence_class.value, job_id=getattr(job, "job_id", None), assessment=assessment)
        return assessment

    def _queue_quarantined(self) -> bool:
        check = getattr(self._queue, "is_gpu_quarantined", None)
        return callable(check) and check() is True

    def _establish(self, job: Any, assessment: GpuLossAssessment) -> None:
        facts = assessment.facts
        incident_id = f"gpu-{uuid.uuid4().hex[:8]}"
        trigger: dict[str, Any] = {
            "job_id": getattr(job, "job_id", None),
            "dependency": classify_job(job).reason,
            "stage": facts.stage,
            "failure_category": facts.category.value if facts.category is not None else None,
            "accelerator_fault": facts.fault.value if facts.fault is not None else None,
            "dispatch_certainty": facts.certainty.value if facts.certainty is not None else None,
        }
        incident: dict[str, Any] = {
            "schema": QUARANTINE_SCHEMA,
            "incident_id": incident_id,
            "evidence_class": assessment.evidence_class.value,
            "established_at": self._now(),
            "trigger": trigger,
            "host_evidence": assessment.host.to_dict() if assessment.host is not None else None,
            "release_requirements": list(RELEASE_REQUIREMENTS),
        }
        applied = self._queue.quarantine_gpu_dispatch(incident)
        self._record(
            "quarantine_established" if applied else "quarantine_already_active",
            job_id=trigger["job_id"],
            assessment=assessment,
            incident_id=incident_id if applied else None,
        )

    # -- operator-gated release --------------------------------------------------------------------------------------

    def release(self, *, operator_confirmed: bool, incident_id: str | None = None) -> GpuReleaseResult:
        """Release the quarantine only with explicit operator confirmation and fresh positive host evidence.

        A reboot, a healthy WebUI endpoint or a manager READY event are never inputs: recovery of the GPU makes the
        release *possible*; only the operator's confirmation, checked against NVIDIA's own enumeration, performs it.
        """

        info = self._queue.gpu_quarantine_info() if hasattr(self._queue, "gpu_quarantine_info") else None
        if info is None:
            return GpuReleaseResult(False, NOT_QUARANTINED)
        active = str(info.get("incident_id") or "")
        if not operator_confirmed:
            return self._refuse(CONFIRMATION_REQUIRED, active)
        if incident_id is not None and incident_id != active:
            return self._refuse(INCIDENT_MISMATCH, active)
        host = self._probe_host()
        if not host.positive_recovery:
            return self._refuse(NO_POSITIVE_EVIDENCE, active, host)
        if not self._queue.release_gpu_quarantine(active):
            return self._refuse(RELEASE_NOT_DURABLE, active, host)
        with self._lock:
            self._last_refusal = None
        self._record("quarantine_released", incident_id=active, host=host)
        return GpuReleaseResult(True, RELEASED, active, host)

    def _refuse(self, reason: str, incident_id: str, host: HostGpuEvidence | None = None) -> GpuReleaseResult:
        with self._lock:
            self._last_refusal = {
                "reason": reason,
                "incident_id": incident_id,
                "at": self._now(),
                "host_evidence": host.to_dict() if host is not None else None,
            }
        self._record("release_refused", incident_id=incident_id, host=host, extra={"why": reason})
        return GpuReleaseResult(False, reason, incident_id, host)

    # -- projection --------------------------------------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Deterministic, content-free, side-effect-free projection (never runs the host probe)."""

        info = self._queue.gpu_quarantine_info() if hasattr(self._queue, "gpu_quarantine_info") else None
        try:
            summary = dict(self._queue.dispatch_summary())
        except Exception:  # noqa: BLE001 - a queue double without the API projects as nothing held
            summary = {}
        held = int(summary.get("held_gpu_loss") or 0)
        with self._lock:
            last = self._last
            refusal = dict(self._last_refusal) if self._last_refusal is not None else None
            events = [dict(item) for item in self._events]
        base: dict[str, Any] = {
            "status": "quarantined" if info is not None else "clear",
            "held_gpu_jobs": held if info is not None else 0,
            "jobs_remain_queued": True,
            "last_assessment": last.to_dict() if last is not None else None,
            "last_release_refusal": refusal,
            "recent_events": events,
        }
        if info is None:
            return {**base, "message": "No GPU device-loss quarantine is active."}
        return {
            **base,
            "message": (
                "GPU device loss was confirmed. GPU jobs (image, video, SVD and unresolved work) stay queued "
                "and unchanged until the GPU has recovered and you confirm it."
            ),
            "incident_id": info.get("incident_id"),
            "evidence_class": info.get("evidence_class"),
            "established_at": info.get("established_at"),
            "trigger": dict(info.get("trigger") or {}),
            "host_evidence": info.get("host_evidence"),
            "persisted": info.get("persisted", True),
            "operator_confirmation_required": True,
            "release_requirements": list(info.get("release_requirements") or RELEASE_REQUIREMENTS),
            "recovery_steps": list(_RECOVERY_STEPS),
        }

    # -- logging -----------------------------------------------------------------------------------------------------

    def _record(
        self,
        event: str,
        *,
        job_id: str | None = None,
        assessment: GpuLossAssessment | None = None,
        incident_id: str | None = None,
        host: HostGpuEvidence | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "event": event,
            "at": self._now(),
            "incident_id": incident_id,
            "job_id": job_id,
            **(assessment.to_dict() if assessment is not None else {}),
            **({"host_evidence": host.to_dict()} if host is not None else {}),
            **(extra or {}),
        }
        with self._lock:
            self._events.append({k: v for k, v in record.items() if v is not None})
        warn = event not in {"quarantine_released"}
        log_with_ctx(
            logger,
            logging.WARNING if warn else logging.INFO,
            f"GPU_DEVICE_LOSS | {event}",
            ctx=LogContext(job_id=job_id, subsystem="gpu_device_loss"),
            extra_fields=record,
        )


__all__ = [
    "CONFIRMATION_REQUIRED",
    "INCIDENT_MISMATCH",
    "NOT_QUARANTINED",
    "NO_POSITIVE_EVIDENCE",
    "QUARANTINE_SCHEMA",
    "RELEASED",
    "RELEASE_NOT_DURABLE",
    "RELEASE_REQUIREMENTS",
    "GpuLossCoordinator",
    "GpuReleaseResult",
]
