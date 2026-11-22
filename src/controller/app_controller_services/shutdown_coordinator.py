"""Coordinate application shutdown across the existing lifecycle owners."""

from __future__ import annotations

import inspect
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.config.app_config import is_debug_shutdown_inspector_enabled
from src.controller.job_service_shutdown import stop_with_timeout
from src.services.persistence_worker import active_persistence_thread, shutdown_persistence_worker
from src.utils.debug_shutdown_inspector import log_shutdown_state
from src.utils.gpu_survivor_telemetry import stop_gpu_session_telemetry
from src.utils.thread_registry import log_worker_stacks
from src.video.comfy_process_manager import get_global_comfy_process_manager

logger = logging.getLogger(__name__)

SHUTDOWN_BUDGET_SECONDS = 14.0
QUEUE_QUIESCE_TIMEOUT_SECONDS = 10.0


@dataclass(slots=True)
class ShutdownOutcome:
    admission_fenced: bool = False
    cancellation_requested: bool = False
    queue_quiescent: bool = False
    background_quiescent: bool = False
    ai_quiescent: bool = False
    persistence_drained: bool = False
    repository: str = "left_open"
    webui: str = "deferred"
    comfy: str = "deferred"
    failures: list[str] = field(default_factory=list)
    remaining_workers: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0
    deadline_expired: bool = False

    @property
    def completed(self) -> bool:
        return (
            self.admission_fenced
            and self.cancellation_requested
            and self.queue_quiescent
            and self.background_quiescent
            and self.ai_quiescent
            and self.persistence_drained
            and self.repository in {"closed", "absent"}
            and self.webui in {"released", "unowned_or_absent"}
            and self.comfy in {"released", "unowned_or_absent"}
            and not self.failures
            and not self.remaining_workers
        )


def fence_queue_admission(job_service: Any) -> bool:
    fence = getattr(job_service, "begin_shutdown", None)
    if not callable(fence):
        return False
    try:
        fence()
    except Exception:
        logger.exception("Error fencing queue admission during shutdown")
        return False
    return True


def queue_workers(job_service: Any) -> tuple[threading.Thread, ...]:
    active = getattr(getattr(job_service, "runner", None), "active_worker_threads", None)
    return active() if callable(active) else ()


def quiesce_job_service(job_service: Any, timeout: float | None = None) -> bool:
    if not callable(getattr(job_service, "stop", None)):
        return True
    limit = QUEUE_QUIESCE_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        result = stop_with_timeout(job_service, limit)
    except Exception:
        logger.exception("Error stopping job service")
        result = None
    query = getattr(job_service, "is_quiescent", None)
    quiescent = result if isinstance(result, bool) else (bool(query()) if callable(query) else True)
    if not quiescent:
        logger.error("[shutdown] Queue worker did not quiesce within %.3fs", limit)
        log_worker_stacks(
            ((thread, "queue execution") for thread in queue_workers(job_service)),
            phase="queue_deadline",
        )
    return quiescent


def close_repository_when_quiescent(
    job_service: Any, *, other_users_quiescent: bool = True
) -> bool:
    store = getattr(job_service, "history_store", None)
    close = getattr(store, "close", None) or getattr(store, "shutdown", None)
    if not callable(close):
        return False
    query = getattr(job_service, "is_quiescent", None)
    if not other_users_quiescent or (callable(query) and not query()):
        logger.error("[shutdown] Job repository NOT closed: a repository user is still active")
        return False
    try:
        close()
    except Exception:
        logger.exception("Error closing job repository")
        return False
    logger.info("[shutdown] Job repository closed")
    return True


def release_owned_comfy(seconds: float) -> str:
    manager = get_global_comfy_process_manager()
    if manager is None or not manager.owns_process:
        return "unowned_or_absent"
    if manager.stop(grace_seconds=min(seconds, 5.0)) is False or manager.is_running():
        return "failed"
    return "released"


def finish_webui(manager: Any, seconds: float) -> str:
    if manager is None or getattr(manager, "owns_process", None) is False:
        return "unowned_or_absent"
    stop = getattr(manager, "stop_webui", None) or getattr(manager, "shutdown", None)
    stop = stop or getattr(manager, "stop", None)
    if not callable(stop):
        return "failed"
    options = (
        {"grace_seconds": min(seconds, 10.0)}
        if "grace_seconds" in inspect.signature(stop).parameters
        else {}
    )
    result = stop(**options)
    running = getattr(manager, "is_running", None)
    return "failed" if result is False or (callable(running) and running()) else "released"


def watch_shutdown(controller: Any) -> None:
    timeout = float(os.environ.get("STABLENEW_SHUTDOWN_WATCHDOG_DELAY", "15"))
    hard_exit = os.environ.get("STABLENEW_HARD_EXIT_ON_SHUTDOWN_HANG", "0") == "1"
    if not hard_exit:
        timeout = max(timeout, SHUTDOWN_BUDGET_SECONDS + 1.0)
    expires = time.monotonic() + max(0.0, timeout)
    if controller._shutdown_finished.wait(max(0.0, timeout)):
        if not hard_exit or controller._shutdown_completed:
            return
        # Opt-in only. Give live workers the same configured hang threshold.
        threading.Event().wait(max(0.0, expires - time.monotonic()))
    logger.error(
        "[shutdown] Watchdog deadline after %.1fs, phase=%s", timeout, controller._shutdown_phase
    )
    log_worker_stacks(
        ((thread, "queue execution") for thread in queue_workers(controller.job_service)),
        phase="watchdog",
    )
    if hard_exit:
        logger.error("Hard exit forced due to shutdown hang.")
        os._exit(1)


def shutdown_app(controller: Any, reason: str) -> ShutdownOutcome:
    """Signal participants, then spend one monotonic budget on their shutdown."""
    started = time.monotonic()
    deadline = started + SHUTDOWN_BUDGET_SECONDS
    outcome = ShutdownOutcome()
    active_steps: list[tuple[threading.Thread, str]] = []
    controller._shutdown_phase = "admission"
    watchdog = controller._start_shutdown_watchdog()
    registry = controller._thread_registry

    def remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    def attempt(phase: str, operation: Callable[[], Any], default: Any = False) -> Any:
        controller._shutdown_phase = phase
        try:
            return operation()
        except Exception:
            outcome.failures.append(phase)
            logger.exception("[shutdown] %s failed", phase)
            return default

    def start_step(phase: str, operation: Callable[[], Any]) -> tuple[threading.Thread, list[Any]]:
        # Existing owners retain teardown authority. A synchronous call that
        # outlasts the budget remains visible with its dependencies intact.
        controller._shutdown_phase = phase
        result: list[Any] = []

        def run() -> None:
            try:
                result.append(operation())
            except Exception:
                logger.exception("[shutdown] %s failed", phase)

        worker = registry.spawn_shutdown_step(run, phase=phase)
        return worker, result

    def finish_step(
        phase: str, step: tuple[threading.Thread, list[Any]], default: Any = False
    ) -> Any:
        worker, result = step
        worker.join(remaining())
        if worker.is_alive():
            active_steps.append((worker, phase))
        elif result:
            return result[0]
        outcome.failures.append(phase)
        return default

    def bounded(phase: str, operation: Callable[[], Any], default: Any = False) -> Any:
        if remaining() > 0:
            return finish_step(phase, start_step(phase, operation), default)
        outcome.failures.append(phase)
        return default

    job_service = controller.job_service
    background = controller._background_tasks
    ai = getattr(controller, "ai_assist", None)
    legacy_worker = controller._worker_thread
    scanner = controller.process_auto_scanner
    system_watchdog = getattr(controller, "_system_watchdog", None)

    request_fence = getattr(job_service, "request_shutdown", None)
    if callable(request_fence):
        attempt("queue-fence-request", request_fence)
    fence = start_step("queue-admission", lambda: fence_queue_admission(job_service))
    background.begin_shutdown()
    controller.detach_presentation_actions()
    registry.begin_shutdown()
    ai_shutdown = (
        None if ai is None else start_step("ai-worker", lambda: ai.shutdown(timeout=remaining()))
    )
    if scanner is not None:
        scanner.begin_shutdown()
    if system_watchdog is not None:
        system_watchdog.begin_shutdown()
    telemetry = start_step("gpu-telemetry", lambda: stop_gpu_session_telemetry(reason))

    if callable(request_fence):
        cancellation = start_step("cancellation", lambda: controller._cancel_active_jobs(reason))
        outcome.admission_fenced = finish_step("queue-admission", fence)
    else:
        outcome.admission_fenced = finish_step("queue-admission", fence)
        cancellation = start_step("cancellation", lambda: controller._cancel_active_jobs(reason))
    attempt("learning-hooks", controller._shutdown_learning_hooks)
    attempt(
        "diagnostics",
        lambda: controller._diagnostics_coordinator.uninstall(main_window=controller.main_window),
    )
    outcome.queue_quiescent = attempt(
        "queue-worker",
        lambda: quiesce_job_service(job_service, min(remaining(), QUEUE_QUIESCE_TIMEOUT_SECONDS)),
    )
    outcome.ai_quiescent = ai_shutdown is None or finish_step("ai-worker", ai_shutdown) is True
    if scanner is not None and not attempt(
        "process-scanner", lambda: scanner.stop(timeout=remaining())
    ):
        outcome.failures.append("process-scanner-not-stopped")
    if system_watchdog is not None and not attempt(
        "system-watchdog", lambda: system_watchdog.stop(timeout=remaining())
    ):
        outcome.failures.append("system-watchdog-not-stopped")
    if legacy_worker is not None and legacy_worker is not threading.current_thread():
        legacy_worker.join(remaining())

    outcome.cancellation_requested = finish_step("cancellation", cancellation)
    cancel_requested = getattr(getattr(job_service, "runner", None), "is_cancel_requested", None)
    if not outcome.cancellation_requested and callable(cancel_requested):
        outcome.cancellation_requested = cancel_requested()
    finish_step("gpu-telemetry", telemetry)

    def surviving_registry_workers() -> list[tuple[threading.Thread, str]]:
        # Output pumps and the instance-lock listener never use the repository.
        return [
            (item.thread, item.purpose or "tracked background worker")
            for item in registry.get_active_threads()
            if not item.name.startswith("Shutdown-")
            and (
                not item.suppress_daemon_warning
                or (item.name.startswith("WebUI-") and not item.name.endswith("-reader"))
            )
        ]

    attempt("tracked-threads", lambda: registry.shutdown_all(timeout=remaining()))
    tracked = surviving_registry_workers()
    # The startup/connection workers are daemon threads but can still launch an owned runtime.
    for worker, _role in tracked:
        if worker.daemon and worker is not threading.current_thread():
            worker.join(remaining())
    tracked = surviving_registry_workers()
    outcome.background_quiescent = background.is_quiescent() and not tracked
    owners_stopped = (
        outcome.admission_fenced
        and outcome.queue_quiescent
        and outcome.background_quiescent
        and not any(
            failure in outcome.failures
            for failure in (
                "system-watchdog-not-stopped",
                "process-scanner-not-stopped",
            )
        )
        and (legacy_worker is None or not legacy_worker.is_alive())
        and not active_steps
    )
    if owners_stopped:
        outcome.persistence_drained = (
            attempt("persistence", lambda: shutdown_persistence_worker(timeout=remaining())) is True
        )

        # Each runtime still goes through its original process owner.
        outcome.webui = bounded(
            "webui-release", lambda: controller._shutdown_webui(remaining()), "incomplete"
        )
        outcome.comfy = bounded(
            "comfy-release", lambda: release_owned_comfy(remaining()), "incomplete"
        )

        def finalize_repository() -> str:
            controller._save_queue_state()
            if getattr(job_service, "history_store", None) is None:
                return "absent"
            return "closed" if close_repository_when_quiescent(job_service) else "left_open"

        if outcome.persistence_drained:
            outcome.repository = bounded("repository", finalize_repository, "incomplete")
        if not active_steps:
            attempt("api-client", controller._close_shutdown_api_client)
    if outcome.repository == "left_open":
        logger.error("[shutdown] Job repository NOT closed: cleanup dependencies have not quiesced")
    if is_debug_shutdown_inspector_enabled():
        attempt("inspector", lambda: log_shutdown_state(logger, reason))

    workers = surviving_registry_workers() + active_steps
    workers.extend((thread, "queue execution") for thread in queue_workers(job_service))
    persistence_thread = active_persistence_thread()
    for thread, role in (
        (legacy_worker, "legacy pipeline"),
        (persistence_thread, "persistence drain"),
        (getattr(scanner, "_thread", None), "process scanner"),
        (getattr(system_watchdog, "_thread", None), "system watchdog"),
    ):
        if thread is not None and thread.is_alive():
            workers.append((thread, role))
    outcome.remaining_workers = tuple(thread.name for thread, _role in workers if thread.is_alive())
    log_worker_stacks(workers, phase="final_assessment")
    outcome.elapsed_seconds = time.monotonic() - started
    outcome.deadline_expired = outcome.elapsed_seconds >= SHUTDOWN_BUDGET_SECONDS
    controller._shutdown_completed = outcome.completed
    controller._shutdown_finished.set()
    watchdog.join(min(0.2, remaining()))
    logger.log(
        logging.INFO if outcome.completed else logging.ERROR,
        "[shutdown] result=%s %s",
        "COMPLETE"
        if outcome.completed
        else ("INCOMPLETE_TIMEOUT" if outcome.deadline_expired else "INCOMPLETE"),
        outcome,
    )
    return outcome
