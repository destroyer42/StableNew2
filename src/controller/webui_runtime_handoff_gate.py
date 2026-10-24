# Subsystem: Controller
# Role: Pre-claim hold/launch/release state machine of the queue-driven runtime handoff (PR-RUNTIME-HANDOFF).

"""Decide, before the worker claims the next workload, whether its WebUI runtime must be started or the work held.

This is the stateful half of :class:`~src.controller.webui_runtime_handoff.WebUIRuntimeHandoff`, owned and driven by
:class:`~src.controller.webui_outage_coordinator.WebUIOutageCoordinator` (its host). It adds no queue, runner, lifecycle
or process authority: the queue still owns claims and the WebUI hold, the single worker still executes, the process
manager is still the only process owner, and nothing here is persisted.

Rules it enforces:

* The next workload is learned from the queue's read-only candidate and the frozen NJR backend identity, never from
  model names or GUI state. A Forge job's runtime is never started for a video job and never started speculatively.
* Pause, the shutdown fence and a GPU quarantine forbid any launch (the quarantine is never released here).
* While another WebUI hold is in force (an outage or the startup gate) this does nothing: that hold keeps its own
  bounded recovery and fresh-proof release.
* If the runtime is missing it applies the queue's WebUI hold first (independent video keeps flowing), makes one
  bounded, single-flight launch, and releases the hold only after a fresh health + readable-options + identity proof.
* A launch that failed is latched against the manager's readiness epoch: it is not retried on every polling cycle, only
  after a new epoch (the operator's Launch/Retry) or an explicit Run Next. A blocker that launched nothing (an external
  runtime, a disabled autostart) is re-evaluated read-only on the release interval.
* It never claims, replays or touches a generation request.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from typing import Any

from src.controller.webui_runtime_handoff import AssessmentState, StartStatus, WebUIRuntimeHandoff
from src.controller.webui_runtime_probe import ProbeResult
from src.queue.backend_dependency import classify_job
from src.queue.job_queue import JobQueue

# ``prepare_next_dispatch`` results.
NOT_APPLICABLE = (
    "not_applicable"  # nothing for the handoff to do (paused, a foreign hold, no WebUI work, ...)
)
READY = "ready"  # the next workload's runtime is usable; the claim may proceed
HELD = "held"  # image work is held (blocked, latched failure, or another caller is launching)
LAUNCH_NEEDED = "launch_needed"  # a launch is required and the caller asked not to block on it
STARTED = "started"  # this call launched the runtime and proved it ready
FAILED = "failed"  # this call attempted the launch and it failed

#: Health values the gate reports to its host (``WebUIHealth`` string values).
HEALTH_HEALTHY = "healthy"
HEALTH_RECOVERING = "recovering"
HEALTH_UNAVAILABLE = "unavailable"
HEALTH_ACTION_REQUIRED = "operator_action_required"

StatusSink = Callable[[str, str | None, str | None], None]
EventSink = Callable[..., None]


def _label(target: str) -> str:
    return "Forge" if target == "forge_webui" else "A1111"


class RuntimeHandoffGate:
    def __init__(
        self,
        queue: JobQueue,
        handoff: WebUIRuntimeHandoff,
        *,
        blocked: Callable[[], bool],
        set_status: StatusSink,
        record: EventSink,
        clock: Callable[[], float],
        interval_s: float,
    ) -> None:
        self._queue = queue
        self._handoff = handoff
        self._blocked = blocked
        self._set_status = set_status
        self._record = record
        self._clock = clock
        self._interval_s = max(0.0, float(interval_s))
        self._lock = threading.RLock()
        self._launch_lock = threading.Lock()  # single flight: one managed launch at a time
        self._incident: str | None = None  # incident id of the hold this gate applied
        self._target: str | None = None
        self._latch: tuple[Any, ...] | None = None  # (target, handoff signature) of a failed launch
        self._state: dict[str, Any] = {}
        self._attempts = 0
        self._evaluated_at: float | None = None

    # -- host-facing --------------------------------------------------------------------------------------------

    def owns_hold(self) -> bool:
        incident = self._incident
        if incident is None:
            return False
        try:
            info = self._queue.webui_hold_info()
        except Exception:  # noqa: BLE001
            return False
        return info is not None and info.get("incident_id") == incident

    def fresh_proof(self) -> ProbeResult | None:
        """Fresh proof of the runtime the held workload needs (``None`` when this gate holds nothing)."""

        target = self._target
        return self._handoff.probe(target) if target is not None and self.owns_hold() else None

    def forget(self) -> None:
        """The hold was released by a fresh proof elsewhere: nothing of this gate's is in force any more."""

        with self._lock:
            self._incident = None
            self._target = None
            self._latch = None
            self._state = {}
            self._attempts = 0
            self._evaluated_at = None

    def projection(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
            attempts = self._attempts
        return {
            "attempts": attempts,
            "state": {k: v for k, v in state.items() if k != "detail"},
            "detail": state.get("detail"),
        }

    # -- the pre-claim decision ---------------------------------------------------------------------------------

    def prepare(self, *, force: bool = False, allow_launch: bool = True) -> str:
        """Ready the runtime the next workload needs, or hold WebUI work, before the worker claims it.

        ``force`` is the operator asking again (Run Next): it bypasses the throttle and the failed-launch latch for
        exactly one bounded attempt. ``allow_launch=False`` reports ``launch_needed`` instead of blocking on it.
        """

        if self._blocked() or self._paused():
            return NOT_APPLICABLE
        own = self.owns_hold()
        if self._incident is not None and not own:
            self.forget()  # released elsewhere
        if self._queue.is_webui_held() and not own:
            return NOT_APPLICABLE  # an outage or startup hold: its own recovery and fresh-proof release apply
        has_candidate, target = self._next_target()
        if target is None:
            if own and not has_candidate:
                self._release("no_webui_work")
            return NOT_APPLICABLE
        with self._lock:
            evaluated, latched = self._evaluated_at, self._latch
            if force:
                self._latch = None
        if own and not force:
            if latched == (target, self._handoff.signature()):
                return HELD  # an unchanged failed launch is not retried (or re-judged) every polling cycle
            if evaluated is not None and self._clock() - evaluated < self._interval_s:
                return HELD
        assessment, probe = self._handoff.assess(target)
        with self._lock:
            self._evaluated_at = self._clock()
        if assessment.state in (AssessmentState.READY, AssessmentState.DEFER):
            if own:
                self._release("runtime_ready", probe)
            return READY
        if assessment.state is AssessmentState.BLOCKED:
            self._hold(target, assessment.reason, assessment.detail, HEALTH_ACTION_REQUIRED)
            return HELD
        if not allow_launch:
            return LAUNCH_NEEDED
        return self._cold_start(target)

    def _paused(self) -> bool:
        try:
            return self._queue.is_paused() is True
        except Exception:  # noqa: BLE001
            return False

    def _next_target(self) -> tuple[bool, str | None]:
        """Whether a workload is next in queue order, and the frozen WebUI backend identity it needs (if any)."""

        try:
            candidate = self._queue.peek_next_dispatch_candidate()
        except Exception:  # noqa: BLE001
            return False, None
        if candidate is None:
            return False, None
        return True, classify_job(candidate).webui_backend_id or None

    def _cold_start(self, target: str) -> str:
        if not self._launch_lock.acquire(blocking=False):
            return HELD  # single flight: another caller is already launching this runtime
        try:
            incident = self._hold(
                target,
                "cold_start",
                f"Managed {_label(target)} is being started for the next queued image job; WebUI jobs stay queued.",
                HEALTH_RECOVERING,
            )
            if incident is None:
                return NOT_APPLICABLE  # another hold won the race; its recovery applies
            with self._lock:
                self._attempts += 1
                attempt = self._attempts
            self._record(
                "cold_start_started",
                incident_id=incident,
                extra={"target": target, "attempt": attempt},
            )
            outcome = self._handoff.start(target, abort=lambda: self._blocked() or self._paused())
            if outcome.status is StartStatus.STARTED:
                self._release("cold_start_succeeded", outcome.probe)
                return STARTED
            if outcome.status is StartStatus.INTERRUPTED:
                with self._lock:
                    self._state = {**self._state, "status": "interrupted", "reason": outcome.reason}
                self._set_status(HEALTH_UNAVAILABLE, incident, None)
                return HELD
            with self._lock:
                self._state = {
                    "target": target,
                    "status": "failed",
                    "reason": outcome.reason,
                    "detail": outcome.detail,
                }
                if (
                    outcome.latch
                ):  # compared after the attempt: its own readiness epoch is part of the state
                    self._latch = (target, self._handoff.signature())
            self._set_status(HEALTH_ACTION_REQUIRED, incident, outcome.reason)
            self._record(
                "cold_start_failed",
                incident_id=incident,
                probe=outcome.probe,
                extra={
                    "target": target,
                    "reason": outcome.reason,
                    "attempt": attempt,
                    "latched": outcome.latch,
                },
            )
            return FAILED
        finally:
            self._launch_lock.release()

    def _hold(self, target: str, reason: str, detail: str, health: str) -> str | None:
        """Hold WebUI work (idempotent). ``None`` when another hold is in force: that hold has its own recovery."""

        incident = self._incident or f"coldstart-{uuid.uuid4().hex[:8]}"
        applied = self._queue.hold_webui_dispatch(reason=f"runtime_{reason}", incident_id=incident)
        info = self._queue.webui_hold_info()
        if info is None or info.get("incident_id") != incident:
            return None
        with self._lock:
            self._incident = incident
            self._target = target
            self._state = {
                "target": target,
                "status": "starting" if health == HEALTH_RECOVERING else "blocked",
                "reason": reason,
                "detail": detail,
            }
        self._set_status(health, incident, reason if health == HEALTH_ACTION_REQUIRED else None)
        if applied:
            self._record(
                "cold_start_hold", incident_id=incident, extra={"target": target, "reason": reason}
            )
        return incident

    def _release(self, why: str, probe: ProbeResult | None = None) -> None:
        """Release the hold this gate applied (never an outage hold) and forget its state."""

        incident = self._incident
        if self.owns_hold():
            self._queue.release_webui_dispatch()
        self.forget()
        self._set_status(HEALTH_HEALTHY, None, why if why == "cold_start_succeeded" else None)
        self._record("hold_released", incident_id=incident, probe=probe, extra={"why": why})


__all__ = [
    "FAILED",
    "HELD",
    "LAUNCH_NEEDED",
    "NOT_APPLICABLE",
    "READY",
    "STARTED",
    "RuntimeHandoffGate",
]
