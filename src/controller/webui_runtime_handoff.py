# Subsystem: Controller
# Role: Queue-driven cold start of the managed WebUI-family runtime for the next image workload (PR-RUNTIME-HANDOFF).

"""Give a queued WebUI image job the runtime it needs, through the existing owners only.

``RuntimeTransitionCoordinator.prepare_for`` releases StableNew-owned conflicting residency (for example Comfy after
video work) and deliberately starts nothing. This is the other half of that handoff, used by
:class:`WebUIOutageCoordinator` *before* the queue claims an image job whose runtime is not there:

* :meth:`WebUIRuntimeHandoff.assess` is read-only. It classifies the runtime the job's frozen backend identity needs as
  ``ready``, ``defer`` (an owned, healthy runtime of the right identity whose identity probe is merely not positive
  right now; the backend's own identity guard decides), ``cold`` (nothing answers and a managed launch is possible) or
  ``blocked`` (something StableNew does not own is in the way, or no managed launch is configured/allowed).
* :meth:`WebUIRuntimeHandoff.start` is the one bounded launch attempt: release owned conflicting runtimes through the
  transition coordinator, ``WebUIProcessManager.start()``, wait for managed startup (the manager publishes its readiness
  epoch, which is a trigger and not proof), then require a fresh health + readable-options + identity proof.

It is not a lifecycle authority: the process manager still owns the process, the queue still owns claims, and nothing
here is persisted. It never adopts, stops or restarts an external runtime and never uses the recovery-only
``restart_webui``. It never touches a generation request, so it cannot replay one.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.controller.webui_runtime_probe import ProbeResult, probe_webui_runtime
from src.services.runtime_transition_service import (
    RuntimeTransitionCoordinator,
    RuntimeTransitionStatus,
)

logger = logging.getLogger(__name__)

#: The longest single readiness wait slice; the loop re-checks the abort predicate between slices.
STARTUP_WAIT_SLICE_SECONDS = 2.0
#: After the endpoint is healthy, how long a positive identity proof may take to appear.
DEFAULT_PROOF_SETTLE_SECONDS = 30.0
_PROOF_POLL_SECONDS = 0.5
_DEFAULT_STARTUP_TIMEOUT_SECONDS = 60.0

# Stable, content-free reason codes (also the ``last_recovery_result`` of the outage projection).
REASON_ENDPOINT_FREE = "endpoint_free"
REASON_NO_MANAGED_RUNTIME = "no_managed_runtime"
REASON_MANAGED_IDENTITY_MISMATCH = "managed_identity_mismatch"
REASON_AUTOSTART_DISABLED = "autostart_disabled"
REASON_EXTERNAL_RUNTIME = "external_runtime"
REASON_RELEASE_FAILED = "release_failed"
REASON_LAUNCH_REFUSED = "launch_refused"
REASON_CONTAINMENT_FAILED = "containment_failed"
REASON_STARTUP_EXITED = "startup_exited"
REASON_STARTUP_TIMEOUT = "startup_timeout"
REASON_IDENTITY_UNPROVEN = "identity_unproven"
REASON_IDENTITY_MISMATCH = "identity_mismatch"
REASON_INTERRUPTED = "interrupted"


class AssessmentState(str, Enum):
    READY = "ready"
    DEFER = "defer"
    COLD = "cold"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class RuntimeAssessment:
    state: AssessmentState
    reason: str = ""
    #: Operator-readable explanation (content-free: no prompts, no paths).
    detail: str = ""


class StartStatus(str, Enum):
    STARTED = "started"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class StartOutcome:
    status: StartStatus
    reason: str = ""
    detail: str = ""
    #: A failure that consumed a launch attempt is latched until the manager's readiness epoch changes (or the
    #: operator asks again); one that launched nothing (an external conflict) is simply re-evaluated read-only.
    latch: bool = False
    probe: ProbeResult | None = None


def _identity_name(target: str) -> str:
    return "Forge" if target == "forge_webui" else "A1111"


def _default_transition() -> RuntimeTransitionCoordinator:
    return RuntimeTransitionCoordinator()


def _default_manager() -> Any:
    from src.api.webui_process_manager import get_global_webui_process_manager

    return get_global_webui_process_manager()


def _default_waiter(manager: Any, base_url: str, timeout_s: float) -> None:
    """The manager's own bounded startup wait; it publishes the readiness epoch on success."""

    from src.api.healthcheck import wait_for_webui_ready
    from src.api.webui_process_manager import wait_for_managed_startup

    wait_for_managed_startup(manager, base_url, timeout_s=timeout_s, probe=wait_for_webui_ready)


class WebUIRuntimeHandoff:
    """Assess and, when allowed, cold-start the managed runtime for one frozen backend identity."""

    def __init__(
        self,
        *,
        transition: RuntimeTransitionCoordinator | None = None,
        manager_getter: Callable[[], Any] | None = None,
        target_probe: Callable[[str], ProbeResult] | None = None,
        waiter: Callable[[Any, str, float], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        proof_settle_s: float = DEFAULT_PROOF_SETTLE_SECONDS,
    ) -> None:
        self._transition = transition or _default_transition()
        self._manager_getter = manager_getter or _default_manager
        self._target_probe = target_probe or probe_webui_runtime
        self._waiter = waiter or _default_waiter
        self._clock = clock
        self._sleeper = sleeper
        self._proof_settle_s = max(0.0, float(proof_settle_s))

    # -- read-only ----------------------------------------------------------------------------------------------

    def probe(self, target: str) -> ProbeResult:
        """A fresh health + readable-options + identity proof against ``target`` (never raises)."""

        try:
            return self._target_probe(target)
        except Exception as exc:  # noqa: BLE001 - a failing probe is "not proven ready"
            return ProbeResult(False, f"probe_error:{type(exc).__name__}")

    def signature(self) -> tuple[Any, ...]:
        """What an unchanged failed startup is compared against: the manager and its readiness epoch."""

        manager = self._safe_manager()
        return (id(manager), getattr(manager, "ready_epoch", None))

    def _safe_manager(self) -> Any:
        try:
            return self._manager_getter()
        except Exception:  # noqa: BLE001
            return None

    def assess(self, target: str) -> tuple[RuntimeAssessment, ProbeResult]:
        probe = self.probe(target)
        if probe.ready:
            return RuntimeAssessment(AssessmentState.READY, "ready"), probe
        name = _identity_name(target)
        if probe.reason.startswith(("configuration_unreadable", "probe_error")):
            return (
                RuntimeAssessment(
                    AssessmentState.BLOCKED,
                    probe.reason,
                    f"The WebUI runtime could not be assessed ({probe.reason}); {name} jobs stay queued and "
                    "nothing was started. Fix the StableNew settings, then use Launch or Retry.",
                ),
                probe,
            )
        if probe.reason == REASON_ENDPOINT_FREE:
            blocker = self._launch_blocker(target)
            if blocker is not None:
                return blocker, probe
            return RuntimeAssessment(AssessmentState.COLD, REASON_ENDPOINT_FREE), probe
        manager = self._safe_manager()
        if self._owned_live_of(manager, target):
            # Healthy, ours and of the right identity; only the identity evidence is not positive right now. The
            # backend's own guard (live positive, or same-session attestation) decides; this layer must not hold it.
            return RuntimeAssessment(AssessmentState.DEFER, probe.reason), probe
        return (
            RuntimeAssessment(
                AssessmentState.BLOCKED,
                probe.reason,
                f"Something at the configured WebUI endpoint is not a usable {name} runtime for this job "
                f"({probe.reason}; observed identity '{probe.identity or 'unknown'}'). StableNew did not launch it and "
                f"will not adopt, stop or restart it; close it yourself, or point StableNew at the right runtime "
                f"({'select the A1111 rollback with webui_runtime_identity = a1111_webui' if target == 'a1111_webui' else 'managed Forge is the default'}). "
                f"{name} jobs stay queued and independent video jobs continue.",
            ),
            probe,
        )

    def _launch_blocker(self, target: str) -> RuntimeAssessment | None:
        """Why a managed launch for ``target`` is impossible or not allowed (read-only), else ``None``."""

        name = _identity_name(target)
        manager = self._safe_manager()
        if manager is None:
            return RuntimeAssessment(
                AssessmentState.BLOCKED,
                REASON_NO_MANAGED_RUNTIME,
                f"No managed {name} runtime is configured, so StableNew cannot start one. Start {name} yourself "
                f"(or configure the managed runtime), then use Launch or Retry. {name} jobs stay queued and "
                "independent video jobs continue.",
            )
        declared = str(getattr(manager, "runtime_identity", "") or "")
        if declared != target:
            other = _identity_name(declared) if declared else "another runtime"
            hint = (
                "To run this A1111 job, select the A1111 rollback explicitly with webui_runtime_identity = "
                "a1111_webui and restart StableNew."
                if target == "a1111_webui"
                else "Select managed Forge (the default) and restart StableNew."
            )
            return RuntimeAssessment(
                AssessmentState.BLOCKED,
                REASON_MANAGED_IDENTITY_MISMATCH,
                f"This job's frozen backend is {name}, but the managed WebUI slot is configured for {other}. "
                f"StableNew will not start the wrong runtime or change the job's identity. {hint}",
            )
        if not bool(getattr(manager, "autostart_enabled", False)):
            return RuntimeAssessment(
                AssessmentState.BLOCKED,
                REASON_AUTOSTART_DISABLED,
                f"Managed {name} autostart is disabled, so StableNew will not launch it for this job. Enable "
                f"autostart in the engine settings or start {name} yourself with Launch; {name} jobs stay queued "
                "and independent video jobs continue.",
            )
        conflict = self._transition.external_comfy_blocker()
        if conflict is not None:
            return RuntimeAssessment(
                AssessmentState.BLOCKED,
                REASON_EXTERNAL_RUNTIME,
                f"{name} cannot be started: {conflict}",
            )
        return None

    @staticmethod
    def _owned_live_of(manager: Any, target: str) -> bool:
        try:
            return bool(
                manager is not None
                and manager.owns_process
                and manager.is_running()
                and str(getattr(manager, "runtime_identity", "") or "") == target
            )
        except Exception:  # noqa: BLE001
            return False

    # -- the one bounded launch attempt -------------------------------------------------------------------------

    def start(self, target: str, *, abort: Callable[[], bool]) -> StartOutcome:
        """Release conflicting owned residency, launch through the manager, wait, then prove the runtime.

        ``abort`` is polled between steps (pause, shutdown fence, GPU quarantine): an abandoned attempt leaves any
        process the manager already started to the manager and is not a failure.
        """

        name = _identity_name(target)
        recheck = self._launch_blocker(target)
        if (
            recheck is not None
        ):  # configuration changed since the assessment: nothing to do, nothing launched
            return StartOutcome(StartStatus.FAILED, recheck.reason, recheck.detail)
        manager = self._safe_manager()
        if abort():
            return StartOutcome(StartStatus.INTERRUPTED, REASON_INTERRUPTED)

        # Release StableNew-owned conflicting residency (owned Comfy, the other WebUI identity, SVD cache) through each
        # runtime's own owner, before the new process competes with it for the GPU. An external runtime is immutable.
        transition = self._transition.prepare_for(target)
        if transition.status is RuntimeTransitionStatus.ACTION_REQUIRED:
            return StartOutcome(
                StartStatus.FAILED,
                REASON_EXTERNAL_RUNTIME,
                f"{name} cannot be started: " + " ".join(transition.blockers),
            )
        if not transition.ready:
            return StartOutcome(
                StartStatus.FAILED,
                REASON_RELEASE_FAILED,
                f"{name} was not started: a StableNew-owned runtime did not release its GPU residency "
                f"({'; '.join(transition.blockers) or 'no detail'}).",
                latch=True,
            )
        if abort():
            return StartOutcome(StartStatus.INTERRUPTED, REASON_INTERRUPTED)

        try:
            manager.start()
        except Exception as exc:  # noqa: BLE001 - refusal is a result; the manager already recorded why
            from src.api.webui_process_manager import WebUIContainmentError

            contained = isinstance(exc, WebUIContainmentError)
            return StartOutcome(
                StartStatus.FAILED,
                REASON_CONTAINMENT_FAILED if contained else REASON_LAUNCH_REFUSED,
                f"Managed {name} was not started: {exc}"
                + (
                    " The failure is not retried automatically; it cannot succeed until the underlying Windows "
                    "job-object condition changes."
                    if contained
                    else " Fix the cause, then use Launch or Retry."
                ),
                latch=True,
            )

        base_url = str(getattr(manager, "endpoint", "") or "")
        budget = self._startup_budget(manager)
        deadline = self._clock() + budget
        while True:
            if abort():
                return StartOutcome(StartStatus.INTERRUPTED, REASON_INTERRUPTED)
            remaining = deadline - self._clock()
            if remaining <= 0:
                return StartOutcome(
                    StartStatus.FAILED,
                    REASON_STARTUP_TIMEOUT,
                    f"Managed {name} did not become ready within {budget:.0f}s. It was not killed or relaunched; "
                    "use Retry once it has finished starting, or check its output.",
                    latch=True,
                )
            try:
                self._waiter(manager, base_url, min(remaining, STARTUP_WAIT_SLICE_SECONDS))
                break
            except Exception as exc:  # noqa: BLE001
                if self._exited(manager, exc):
                    return StartOutcome(
                        StartStatus.FAILED,
                        REASON_STARTUP_EXITED,
                        f"Managed {name} exited before it became ready: {exc}",
                        latch=True,
                    )
                # A slice that merely expired: keep waiting until the budget is spent.

        # The manager's readiness epoch is a trigger, never proof: require a fresh health + options + identity proof.
        proof_deadline = self._clock() + self._proof_settle_s
        probe = self.probe(target)
        while not probe.ready:
            if abort():
                return StartOutcome(StartStatus.INTERRUPTED, REASON_INTERRUPTED)
            contradicted = bool(
                probe.identity in ("forge_webui", "a1111_webui")
                and probe.reason == "identity_mismatch"
            )
            if contradicted or self._clock() >= proof_deadline:
                return StartOutcome(
                    StartStatus.FAILED,
                    REASON_IDENTITY_MISMATCH if contradicted else REASON_IDENTITY_UNPROVEN,
                    f"Managed {name} is serving, but a fresh readiness proof did not show a usable {name} runtime "
                    f"({probe.reason}; observed identity '{probe.identity or 'unknown'}'). Jobs stay queued.",
                    latch=True,
                    probe=probe,
                )
            self._sleeper(_PROOF_POLL_SECONDS)
            probe = self.probe(target)
        return StartOutcome(StartStatus.STARTED, "ready", probe=probe)

    @staticmethod
    def _startup_budget(manager: Any) -> float:
        value = getattr(manager, "startup_timeout_seconds", None)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value)
        return _DEFAULT_STARTUP_TIMEOUT_SECONDS

    @staticmethod
    def _exited(manager: Any, exc: BaseException) -> bool:
        """The process died before readiness (the manager raises ``WebUIStartupError`` with diagnostics for that)."""

        try:
            from src.api.webui_process_manager import WebUIStartupError

            return isinstance(exc, WebUIStartupError)
        except Exception:  # noqa: BLE001
            return False


__all__ = [
    "REASON_AUTOSTART_DISABLED",
    "REASON_CONTAINMENT_FAILED",
    "REASON_EXTERNAL_RUNTIME",
    "REASON_IDENTITY_MISMATCH",
    "REASON_IDENTITY_UNPROVEN",
    "REASON_INTERRUPTED",
    "REASON_LAUNCH_REFUSED",
    "REASON_MANAGED_IDENTITY_MISMATCH",
    "REASON_NO_MANAGED_RUNTIME",
    "REASON_RELEASE_FAILED",
    "REASON_STARTUP_EXITED",
    "REASON_STARTUP_TIMEOUT",
    "AssessmentState",
    "RuntimeAssessment",
    "StartOutcome",
    "StartStatus",
    "WebUIRuntimeHandoff",
]
