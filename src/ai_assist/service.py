"""Single-flight admission, yielding and outcome mapping for one AI request at a time.

AI yields to generation (owner decision D10). Admission refuses while a queue job is RUNNING, a GPU dispatch quarantine is
active, or generation activity cannot be read. An already-running request is terminated within one poll interval (the
watch interval plus the 50 ms ``run_bounded`` poll) when any of that appears, or when host memory falls below the guard.
The service only *reads* generation activity through an injected provider: it adds no queue flag, claim path, lifecycle
state, history or job-cancellation authority. A job that claims in the instant between two polls can overlap the request
by at most one interval; that bounded residual is documented in ``docs/Subsystems/AiAssist/AI_ASSIST.md``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.ai_assist.argv import RunLimits, Sampling
from src.ai_assist.attestation import read_attestation
from src.ai_assist.contracts import AiCancelToken, AssistOutcome, AssistRequest, OutcomeCode
from src.ai_assist.events import EventLog
from src.ai_assist.host import (
    GenerationActivity,
    GenerationActivityProvider,
    HostMemory,
    MemoryProbe,
    checked_activity,
    checked_memory,
    read_host_memory,
)
from src.ai_assist.manifests import (
    ModelRegistry,
    RuntimeManifest,
    Verification,
    verify_installation,
)
from src.ai_assist.observe import ChildObserver, default_cap_gib
from src.ai_assist.paths import events_path
from src.ai_assist.runtime import AiRuntime
from src.ai_assist.validators import validate_output
from src.utils.thread_registry import get_thread_registry

logger = logging.getLogger(__name__)

_GIB = 1024**3
#: Memory the request needs beyond the model file: KV cache, compute buffers and the OS (GiB).
MEMORY_MARGIN_GIB = 4.0
#: Guard while the child runs, mirroring the WAN-321F session limits (GiB).
GUARD_AVAILABLE_GIB = 0.25
GUARD_COMMIT_HEADROOM_GIB = 1.0
GUARD_CONSECUTIVE = 2


@dataclass(frozen=True, slots=True)
class ServicePolicy:
    #: Qualification harness only: also accept a registered-but-unqualified model and runtime.
    allow_candidate: bool = False
    #: Require the operator's firewall attestation before any request runs (owner decision D8).
    strict_offline: bool = False
    watch_interval_seconds: float = 0.25
    #: Cap on the child tree's private memory (GiB); ``None`` derives it from the model size.
    process_memory_cap_gib: float | None = None
    #: How long the child may go unfound before the request stops (it cannot be bounded unseen).
    observe_grace_seconds: float = 3.0


@dataclass(frozen=True, slots=True)
class Submission:
    """Result of :meth:`AiAssistService.submit`: either an immediate refusal or an accepted, running request."""

    accepted: bool
    outcome: AssistOutcome | None = None
    token: AiCancelToken | None = None


class _Watch:
    """Polled by ``run_bounded`` about every 50 ms; decides whether the running child must stop, and why."""

    def __init__(
        self,
        *,
        token: AiCancelToken,
        activity: GenerationActivityProvider,
        memory: MemoryProbe,
        clock: Callable[[], float],
        interval: float,
        observer: ChildObserver | None = None,
    ) -> None:
        self._observer = observer
        self._token = token
        self._activity = activity
        self._memory = memory
        self._clock = clock
        self._interval = interval
        self._last = clock()
        self._strikes = 0
        self.outcome: tuple[OutcomeCode, str] | None = None

    def __call__(self) -> bool:
        # ``run_bounded`` treats an exception from this callable as "not cancelled" and would leave the child running, so
        # nothing may escape: any failure here is itself a reason to stop.
        try:
            return self._poll()
        except Exception:  # noqa: BLE001 - see above; fail closed
            logger.warning("AI assist watch failed; stopping the request", exc_info=True)
            self.outcome = (OutcomeCode.YIELDED_TO_GENERATION, "watch_error")
            return True

    def _poll(self) -> bool:
        if self.outcome is not None:
            return True
        if self._token.cancelled:
            self.outcome = (OutcomeCode.CANCELLED, "request_cancelled")
            return True
        if self._observer is not None and not self._observer.evidence.child_observed:
            # Until the child is found, look on every 50 ms poll: priority is applied as early as possible and a
            # short request is still observed.
            reason = self._observer.poll()
            if reason is not None:
                self.outcome = (OutcomeCode.RESOURCE_INSUFFICIENT, reason)
                return True
        now = self._clock()
        if now - self._last < self._interval:
            return False
        self._last = now
        activity = self._read_activity()
        if activity is None:
            self.outcome = (OutcomeCode.YIELDED_TO_GENERATION, "activity_unreadable")
            return True
        if activity.running_jobs > 0:
            self.outcome = (OutcomeCode.YIELDED_TO_GENERATION, "generation_running")
            return True
        if activity.gpu_quarantined:
            self.outcome = (OutcomeCode.YIELDED_TO_GENERATION, "gpu_quarantine")
            return True
        memory = self._read_memory()
        # Written so that anything that is not a clear pass counts as a breach.
        clear = (
            memory is not None
            and memory.available_gib >= GUARD_AVAILABLE_GIB
            and memory.commit_headroom_gib >= GUARD_COMMIT_HEADROOM_GIB
        )
        self._strikes = 0 if clear else self._strikes + 1
        if self._strikes >= GUARD_CONSECUTIVE:
            self.outcome = (OutcomeCode.RESOURCE_INSUFFICIENT, "memory_guard")
            return True
        if self._observer is not None:
            reason = self._observer.poll()
            if reason is not None:
                self.outcome = (OutcomeCode.RESOURCE_INSUFFICIENT, reason)
                return True
        return False

    def _read_activity(self) -> GenerationActivity | None:
        try:
            return checked_activity(self._activity())
        except Exception:  # noqa: BLE001 - no answer is treated as a conflict, never as "idle"
            logger.warning("Generation activity could not be read; yielding", exc_info=True)
            return None

    def _read_memory(self) -> HostMemory | None:
        try:
            return checked_memory(self._memory())
        except Exception:  # noqa: BLE001 - an unreadable probe counts as a breach
            logger.warning("Host memory probe failed", exc_info=True)
            return None

    def cancelled_outcome(self) -> tuple[OutcomeCode, str]:
        return self.outcome or (OutcomeCode.CANCELLED, "request_cancelled")


class AiAssistService:
    def __init__(
        self,
        *,
        root: Path,
        runtime_manifest: RuntimeManifest,
        registry: ModelRegistry,
        activity_provider: GenerationActivityProvider,
        memory_probe: MemoryProbe = read_host_memory,
        runtime: AiRuntime | None = None,
        policy: ServicePolicy = ServicePolicy(),  # noqa: B008 - frozen dataclass default
        limits: RunLimits = RunLimits(),  # noqa: B008
        sampling: Sampling = Sampling(),  # noqa: B008
        event_log: EventLog | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._root = root
        self._manifest = runtime_manifest
        self._registry = registry
        self._activity = activity_provider
        self._memory = memory_probe
        self._runtime = runtime or AiRuntime(root, clock=clock)
        self._policy = policy
        self._limits = limits
        self._sampling = sampling
        self._events = event_log or EventLog(events_path(root))
        self._clock = clock
        self._lock = threading.Lock()
        self._active: tuple[str, AiCancelToken] | None = None
        self._worker: threading.Thread | None = None
        self._closed = False
        self._swept = False

    # -- public API ---------------------------------------------------------------------------------------------------

    def run(self, request: AssistRequest, token: AiCancelToken | None = None) -> AssistOutcome:
        """Admit and run one request on the calling thread. Never raises for an operational failure."""

        token = token or AiCancelToken()
        admitted = self._admit(request, token)
        if isinstance(admitted, AssistOutcome):
            return self._record(request, admitted, None)
        return self._execute(request, token, admitted)

    def submit(
        self, request: AssistRequest, on_done: Callable[[AssistOutcome], None]
    ) -> Submission:
        """Admit synchronously; run on a tracked non-daemon worker. ``on_done`` is called only for an accepted request."""

        token = AiCancelToken()
        admitted = self._admit(request, token)
        if isinstance(admitted, AssistOutcome):
            return Submission(False, self._record(request, admitted, None))

        def work() -> None:
            outcome = self._execute(request, token, admitted)
            try:
                on_done(outcome)
            except Exception:  # noqa: BLE001 - a failing listener must not leak into the service
                logger.warning("AI assist completion callback failed", exc_info=True)

        try:
            # Publish the worker under the same lock as the shutdown fence. Shutdown cannot observe a reserved
            # request with no worker and return before that worker launches.
            with self._lock:
                if self._closed:
                    self._active = None
                    return Submission(
                        False,
                        AssistOutcome(
                            OutcomeCode.UNAVAILABLE, request.request_id, "service_closed"
                        ),
                    )
                self._worker = get_thread_registry().spawn(
                    target=work, name=f"AiAssist-{request.request_id}", purpose="AI assist request"
                )
        except Exception:  # noqa: BLE001 - e.g. the registry is shutting down: release the single-flight slot
            logger.warning("AI assist worker could not be started", exc_info=True)
            with self._lock:
                self._active = None
            refused = AssistOutcome(
                code=OutcomeCode.UNAVAILABLE,
                request_id=request.request_id,
                reason="worker_unavailable",
            )
            return Submission(False, self._record(request, refused, admitted))
        return Submission(True, None, token)

    def cancel(self, request_id: str) -> bool:
        """Cancel this AI request only. No job, queue entry or repository row is touched. ``True`` if it was active."""

        with self._lock:
            if self._active is not None and self._active[0] == request_id:
                self._active[1].cancel()
                return True
        return False

    def begin_shutdown(self) -> None:
        """Fence new admission and cancel the owned request without waiting."""

        with self._lock:
            self._closed = True
            if self._active is not None:
                self._active[1].cancel()

    def shutdown(self, timeout: float = 10.0) -> bool:
        """Cancel any in-flight request and wait for it. ``True`` only when nothing is left running."""

        self.begin_shutdown()
        with self._lock:
            worker = self._worker
        if worker is not None and worker.is_alive():
            if worker is threading.current_thread():
                return False
            worker.join(timeout)
            return not worker.is_alive()
        with self._lock:
            return self._active is None

    def _read_activity(self) -> GenerationActivity | None:
        try:
            return checked_activity(self._activity())
        except Exception:  # noqa: BLE001 - no answer is treated as a conflict, never as "idle"
            logger.warning("Generation activity could not be read; refusing", exc_info=True)
            return None

    def _read_memory(self) -> HostMemory | None:
        try:
            return checked_memory(self._memory())
        except Exception:  # noqa: BLE001 - an unreadable probe counts as a failed reading
            logger.warning("Host memory probe failed", exc_info=True)
            return None

    # -- admission ----------------------------------------------------------------------------------------------------

    def _admit(self, request: AssistRequest, token: AiCancelToken) -> AssistOutcome | Verification:
        """Fail closed. Order: single-flight, installation, egress attestation, generation, memory."""

        def refuse(code: OutcomeCode, reason: str) -> AssistOutcome:
            return AssistOutcome(code=code, request_id=request.request_id, reason=reason)

        with self._lock:
            if self._closed:
                return refuse(OutcomeCode.UNAVAILABLE, "service_closed")
            if self._active is not None or (self._worker is not None and self._worker.is_alive()):
                return refuse(OutcomeCode.BUSY, "another_request_active")
            if not self._swept:
                # Once per service, before the first request: remove scratch directories (which hold prompt text) that a
                # hard kill or a locked file left behind. Age-gated, so another live request is never touched.
                self._swept = True
                self._runtime.sweep_stale_scratch()
            verification = verify_installation(
                self._root,
                self._manifest,
                self._registry,
                allow_candidate=self._policy.allow_candidate,
            )
            if not verification.ok:
                assert verification.code is not None
                return refuse(verification.code, verification.reason)
            if self._policy.strict_offline and read_attestation(self._root) is None:
                return refuse(OutcomeCode.EGRESS_NOT_ATTESTED, "operator_attestation_missing")
            activity = self._read_activity()
            if activity is None:
                return refuse(OutcomeCode.GENERATION_ACTIVE, "activity_unreadable")
            if activity.running_jobs > 0:
                return refuse(OutcomeCode.GENERATION_ACTIVE, "generation_running")
            if activity.gpu_quarantined:
                return refuse(OutcomeCode.GENERATION_ACTIVE, "gpu_quarantine")
            assert verification.entry is not None
            needed = verification.entry.bytes / _GIB + MEMORY_MARGIN_GIB
            memory = self._read_memory()
            if memory is None:
                return refuse(OutcomeCode.RESOURCE_INSUFFICIENT, "memory_unreadable")
            if not memory.available_gib >= needed:
                return refuse(OutcomeCode.RESOURCE_INSUFFICIENT, "available_ram_below_requirement")
            if not memory.commit_headroom_gib >= needed:
                return refuse(
                    OutcomeCode.RESOURCE_INSUFFICIENT, "commit_headroom_below_requirement"
                )
            self._active = (request.request_id, token)
            return verification

    # -- execution ----------------------------------------------------------------------------------------------------

    def _execute(
        self, request: AssistRequest, token: AiCancelToken, verification: Verification
    ) -> AssistOutcome:
        started = self._clock()
        assert verification.entry is not None
        observer = ChildObserver(
            cap_gib=self._policy.process_memory_cap_gib
            or default_cap_gib(verification.entry.bytes),
            clock=self._clock,
            grace_seconds=self._policy.observe_grace_seconds,
        )
        watch = _Watch(
            token=token,
            activity=self._activity,
            memory=self._memory,
            clock=self._clock,
            interval=self._policy.watch_interval_seconds,
            observer=observer,
        )
        output_chars: int | None = None
        try:
            result = self._runtime.run_once(
                verification,
                request,
                self._limits,
                self._sampling,
                watch,
                watch.cancelled_outcome,
                observe=observer.bind,
            )
            if result.code is not None:
                outcome = AssistOutcome(
                    code=result.code,
                    request_id=request.request_id,
                    reason=result.reason,
                    elapsed_ms=result.elapsed_ms,
                    details=observer.evidence.as_details(),
                )
            else:
                output_chars = len(result.stdout)
                validated = validate_output(result.stdout, request)
                outcome = AssistOutcome(
                    code=validated.code,
                    request_id=request.request_id,
                    reason=validated.reason,
                    suggestion=validated.suggestion,
                    elapsed_ms=result.elapsed_ms,
                    details=observer.evidence.as_details(),
                )
        except Exception:  # noqa: BLE001 - the request must always end in a typed outcome
            logger.exception("AI assist request failed unexpectedly")
            outcome = AssistOutcome(
                code=OutcomeCode.UNAVAILABLE,
                request_id=request.request_id,
                reason="unexpected_error",
                elapsed_ms=int((self._clock() - started) * 1000),
            )
        finally:
            with self._lock:
                self._active = None
        return self._record(request, outcome, verification, output_chars)

    def _record(
        self,
        request: AssistRequest,
        outcome: AssistOutcome,
        verification: Verification | None,
        output_chars: int | None = None,
    ) -> AssistOutcome:
        record: dict[str, object] = {
            "request_id": request.request_id,
            "kind": request.kind.value,
            "outcome": outcome.code.value,
            "reason": outcome.reason,
            "elapsed_ms": outcome.elapsed_ms,
            "input_chars": request.input_chars(),
            "output_chars": output_chars,
            "request_digest": request.digest(),
            "strict_offline": self._policy.strict_offline,
        }
        if (
            verification is not None
            and verification.entry is not None
            and verification.build is not None
        ):
            record["model_sha256_prefix"] = verification.entry.sha256[:12]
            record["runtime_build_id"] = verification.build.build_id
        for key, field in (
            ("peak_tree_private_gib", "peak_private_gib"),
            ("priority_verified", "priority_verified"),
            ("child_observed", "child_observed"),
        ):
            if key in outcome.details:
                record[field] = outcome.details[key]
        if not self._events.append(record):
            # Not silent: the append already logged a warning; the outcome says so too, without failing the request.
            outcome.details["event_log_failed"] = True
        return outcome


__all__ = [
    "GUARD_AVAILABLE_GIB",
    "GUARD_COMMIT_HEADROOM_GIB",
    "MEMORY_MARGIN_GIB",
    "AiAssistService",
    "ServicePolicy",
    "Submission",
]
