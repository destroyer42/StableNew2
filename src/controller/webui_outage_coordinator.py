# Subsystem: Controller
# Role: WebUI outage detection, dispatch hold and bounded owned recovery (PR-QUEUE-WEBUI-171).

"""Contain a WebUI outage inside the existing queue/worker/manager boundaries.

This is a narrow coordination service, not an authority: the queue still owns claims and lifecycle, the one
single-node worker still executes, and ``WebUIProcessManager`` is still the only lifecycle owner. It

* classifies a failed job from typed evidence (raised or normalized) and, for a suspected outage only, takes one fresh
  bounded read-only health assessment before declaring it;
* on a confirmed outage applies the queue's in-memory WebUI hold (independent SVD/Comfy work keeps flowing) and, for a
  manager-owned runtime only, performs one bounded recovery cycle through the manager;
* releases the hold only after a fresh readiness *and* runtime-identity proof.

It never replays a generation: backend recovery and job re-execution are separate, and a job is restored to QUEUED only
on positive evidence that nothing was dispatched. Nothing here is persisted.

Production wiring also arms the queue-driven runtime handoff (``RuntimeHandoffGate``, PR-RUNTIME-HANDOFF): before a
claim, a queued image job whose runtime is missing is held, the managed runtime is launched once through the existing
manager, and the hold is released only after a fresh readiness proof. An outage hold here always takes precedence.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.api.webui_failure_evidence import (
    DispatchCertainty,
    FailureAssessment,
    FailureCategory,
)
from src.controller.webui_runtime_probe import ProbeResult, probe_webui_runtime
from src.queue.dispatch_evidence import assess_dispatch
from src.queue.job_queue import JobQueue
from src.utils import LogContext, log_with_ctx

if TYPE_CHECKING:
    from src.controller.webui_runtime_handoff import WebUIRuntimeHandoff
    from src.controller.webui_runtime_handoff_gate import RuntimeHandoffGate

logger = logging.getLogger(__name__)

#: One owned restart cycle per incident (the manager's own readiness verification is bounded inside it).
DEFAULT_RECOVERY_BUDGET = 1
#: A job restored to QUEUED because nothing was dispatched may be restored at most this many times.
MAX_UNDISPATCHED_REQUEUES = 2
_OUTPUT_TAIL_LINES = 40


class WebUIHealth(str, Enum):
    UNVERIFIED = "unverified"
    HEALTHY = "healthy"
    RECOVERING = "recovering"
    UNAVAILABLE = "unavailable"
    ACTION_REQUIRED = "operator_action_required"


@dataclass(frozen=True, slots=True)
class OutageDecision:
    assessment: FailureAssessment
    #: The worker should restore the job to QUEUED instead of publishing FAILED.
    requeue: bool = False
    #: The worker should call ``recover`` after publishing the job result.
    recover: bool = False
    outage_confirmed: bool = False
    incident_id: str | None = None


NO_ACTION = OutageDecision(assessment=FailureAssessment(FailureCategory.NOT_WEBUI, DispatchCertainty.NOT_APPLICABLE))


def default_webui_probe() -> ProbeResult:
    """The release probe: readiness plus the *configured* runtime identity."""

    return probe_webui_runtime()


def _default_manager() -> Any:
    from src.api.webui_process_manager import get_global_webui_process_manager

    return get_global_webui_process_manager()


class WebUIOutageCoordinator:
    """Per-queue WebUI outage state machine (transient, in-memory)."""

    def __init__(
        self,
        job_queue: JobQueue,
        *,
        probe: Callable[[], ProbeResult] | None = None,
        manager_getter: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        release_interval_s: float = 2.0,
        recovery_budget: int = DEFAULT_RECOVERY_BUDGET,
    ) -> None:
        self._queue = job_queue
        self._probe = probe or default_webui_probe
        self._manager_getter = manager_getter or _default_manager
        self._clock = clock
        self._release_interval_s = max(0.0, float(release_interval_s))
        self._budget = max(0, int(recovery_budget))
        self._lock = threading.RLock()
        self._recovery_lock = threading.Lock()
        self._health = WebUIHealth.HEALTHY
        self._incident_id: str | None = None
        self._first_failure: str | None = None
        self._first_assessment: FailureAssessment | None = None
        self._first_job_id: str | None = None
        self._affected: set[str] = set()
        self._attempts = 0
        self._last_recovery: str = "none"
        self._last_probe: ProbeResult | None = None
        self._last_check_at: float | None = None
        self._incidents: deque[dict[str, Any]] = deque(maxlen=8)
        self._listening_to: Any = None
        self._startup_gate = False
        self._gate: RuntimeHandoffGate | None = None  # armed by production wiring only

    # -- queue-facing helpers ---------------------------------------------------------------------------------------

    def _summary(self) -> dict[str, Any]:
        """Queue dispatch counts; a queue without the hold API (a test double) projects as nothing held."""

        try:
            return dict(self._queue.dispatch_summary())
        except Exception:
            return {"queued": 0, "held_webui": 0, "eligible": 0, "independent": 0, "unresolved": 0, "hold": None}

    def _fenced(self) -> bool:
        try:
            return bool(self._queue.is_dispatch_fenced())
        except Exception:
            return False

    def _gpu_quarantined(self) -> bool:
        try:
            return self._queue.is_gpu_quarantined() is True
        except Exception:
            return False

    def enable_startup_gate(self, *, reason: str = "startup_unverified") -> None:
        """Hold WebUI claims until a fresh readiness+identity proof (after an application restart)."""

        with self._lock:
            self._startup_gate = True
            self._health = WebUIHealth.UNVERIFIED
            self._incident_id = self._incident_id or f"startup-{uuid.uuid4().hex[:8]}"
            self._queue.hold_webui_dispatch(reason=reason, incident_id=self._incident_id)

    # -- assessment -------------------------------------------------------------------------------------------------

    def assess(
        self,
        job: Any,
        *,
        result: dict[str, Any] | None = None,
        exc: BaseException | None = None,
    ) -> OutageDecision:
        """Classify one failed job; take one fresh read-only health assessment only for a suspected outage."""

        # The same dispatch-certainty verdict the operator's Cancel and Return is held to (src/queue/dispatch_evidence).
        assessment, runs_webui = assess_dispatch(job, result=result, exc=exc)
        if not runs_webui or not assessment.suspects_outage or self._fenced():
            return OutageDecision(assessment)
        probe = self._fresh_probe()
        if probe.ready:
            # The runtime answers: the failure was not an outage (a definitive HTTP rejection, a model error, ...).
            return OutageDecision(assessment)
        incident_id = self._begin_incident(job, assessment, probe)
        requeue = (
            assessment.safe_to_requeue
            and getattr(job.execution_metadata, "return_to_queue_count", 0) < MAX_UNDISPATCHED_REQUEUES
        )
        attempted = int(self._recovery_attempted_by_executor(exc, result))
        with self._lock:
            self._attempts = max(self._attempts, attempted)
            if not probe.recovery_allowed:
                self._last_recovery = probe.reason
        return OutageDecision(
            assessment,
            requeue=requeue,
            recover=attempted == 0 and probe.recovery_allowed,
            outage_confirmed=True,
            incident_id=incident_id,
        )

    @staticmethod
    def _recovery_attempted_by_executor(exc: BaseException | None, result: dict[str, Any] | None) -> bool:
        """The executor already spent its restart attempts for this failure: do not multiply the budget."""

        evidence: Any = None
        if exc is not None:
            from src.api.webui_failure_evidence import build_failure_evidence

            evidence = build_failure_evidence(exc)
        elif isinstance(result, dict):
            metadata = result.get("metadata") or {}
            evidence = metadata.get("failure_evidence") if isinstance(metadata, dict) else None
        return bool(isinstance(evidence, dict) and int(evidence.get("recovery_attempts") or 0) > 0)

    def _fresh_probe(self) -> ProbeResult:
        try:
            probe = self._probe()
        except Exception as exc:  # noqa: BLE001 - a failing probe is "not proven ready"
            probe = ProbeResult(False, f"probe_error:{type(exc).__name__}")
        with self._lock:
            self._last_probe = probe
            self._last_check_at = self._clock()
        return probe

    # -- incident / hold --------------------------------------------------------------------------------------------

    def _begin_incident(self, job: Any, assessment: FailureAssessment, probe: ProbeResult) -> str:
        with self._lock:
            self._affected.add(job.job_id)
            if self._incident_id is None or self._health is WebUIHealth.HEALTHY:
                self._incident_id = f"webui-{uuid.uuid4().hex[:8]}"
                self._first_failure = assessment.category.value
                self._first_assessment = assessment
                self._first_job_id = job.job_id
                self._attempts = 0
                self._last_recovery = "none"
                self._startup_gate = False
            if self._health is not WebUIHealth.RECOVERING:
                self._health = WebUIHealth.UNAVAILABLE
            incident_id = self._incident_id
        self._queue.hold_webui_dispatch(reason=f"webui_{assessment.category.value}", incident_id=incident_id)
        self._record_incident(
            "outage_confirmed",
            job_id=job.job_id,
            assessment=assessment,
            probe=probe,
            incident_id=incident_id,
        )
        return incident_id

    def _record_incident(
        self,
        event: str,
        *,
        incident_id: str | None,
        job_id: str | None = None,
        assessment: FailureAssessment | None = None,
        probe: ProbeResult | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        manager = self._safe_manager()
        owned = bool(getattr(manager, "owns_process", False)) if manager is not None else False
        pid = getattr(manager, "pid", None) if owned else None
        record: dict[str, Any] = {
            "event": event,
            "incident_id": incident_id,
            "job_id": job_id,
            "endpoint": (probe.endpoint if probe else "") or self._endpoint(manager),
            "runtime_identity": getattr(manager, "runtime_identity", None) if manager is not None else None,
            "owned": owned,
            "pid": pid if isinstance(pid, int) else None,
            "process_running": self._process_running(manager),
            "probe_reason": probe.reason if probe else None,
            "queue": self._summary(),
            "recovery_attempts": self._attempts,
            **(assessment.to_dict() if assessment else {}),
            **(extra or {}),
        }
        with self._lock:
            self._incidents.append({k: v for k, v in record.items() if k != "output_tail"})
        log_with_ctx(
            logger,
            logging.INFO if event in {"hold_released", "cold_start_started"} else logging.WARNING,
            f"WEBUI_OUTAGE | {event}",
            ctx=LogContext(job_id=job_id, subsystem="webui_outage"),
            extra_fields=record,
        )

    def _safe_manager(self) -> Any:
        try:
            return self._manager_getter()
        except Exception:
            return None

    @staticmethod
    def _process_running(manager: Any) -> bool | None:
        try:
            return bool(manager.is_running()) if manager is not None else None
        except Exception:
            return None

    @staticmethod
    def _endpoint(manager: Any) -> str:
        try:
            return str(getattr(manager, "endpoint", "") or "")
        except Exception:
            return ""

    # -- recovery ---------------------------------------------------------------------------------------------------

    def recover(self, decision: OutageDecision) -> None:
        """One bounded, single-flight owned recovery cycle; never touches an external runtime."""

        if not decision.outage_confirmed or self._fenced():
            return
        if not self._recovery_lock.acquire(blocking=False):
            return  # another caller is already recovering this incident
        try:
            with self._lock:
                if decision.incident_id != self._incident_id or not self._queue.is_webui_held():
                    return
            if self._gpu_quarantined():
                # PR-QUEUE-GPU-180: a confirmed GPU loss cannot be repaired by restarting the WebUI, and a runtime
                # must not be (re)started onto a lost device. Observe and wait for the operator.
                self._set_unavailable(decision, "gpu_device_loss_quarantine")
                return
            manager = self._safe_manager()
            self._listen_to(manager)
            owned = bool(manager is not None and getattr(manager, "owns_process", False))
            if not decision.recover or self._attempts >= self._budget:
                why = "budget_exhausted" if decision.recover else (
                    self._last_recovery if self._last_recovery != "none" else "recovery_already_attempted"
                )
                self._set_unavailable(decision, why)
                return
            if not owned:
                # An external WebUI is never restarted, stopped or adopted: observe and ask the operator.
                with self._lock:
                    self._health = WebUIHealth.ACTION_REQUIRED
                    self._last_recovery = "external_runtime_action_required"
                self._record_incident("external_action_required", incident_id=decision.incident_id)
                return
            with self._lock:
                self._attempts += 1
                self._health = WebUIHealth.RECOVERING
            tail: str = ""
            try:
                tail = str(manager.get_stdout_tail_text(_OUTPUT_TAIL_LINES))
            except Exception:
                tail = ""
            self._record_incident(
                "recovery_started",
                incident_id=decision.incident_id,
                extra={"stdout_tail_lines": len(tail.splitlines()), "output_tail": tail},
            )
            started = self._clock()
            try:
                restarted = bool(manager.restart_webui(wait_ready=True, max_attempts=1))
            except Exception as exc:  # noqa: BLE001
                logger.error("Owned WebUI recovery raised: %s", exc)
                restarted = False
            elapsed = self._clock() - started
            proof = self._fresh_probe() if restarted else ProbeResult(False, "restart_failed")
            if restarted and proof.ready and not self._fenced():
                self._queue.release_webui_dispatch()
                with self._lock:
                    self._health = WebUIHealth.HEALTHY
                    self._last_recovery = "succeeded"
                    self._incident_id = None
                    self._affected.clear()
                self._record_incident(
                    "recovery_succeeded",
                    incident_id=decision.incident_id,
                    probe=proof,
                    extra={"elapsed_s": round(elapsed, 3)},
                )
            else:
                with self._lock:
                    self._health = WebUIHealth.ACTION_REQUIRED
                    self._last_recovery = "failed"
                self._record_incident(
                    "recovery_failed",
                    incident_id=decision.incident_id,
                    probe=proof,
                    extra={"elapsed_s": round(elapsed, 3)},
                )
        finally:
            self._recovery_lock.release()

    def _set_unavailable(self, decision: OutageDecision, why: str) -> None:
        with self._lock:
            self._health = WebUIHealth.ACTION_REQUIRED
            self._last_recovery = why
        self._record_incident("recovery_skipped", incident_id=decision.incident_id, extra={"why": why})

    # -- release ----------------------------------------------------------------------------------------------------

    def _listen_to(self, manager: Any) -> None:
        if manager is None or manager is self._listening_to:
            return
        add = getattr(manager, "add_ready_listener", None)
        if callable(add):
            try:
                add(self._on_manager_ready)
                self._listening_to = manager
            except Exception:
                logger.debug("Could not attach WebUI ready listener", exc_info=True)

    def _on_manager_ready(self, _event: Any) -> None:
        """A manager readiness epoch is a *trigger*: the hold is released only by a fresh proof."""

        self.maybe_release(force=True)

    def maybe_release(self, *, force: bool = False) -> bool:
        """Release the hold after a fresh readiness+identity proof (throttled, read-only, worker-thread safe)."""

        if not self._queue.is_webui_held() or self._fenced():
            return False
        if self._recovery_lock.locked():
            return False
        self._listen_to(self._safe_manager())
        gate = self._gate
        own = gate is not None and gate.owns_hold()
        now = self._clock()
        with self._lock:
            if (
                not force
                and self._last_check_at is not None
                and now - self._last_check_at < self._release_interval_s
            ):
                return False
        proof = self._fresh_handoff_proof() if own else self._fresh_probe()
        if not proof.ready:
            return False
        if self._fenced() or not self._queue.release_webui_dispatch():
            return False
        with self._lock:
            incident = self._incident_id
            self._health = WebUIHealth.HEALTHY
            self._startup_gate = False
            self._incident_id = None
            self._affected.clear()
            if own:
                self._last_recovery = "cold_start_succeeded"
            elif self._last_recovery in {"none", "failed", "external_runtime_action_required"}:
                self._last_recovery = "runtime_recovered"
        if own and gate is not None:
            gate.forget()
        self._record_incident("hold_released", incident_id=incident, probe=proof)
        return True

    # -- queue-driven runtime handoff (PR-RUNTIME-HANDOFF) ----------------------------------------------------------

    def enable_runtime_handoff(self, handoff: WebUIRuntimeHandoff | None = None) -> None:
        """Arm the pre-claim runtime handoff. Production wiring only: an injected (test) service stays inert."""

        from src.controller.webui_runtime_handoff import WebUIRuntimeHandoff
        from src.controller.webui_runtime_handoff_gate import RuntimeHandoffGate

        self._gate = RuntimeHandoffGate(
            self._queue,
            handoff or WebUIRuntimeHandoff(),
            blocked=lambda: self._fenced() or self._gpu_quarantined(),
            set_status=self._set_handoff_status,
            record=self._record_incident,
            clock=self._clock,
            interval_s=self._release_interval_s,
        )

    def prepare_next_dispatch(self, *, force: bool = False, allow_launch: bool = True) -> str:
        """Ready the runtime the next queued workload needs (or hold WebUI work) before the worker claims it."""

        gate = self._gate
        return gate.prepare(force=force, allow_launch=allow_launch) if gate is not None else "not_applicable"

    def _set_handoff_status(self, health: str, incident_id: str | None, last_recovery: str | None) -> None:
        with self._lock:
            self._health = WebUIHealth(health)
            self._incident_id = incident_id
            if last_recovery is not None:
                self._last_recovery = last_recovery

    def _fresh_handoff_proof(self) -> ProbeResult:
        gate = self._gate
        proof = gate.fresh_proof() if gate is not None else None
        if proof is None:
            return self._fresh_probe()
        with self._lock:
            self._last_probe = proof
            self._last_check_at = self._clock()
        return proof

    # -- projection -------------------------------------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Deterministic, content-free projection (no prompts, no filesystem paths)."""

        summary = self._summary()
        manager = self._safe_manager()
        with self._lock:
            health = self._health
            probe = self._last_probe
            held = int(summary["held_webui"])
            if not summary["hold"] and health is not WebUIHealth.RECOVERING:
                health = WebUIHealth.HEALTHY if health is not WebUIHealth.UNVERIFIED else health
            messages = {
                WebUIHealth.HEALTHY: "WebUI is available.",
                WebUIHealth.UNVERIFIED: "WebUI is being verified; WebUI jobs stay queued until it is ready.",
                WebUIHealth.RECOVERING: "WebUI is being recovered; WebUI jobs stay queued.",
                WebUIHealth.UNAVAILABLE: "WebUI is unavailable; WebUI jobs stay queued and independent video jobs continue.",
                WebUIHealth.ACTION_REQUIRED: (
                    "WebUI needs operator action (Launch or Retry); WebUI jobs stay queued and "
                    "independent video jobs continue."
                ),
            }
            message = messages[health]
            handoff = self._gate.projection() if self._gate is not None else {}
            if handoff.get("detail") and health in (
                WebUIHealth.RECOVERING,
                WebUIHealth.UNAVAILABLE,
                WebUIHealth.ACTION_REQUIRED,
            ):
                message = str(handoff["detail"])
            if int(summary.get("held_gpu_loss") or 0):
                # PR-QUEUE-GPU-180: a GPU quarantine holds video jobs too, so nothing "continues" meanwhile.
                message = message.replace(
                    "independent video jobs continue", "video jobs are also held by the GPU quarantine"
                )
            return {
                "status": health.value,
                "message": message,
                "endpoint": (probe.endpoint if probe else "") or self._endpoint(manager),
                "runtime_identity": getattr(manager, "runtime_identity", None) if manager is not None else None,
                "owned_runtime": bool(getattr(manager, "owns_process", False)) if manager is not None else False,
                "owned_pid": getattr(manager, "pid", None) if manager is not None and manager.owns_process else None,
                "process_running": self._process_running(manager),
                "held_webui_jobs": held,
                "independent_jobs_eligible": int(summary["independent"]),
                "recovery_attempts": self._attempts,
                "last_recovery_result": self._last_recovery,
                "first_failure_category": self._first_failure,
                "first_failure_code": self._first_assessment.error_code if self._first_assessment else None,
                "dispatch_certainty": self._first_assessment.certainty.value if self._first_assessment else None,
                "identity_gap": self._first_assessment.identity_gap if self._first_assessment else None,
                "incident_id": self._incident_id,
                "held_jobs_remain_queued": True,
                "last_probe_reason": probe.reason if probe else None,
                "recent_incidents": [dict(item) for item in self._incidents],
                "runtime_handoff": {
                    "armed": self._gate is not None,
                    "attempts": handoff.get("attempts", 0),
                    "state": handoff.get("state", {}),
                },
            }


__all__ = [
    "DEFAULT_RECOVERY_BUDGET",
    "NO_ACTION",
    "OutageDecision",
    "ProbeResult",
    "WebUIHealth",
    "WebUIOutageCoordinator",
    "default_webui_probe",
    "probe_webui_runtime",
]
