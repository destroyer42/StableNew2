"""JobService bridges JobQueue, runner, and history for higher-level orchestration."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict
import logging
import time

from typing import Any, Callable, Literal, Protocol

from src.controller.job_history_service import JobHistoryService
from src.config.app_config import get_process_container_config, get_watchdog_config
from src.queue.job_model import Job, JobExecutionMetadata, JobStatus, RetryAttempt
from src.gui.pipeline_panel_v2 import format_queue_job_summary
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.queue.job_history_store import JobHistoryStore
from src.utils import LogContext, log_with_ctx
from src.utils.error_envelope_v2 import serialize_envelope, UnifiedErrorEnvelope
from src.utils.process_container_v2 import (
    NullProcessContainer,
    ProcessContainer,
    ProcessContainerConfig,
    PROCESS_CONTAINER_LOG_PREFIX,
    build_process_container,
)
from src.utils.watchdog_v2 import JobWatchdog, WatchdogConfig, WATCHDOG_LOG_PREFIX

try:
    import psutil  # type: ignore[import]
except ImportError:  # pragma: no cover - psutil is optional for cleanup
    psutil = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _terminate_single_process(proc: "psutil.Process", *, timeout: float) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
    except psutil.TimeoutExpired:  # type: ignore[attr-defined]
        log_with_ctx(
            logger,
            logging.DEBUG,
            "Process did not terminate cleanly; escalating to kill",
            ctx=LogContext(subsystem="job_service"),
            extra_fields={"pid": getattr(proc, "pid", None)},
        )
        try:
            proc.kill()
            proc.wait(timeout=max(0.1, timeout / 2))
        except Exception:
            pass
    except (psutil.NoSuchProcess, psutil.ZombieProcess):  # type: ignore[attr-defined]
        return
    except Exception as exc:
        log_with_ctx(
            logger,
            logging.DEBUG,
            "Failed to terminate process",
            ctx=LogContext(subsystem="job_service"),
            extra_fields={"pid": getattr(proc, "pid", None), "error": str(exc)},
        )


def _terminate_process_tree(pid: int, *, timeout: float = 3.0) -> None:
    if psutil is None:
        log_with_ctx(
            logger,
            logging.DEBUG,
            "psutil not available; skipping process cleanup",
            ctx=LogContext(subsystem="job_service"),
            extra_fields={"pid": pid},
        )
        return
    try:
        root = psutil.Process(pid)  # type: ignore[attr-defined]
    except (psutil.NoSuchProcess, psutil.ZombieProcess):  # type: ignore[attr-defined]
        return
    except Exception as exc:
        log_with_ctx(
            logger,
            logging.DEBUG,
            "Unable to inspect process",
            ctx=LogContext(subsystem="job_service"),
            extra_fields={"pid": pid, "error": str(exc)},
        )
        return

    children = root.children(recursive=True)
    for child in reversed(children):
        _terminate_single_process(child, timeout=timeout)
    _terminate_single_process(root, timeout=timeout)

QueueStatus = Literal["idle", "running", "paused"]


class RunnerProtocol(Protocol):
    """Protocol for job runners (SingleNodeJobRunner, StubRunner, etc.)."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def is_running(self) -> bool: ...
    def run_once(self, job: Job) -> dict | None: ...
    def cancel_current(self) -> None: ...


# Type alias for runner factory callable
RunnerFactory = Callable[[JobQueue, Callable[[Job], dict] | None], RunnerProtocol]


class JobService:
    """Bridge between JobQueue, runner, and history for higher-level orchestration.

    PR-0114C-T(x): Supports dependency injection for runner and history service:
    - runner: Direct runner instance (legacy API, for backward compat)
    - runner_factory: Factory callable to create runner (preferred for DI)
    - history_service: History service instance (can be NullHistoryService in tests)
    """

    EVENT_QUEUE_UPDATED = "queue_updated"
    EVENT_JOB_STARTED = "job_started"
    EVENT_JOB_FINISHED = "job_finished"
    EVENT_JOB_FAILED = "job_failed"
    EVENT_WATCHDOG_VIOLATION = "watchdog_violation"
    EVENT_QUEUE_EMPTY = "queue_empty"
    EVENT_QUEUE_STATUS = "queue_status"

    def __init__(
        self,
        job_queue: JobQueue,
        runner: RunnerProtocol | None = None,
        history_store: JobHistoryStore | None = None,
        history_service: JobHistoryService | None = None,
        *,
        runner_factory: RunnerFactory | None = None,
        run_callable: Callable[[Job], dict] | None = None,
        watchdog_config: WatchdogConfig | None = None,
        process_container_config: ProcessContainerConfig | None = None,
        container_factory: Callable[[str, ProcessContainerConfig], ProcessContainer] | None = None,
    ) -> None:
        """Initialize JobService with queue, runner, and history dependencies.

        Args:
            job_queue: The job queue to manage.
            runner: Direct runner instance (legacy API). If None, uses runner_factory.
            history_store: Optional history store for persistence.
            history_service: Optional history service. If None and history_store
                provided, creates a default JobHistoryService.
            runner_factory: Factory to create runner. Signature:
                (job_queue, run_callable) -> RunnerProtocol.
                If both runner and runner_factory are None, creates SingleNodeJobRunner.
            run_callable: Callable to execute jobs, passed to runner/factory.
        """
        self.job_queue = job_queue
        self.history_store = history_store
        self._run_callable = run_callable

        # PR-0114C-T(x): Support runner injection via factory or direct instance
        if runner is not None:
            self.runner = runner
        elif runner_factory is not None:
            self.runner = runner_factory(job_queue, run_callable)
        else:
            # Default: create SingleNodeJobRunner (production behavior)
            self.runner = SingleNodeJobRunner(
                job_queue,
                run_callable=run_callable,
                poll_interval=0.05,
            )

        # PR-0114C-T(x): Support history service injection
        self._history_service = history_service
        if self._history_service is None and history_store is not None:
            try:
                self._history_service = JobHistoryService(job_queue, history_store)
            except Exception:
                self._history_service = None

        self._listeners: dict[str, list[Callable[..., None]]] = {}
        self._queue_status: QueueStatus = "idle"
        self._execution_metadata: dict[str, JobExecutionMetadata] = {}
        self._watchdog_config: WatchdogConfig = watchdog_config or get_watchdog_config()
        self._active_watchdogs: dict[str, JobWatchdog] = {}
        self._watchdog_event_history: deque[dict[str, Any]] = deque(maxlen=32)
        self._cleanup_history: deque[dict[str, Any]] = deque(maxlen=32)
        self._process_container_config: ProcessContainerConfig = (
            process_container_config or get_process_container_config()
        )
        self._container_factory = container_factory or build_process_container
        self._process_containers: dict[str, ProcessContainer] = {}
        self.job_queue.register_status_callback(self._handle_job_status_change)

    @property
    def queue(self) -> JobQueue:
        """Alias for job_queue for controller compatibility."""
        return self.job_queue

    def register_callback(self, event: str, callback: Callable[..., None]) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def enqueue(self, job: Job) -> None:
        self.job_queue.submit(job)
        self._emit_queue_updated()

    def run_now(self, job: Job) -> None:
        self.enqueue(job)
        try:
            self.run_next_now()
        except Exception:
            pass
        if not self.runner.is_running():
            self.runner.start()

    def submit_job_with_run_mode(self, job: Job) -> None:
        """Submit a job respecting its configured run_mode."""
        mode = (job.run_mode or "queue").lower()
        log_with_ctx(
            logger,
            logging.INFO,
            f"Submitting job {job.job_id} with run_mode={mode}",
            ctx=LogContext(job_id=job.job_id, subsystem="job_service"),
            extra_fields={"run_mode": mode},
        )
        if mode == "direct":
            self.submit_direct(job)
        else:
            self.submit_queued(job)

    def submit_direct(self, job: Job) -> dict | None:
        """Execute a job synchronously (bypasses queue for 'Run Now' semantics).
        
        PR-106: Explicit API for direct execution path.
        """
        log_with_ctx(
            logger,
            logging.INFO,
            f"Direct execution of job {job.job_id}",
            ctx=LogContext(job_id=job.job_id, subsystem="job_service"),
        )
        self.job_queue.submit(job)
        self._emit_queue_updated()
        try:
            result = self.runner.run_once(job)
            return result
        except Exception:
            raise

    def submit_queued(self, job: Job) -> None:
        """Submit a job to the queue for background execution.
        
        PR-106: Explicit API for queued execution path.
        """
        log_with_ctx(
            logger,
            logging.INFO,
            f"Queuing job {job.job_id} for background execution",
            ctx=LogContext(job_id=job.job_id, subsystem="job_service"),
        )
        self.enqueue(job)
        if not self.runner.is_running():
            self.runner.start()

    def submit_jobs(self, jobs: list[Job]) -> None:
        """Submit multiple jobs respecting each job's configured run_mode.
        
        PR-044: Batch submission for randomizer variant jobs.
        """
        for job in jobs:
            self.submit_job_with_run_mode(job)

    def pause(self) -> None:
        self.runner.stop()
        self._set_queue_status("paused")

    def resume(self) -> None:
        self.runner.start()
        self._set_queue_status("running")

    def cancel_current(self) -> Job | None:
        """Cancel the currently running job and return it if one was active."""
        running = self._find_running_job()
        if running is None and getattr(self.runner, "current_job", None) is not None:
            running = self.runner.current_job
        if running:
            self.cancel_job(running.job_id, reason="cancel_requested")
        self.runner.cancel_current()
        self._set_queue_status("idle")
        return running

    def cancel_job(self, job_id: str, *, reason: str | None = None) -> None:
        """Cancel the job with the given ID and clean up associated processes."""
        if not job_id:
            return
        job = self.job_queue.mark_cancelled(job_id, reason or "cancelled")
        if job is not None:
            self.cleanup_external_processes(job_id, reason=reason)
        self._set_queue_status("idle")

    def register_external_process(self, job_id: str, pid: int) -> None:
        """Track an external PID so we can clean it up when the job terminates."""
        if not job_id or pid <= 0:
            return
        container = self._ensure_container(job_id)
        container.add_pid(pid)
        meta = self._ensure_job_metadata(job_id)
        if pid in meta.external_pids:
            return
        meta.external_pids.append(pid)

    def record_retry_attempt(
        self,
        job_id: str,
        stage: str | None,
        attempt_index: int,
        max_attempts: int,
        reason: str,
    ) -> None:
        """Persist retry metadata so diagnostics can report retry history."""
        if not job_id:
            return
        metadata = self._ensure_job_metadata(job_id)
        metadata.retry_attempts.append(
            RetryAttempt(
                stage=stage or "pipeline",
                attempt_index=attempt_index,
                max_attempts=max_attempts,
                reason=reason,
            )
        )

    def cleanup_external_processes(self, job_id: str, *, reason: str | None = None) -> None:
        """Terminate and clear tracked PIDs for the provided job."""
        metadata = self._pop_combined_metadata(job_id)
        if not metadata or not metadata.external_pids:
            return
        reason_suffix = f" ({reason})" if reason else ""
        log_with_ctx(
            logger,
            logging.INFO,
            "Cleaning external processes",
            ctx=LogContext(job_id=job_id, subsystem="job_service"),
            extra_fields={
                "pid_count": len(metadata.external_pids),
                "reason": reason or "cleanup",
            },
        )
        self._record_cleanup_event(job_id, list(set(metadata.external_pids)), reason or "cleanup")
        for pid in set(metadata.external_pids):
            _terminate_process_tree(pid)

    def _record_cleanup_event(self, job_id: str, pids: list[int], reason: str) -> None:
        """Keep a limited history of cleanup activity for diagnostics."""
        self._cleanup_history.append(
            {
                "job_id": job_id,
                "pids": list(pids),
                "reason": reason,
                "timestamp": time.time(),
            }
        )

    def list_queue(self) -> list[Job]:
        return self.job_queue.list_jobs()

    def _find_running_job(self) -> Job | None:
        """Return the currently running job known to the queue."""
        for job in self.job_queue.list_jobs():
            if job.status == JobStatus.RUNNING:
                return job
        return None

    def _ensure_job_metadata(self, job_id: str) -> JobExecutionMetadata:
        """Return the metadata container for a job, merging any pending entries."""
        job = self.job_queue.get_job(job_id)
        fallback = self._execution_metadata.pop(job_id, None)
        if job is not None:
            meta = job.execution_metadata
            if fallback:
                for pid in fallback.external_pids:
                    if pid not in meta.external_pids:
                        meta.external_pids.append(pid)
                for attempt in fallback.retry_attempts:
                    meta.retry_attempts.append(attempt)
            return meta
        if fallback:
            self._execution_metadata[job_id] = fallback
            return fallback
        metadata = JobExecutionMetadata()
        self._execution_metadata[job_id] = metadata
        return metadata

    def _pop_combined_metadata(self, job_id: str) -> JobExecutionMetadata | None:
        """Merge metadata from cached entries and the live job, clearing both."""
        fallback = self._execution_metadata.pop(job_id, None)
        combined_pids: set[int] = set(fallback.external_pids if fallback else [])
        job = self.job_queue.get_job(job_id)
        if job and job.execution_metadata.external_pids:
            combined_pids.update(job.execution_metadata.external_pids)
            job.execution_metadata.external_pids.clear()
        if not combined_pids:
            return None
        return JobExecutionMetadata(external_pids=list(combined_pids))

    def _ensure_container(self, job_id: str) -> ProcessContainer:
        container = self._process_containers.get(job_id)
        if container is not None:
            return container
        try:
            container = self._container_factory(job_id, self._process_container_config)
        except Exception as exc:
            log_with_ctx(
                logger,
                logging.DEBUG,
                "Failed to build process container",
                ctx=LogContext(job_id=job_id, subsystem="job_service"),
                extra_fields={"error": str(exc)},
            )
            container = NullProcessContainer(job_id, self._process_container_config)  # type: ignore[call-arg]
        self._process_containers[job_id] = container
        return container

    def _destroy_container(self, job_id: str) -> None:
        container = self._process_containers.pop(job_id, None)
        if container is None:
            return
        try:
            container.kill_all()
            log_with_ctx(
                logger,
                logging.INFO,
                f"{PROCESS_CONTAINER_LOG_PREFIX} job kill_all invoked",
                ctx=LogContext(job_id=job_id, subsystem="process_container"),
            )
        except Exception as exc:
            log_with_ctx(
                logger,
                logging.DEBUG,
                "Container kill_all failed",
                ctx=LogContext(job_id=job_id, subsystem="process_container"),
                extra_fields={"error": str(exc)},
            )
        try:
            container.teardown()
        except Exception as exc:
            log_with_ctx(
                logger,
                logging.DEBUG,
                "Container teardown failed",
                ctx=LogContext(job_id=job_id, subsystem="process_container"),
                extra_fields={"error": str(exc)},
            )

    def get_diagnostics_snapshot(self) -> dict[str, Any]:
        """Return diagnostics data surfaced to GUI/diagnostic tooling."""
        jobs = []
        for job in self.job_queue.list_jobs():
            jobs.append(
                {
                    "job_id": job.job_id,
                    "status": job.status.value,
                    "priority": job.priority.name,
                    "run_mode": job.run_mode,
                    "external_pids": list(job.execution_metadata.external_pids),
                    "retry_attempts": [asdict(attempt) for attempt in job.execution_metadata.retry_attempts],
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                    "error_envelope": serialize_envelope(job.error_envelope),
                }
            )
        metadata_cache = {
            job_id: list(metadata.external_pids)
            for job_id, metadata in self._execution_metadata.items()
            if metadata.external_pids
        }
        containers = {
            job_id: container.inspect() for job_id, container in self._process_containers.items()
        }
        return {
            "jobs": jobs,
            "cached_metadata": metadata_cache,
            "containers": containers,
            "active_watchdogs": list(self._active_watchdogs.keys()),
            "watchdog_events": list(self._watchdog_event_history),
            "cleanup_history": list(self._cleanup_history),
            "process_container_config": asdict(self._process_container_config),
        }

    def run_next_now(self) -> None:
        """Synchronously run the next queued job via the runner."""
        job = self.job_queue.get_next_job()
        if job is None:
            return
        self._set_queue_status("running")
        try:
            self.runner.run_once(job)
        finally:
            if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
                self._set_queue_status("idle")

    def _handle_job_status_change(self, job: Job, status: JobStatus) -> None:
        if status == JobStatus.RUNNING:
            self._emit(self.EVENT_JOB_STARTED, job)
            self._start_watchdog(job)
        elif status == JobStatus.COMPLETED:
            self._emit(self.EVENT_JOB_FINISHED, job)
            self._record_job_history(job, status)
        elif status in {JobStatus.CANCELLED, JobStatus.FAILED}:
            self._emit(self.EVENT_JOB_FAILED, job)
            if status == JobStatus.FAILED:
                self._record_job_history(job, status)
        if status in {JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED}:
            self._stop_watchdog(job.job_id)
            self.cleanup_external_processes(job.job_id, reason=status.value.lower())
            self._destroy_container(job.job_id)
        self._emit_queue_updated()
        if not any(j.status == JobStatus.QUEUED for j in self.job_queue.list_jobs()):
            self._emit(self.EVENT_QUEUE_EMPTY)

    def _start_watchdog(self, job: Job) -> None:
        if not self._watchdog_config.enabled or psutil is None:
            return
        if job.job_id in self._active_watchdogs:
            return
        watchdog = JobWatchdog(
            job_id=job.job_id,
            metadata=job.execution_metadata,
            config=self._watchdog_config,
            violation_callback=self._on_watchdog_violation,
        )
        self._active_watchdogs[job.job_id] = watchdog
        watchdog.start()

    def _stop_watchdog(self, job_id: str) -> None:
        watchdog = self._active_watchdogs.pop(job_id, None)
        if watchdog:
            watchdog.stop()

    def _record_watchdog_event(self, job_id: str, envelope: UnifiedErrorEnvelope) -> None:
        reason = envelope.context.get("watchdog_reason", envelope.error_type)
        self._watchdog_event_history.append(
            {
                "job_id": job_id,
                "reason": reason,
                "info": dict(envelope.context),
                "envelope": serialize_envelope(envelope),
                "timestamp": time.time(),
            }
        )

    def _on_watchdog_violation(self, job_id: str, envelope: UnifiedErrorEnvelope) -> None:
        reason = envelope.context.get("watchdog_reason", envelope.error_type)
        info = envelope.context
        message = f"{WATCHDOG_LOG_PREFIX} job={job_id} reason={reason} info={info}"
        log_with_ctx(
            logger,
            logging.WARNING,
            message,
            ctx=LogContext(subsystem="watchdog"),
            extra_fields={"error_envelope": serialize_envelope(envelope)},
        )
        self._stop_watchdog(job_id)
        self._record_watchdog_event(job_id, envelope)
        self._emit(self.EVENT_WATCHDOG_VIOLATION, job_id, envelope)
        job = self.job_queue.get_job(job_id)
        if job:
            job.error_envelope = envelope
        self.cancel_job(job_id, reason=f"watchdog_{reason.lower()}")

    def _record_job_history(self, job: Job, status: JobStatus) -> None:
        if not self._history_service:
            return
        try:
            if status == JobStatus.COMPLETED:
                self._history_service.record(job, result=job.result)
            elif status == JobStatus.FAILED:
                self._history_service.record_failure(job, error=job.error_message)
        except Exception:
            logging.debug("Failed to record job history for %s", job.job_id, exc_info=True)

    def _emit_queue_updated(self) -> None:
        jobs = self.job_queue.list_jobs()
        summaries = [format_queue_job_summary(job) for job in jobs]
        self._emit(self.EVENT_QUEUE_UPDATED, summaries)

    def _set_queue_status(self, status: QueueStatus) -> None:
        if self._queue_status != status:
            self._queue_status = status
            self._emit(self.EVENT_QUEUE_STATUS, status)

    def _emit(self, event: str, *args: Any) -> None:
        for callback in self._listeners.get(event, []):
            try:
                callback(*args)
            except Exception:
                continue
