"""JobService bridges JobQueue, runner, and history for higher-level orchestration."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict
from datetime import datetime
import logging
import time
from threading import Lock

from typing import Any, Callable, Literal, Protocol

from src.controller.job_history_service import JobHistoryService
from src.controller.job_lifecycle_logger import JobLifecycleLogger
from src.config.app_config import get_process_container_config, get_watchdog_config
from src.queue.job_model import Job, JobExecutionMetadata, JobPriority, JobStatus, RetryAttempt
from src.gui.pipeline_panel_v2 import format_queue_job_summary
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.queue.job_history_store import JobHistoryStore
from src.pipeline.job_models_v2 import (
    JobStatusV2,
    NormalizedJobRecord,
    UnifiedJobSummary,
    JobView,
)
from src.pipeline.job_requests_v2 import PipelineRunMode, PipelineRunRequest
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
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot

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
    EVENT_JOB_SUBMITTED = "job_submitted"
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
        job_lifecycle_logger: JobLifecycleLogger | None = None,
        require_normalized_records: bool = False,
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
        log_with_ctx(
            logger,
            logging.DEBUG,
            "JobService initialized with runner",
            ctx=LogContext(subsystem="job_service"),
            extra_fields={"runner_type": type(self.runner).__name__},
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
        self._job_lifecycle_logger = job_lifecycle_logger
        self._require_normalized_records = bool(require_normalized_records)
        self.job_queue.register_status_callback(self._handle_job_status_change)
        self._runner_lock = Lock()
        self._worker_started = False

    @property
    def queue(self) -> JobQueue:
        """Alias for job_queue for controller compatibility."""
        return self.job_queue

    def register_callback(self, event: str, callback: Callable[..., None]) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def set_status_callback(self, name: str, callback: Callable[[Job, JobStatus], None]) -> None:
        """PR-D: Register a callback for job status changes with full job + status info.
        
        Args:
            name: Identifier for this callback (e.g., "gui_queue_history")
            callback: Function that receives (job: Job, status: JobStatus)
        """
        # Use a special event type for status callbacks
        event_key = f"_status_callback_{name}"
        self._listeners.setdefault(event_key, []).append(callback)

    def set_job_lifecycle_logger(self, logger: JobLifecycleLogger | None) -> None:
        self._job_lifecycle_logger = logger

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
        record = self._prepare_job_for_submission(job)
        if job.status == JobStatus.FAILED:
            # Record the failed submission without attempting execution
            self.job_queue.submit(job)
            self._notify_job_submitted(job)
            self._emit_queue_updated()
            self._handle_job_status_change(job, JobStatus.FAILED)
            return
        if mode == "direct":
            self.submit_direct(job)
        else:
            self.submit_queued(job)

    def _prepare_job_for_submission(self, job: Job) -> NormalizedJobRecord | None:
        """Ensure normalized metadata is present and log previews as needed."""
        record = getattr(job, "_normalized_record", None)
        snapshot = getattr(job, "snapshot", None) or {}
        if record is None and snapshot:
            record = normalized_job_from_snapshot(snapshot)
        if record is None and self._require_normalized_records:
            self._fail_job(job, "missing_snapshot", "Job is missing normalized metadata.")
            return None
        if record is not None:
            ok, details = self._validate_normalized_record(record)
            if not ok:
                self._fail_job(job, details.get("code", "validation_failed"), details.get("message", "Validation failed"))
            else:
                job.unified_summary = record.to_unified_summary()
                setattr(job, "_normalized_record", record)
        return record

    def _job_from_njr(
        self,
        record: NormalizedJobRecord,
        run_request: PipelineRunRequest,
        *,
        priority: JobPriority = JobPriority.NORMAL,
    ) -> Job:
        # PR-CORE1-B3/C2: NJR-backed jobs are purely NJR-only and don't store pipeline_config.
        job = Job(
            job_id=record.job_id,
            priority=priority,
            run_mode=run_request.run_mode.value,
            source=run_request.source.value,
            prompt_source="pack",
            prompt_pack_id=record.prompt_pack_id or run_request.prompt_pack_id,
            randomizer_metadata=record.randomizer_summary,
            variant_index=record.variant_index,
            variant_total=record.variant_total,
        )
        job.snapshot = asdict(record)
        job._normalized_record = record  # type: ignore[attr-defined]
        return job

    def enqueue_njrs(self, njrs: list[NormalizedJobRecord], run_request: PipelineRunRequest) -> list[str]:
        """Enqueue a batch of NormalizedJobRecord instances."""
        job_ids: list[str] = []
        for record in njrs[: run_request.max_njr_count]:
            job = self._job_from_njr(record, run_request)
            self.submit_job_with_run_mode(job)
            job_ids.append(job.job_id)
        return job_ids

    def run_njrs_direct(self, njrs: list[NormalizedJobRecord], run_request: PipelineRunRequest) -> list[str]:
        """Run NJRs immediately (Run Now semantics)."""
        job_ids: list[str] = []
        for record in njrs[: run_request.max_njr_count]:
            job = self._job_from_njr(record, run_request)
            job.run_mode = PipelineRunMode.DIRECT.value
            self.submit_job_with_run_mode(job)
            job_ids.append(job.job_id)
        return job_ids

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
        self._notify_job_submitted(job)
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
        self._notify_job_submitted(job)
        if not self.runner.is_running():
            log_with_ctx(
                logger,
                logging.INFO,
                "Queue worker starting",
                ctx=LogContext(job_id=job.job_id, subsystem="job_service"),
                extra_fields={"runner": type(self.runner).__name__},
            )
        else:
            log_with_ctx(
                logger,
                logging.DEBUG,
                "Queue worker already running; job will be picked up by worker loop",
                ctx=LogContext(job_id=job.job_id, subsystem="job_service"),
            )
        self._ensure_runner_started()

    def _ensure_runner_started(self) -> None:
        with self._runner_lock:
            if self._worker_started or self.runner.is_running():
                return
            runner_type = type(self.runner).__name__
            try:
                self.runner.start()
            except Exception as exc:
                log_with_ctx(
                    logger,
                    logging.ERROR,
                    "Queue worker failed to start",
                    ctx=LogContext(subsystem="job_service"),
                    extra_fields={"runner": runner_type, "error": str(exc)},
                )
                raise
            self._worker_started = True

    def _validate_normalized_record(self, record: NormalizedJobRecord) -> tuple[bool, dict[str, str]]:
        """Basic validation of normalized job metadata before queue acceptance."""
        if not record.job_id:
            return False, {"code": "missing_job_id", "message": "Normalized job is missing job_id."}
        prompt_source = getattr(record, "prompt_source", None) or ""
        prompt_pack_id = getattr(record, "prompt_pack_id", "")
        if prompt_source.lower() != "pack" or not prompt_pack_id:
            log_with_ctx(
                logger,
                logging.ERROR,
                "Normalized job missing pack identity",
                ctx=LogContext(job_id=record.job_id, subsystem="job_service"),
                extra_fields={
                    "prompt_source": prompt_source,
                    "prompt_pack_id": prompt_pack_id,
                    "prompt_pack_name": getattr(record, "prompt_pack_name", None),
                    "sample_prompt": (getattr(record, "positive_prompt", "") or "").strip()[:120],
                },
            )
            return False, {
                "code": "pack_required",
                "message": f"Normalized job '{record.job_id}' must declare prompt_source=pack and prompt_pack_id.",
            }
        if not record.positive_prompt or not record.positive_prompt.strip():
            return False, {
                "code": "missing_prompt",
                "message": f"Normalized job '{record.job_id}' must include a positive prompt.",
            }
        if record.config is None:
            return False, {
                "code": "missing_config",
                "message": f"Normalized job '{record.job_id}' lacks a merged config payload.",
            }
        if not record.stage_chain:
            return False, {
                "code": "missing_stage_chain",
                "message": f"Normalized job '{record.job_id}' must have at least one stage in stage_chain.",
            }
        return True, {"code": "ok", "message": "ok"}

    def _fail_job(self, job: Job, code: str, message: str) -> None:
        """Fail a job gracefully with a diagnostic envelope."""
        job.status = JobStatus.FAILED
        job.error_message = message
        job.error_envelope = UnifiedErrorEnvelope(
            error_type=code,
            subsystem="job_service",
            severity="error",
            message=message,
            cause=None,
            stack="",
            job_id=job.job_id,
            stage=None,
            context={"code": code},
        )
        job.result = {
            "status": "failed",
            "error": message,
            "code": code,
        }
        log_with_ctx(
            logger,
            logging.WARNING,
            "Job validation failed",
            ctx=LogContext(job_id=job.job_id, subsystem="job_service"),
            extra_fields={"code": code, "message": message},
        )

    def _notify_job_submitted(self, job: Job) -> None:
        """Emit a lifecycle event and log the submission when a job is accepted."""
        record = getattr(job, "_normalized_record", None)
        summary = record.to_unified_summary() if record else getattr(job, "unified_summary", None)
        self._emit(self.EVENT_JOB_SUBMITTED, job, summary)
        if self._job_lifecycle_logger:
            self._job_lifecycle_logger.log_job_submitted(
                source=getattr(job, "source", "job_service") or "job_service",
                job_id=job.job_id,
            )

    def submit_jobs(self, jobs: list[Job]) -> None:
        """Submit multiple jobs respecting each job's configured run_mode.
        
        PR-044: Batch submission for randomizer variant jobs.
        """
        for job in jobs:
            self.submit_job_with_run_mode(job)

    def pause(self) -> None:
        self._stop_runner()
        self._set_queue_status("paused")

    def resume(self) -> None:
        self._ensure_runner_started()
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
            record = getattr(job, "_normalized_record", None)
            result_code = None
            if isinstance(getattr(job, "result", None), dict):
                result_code = job.result.get("code")
            jobs.append(
                {
                    "job_id": job.job_id,
                    "status": job.status.value,
                    "priority": job.priority.name,
                    "run_mode": job.run_mode,
                    "prompt_source": getattr(job, "prompt_source", None),
                    "prompt_pack_id": getattr(job, "prompt_pack_id", None),
                    "validation_status": result_code or ("ok" if job.status != JobStatus.FAILED else "failed"),
                    "legacy_snapshot_mode": bool(getattr(record, "extra_metadata", {}).get("legacy_snapshot_mode"))
                    if record
                    else False,
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

    def _stop_runner(self) -> None:
        with self._runner_lock:
            if not self._worker_started:
                return
            runner_type = type(self.runner).__name__
            log_with_ctx(
                logger,
                logging.INFO,
                "Queue worker stopping (runner=%s)",
                ctx=LogContext(subsystem="job_service"),
                extra_fields={"runner": runner_type},
            )
            self.runner.stop()
            self._worker_started = False

    def _handle_job_status_change(self, job: Job, status: JobStatus) -> None:
        log_with_ctx(
            logger,
            logging.INFO,
            "Job status change",
            ctx=LogContext(job_id=job.job_id, subsystem="job_service"),
            extra_fields={
                "status": status.value,
                "run_mode": job.run_mode,
                "prompt_pack_id": getattr(job, "prompt_pack_id", None),
            },
        )
        if status == JobStatus.RUNNING:
            self._log_job_started(job.job_id)
            self._emit(self.EVENT_JOB_STARTED, job)
            self._start_watchdog(job)
        elif status == JobStatus.COMPLETED:
            self._log_job_finished(job.job_id, "completed", "Job completed successfully.")
            self._emit(self.EVENT_JOB_FINISHED, job)
            self._record_job_history(job, status)
        elif status == JobStatus.CANCELLED:
            self._log_job_finished(job.job_id, "cancelled", job.error_message or "Job cancelled.")
            self._emit(self.EVENT_JOB_FAILED, job)
        elif status == JobStatus.FAILED:
            self._log_job_finished(job.job_id, "failed", job.error_message or "Job failed.")
            self._emit(self.EVENT_JOB_FAILED, job)
            self._record_job_history(job, status)
        if status in {JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED}:
            self._stop_watchdog(job.job_id)
            self.cleanup_external_processes(job.job_id, reason=status.value.lower())
            self._destroy_container(job.job_id)
        
        # PR-D: Emit status-specific callbacks for GUI queue/history updates
        self._emit_status_callbacks(job, status)
        
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

    def _emit_status_callbacks(self, job: Job, status: JobStatus) -> None:
        """PR-D: Emit status callbacks registered via set_status_callback."""
        # Find all status callback listeners
        status_callbacks = [
            cb
            for key, callbacks in self._listeners.items()
            if key.startswith("_status_callback_")
            for cb in callbacks
        ]
        
        self._build_job_view(job, status)
        for callback in status_callbacks:
            try:
                callback(job, status)
            except Exception as exc:
                logger.debug("Status callback failed: %s", exc)

    def _build_job_view(self, job: Job, status: JobStatus) -> JobView:
        """Build a JobView derived from the NJR snapshot for UI consumers."""
        try:
            normalized_status = JobStatusV2(status.value)
        except ValueError:
            normalized_status = JobStatusV2.QUEUED

        created_iso = job.created_at.isoformat() if job.created_at else None
        started_iso = job.started_at.isoformat() if job.started_at else None
        completed_iso = job.completed_at.isoformat() if job.completed_at else None
        record = normalized_job_from_snapshot(getattr(job, "snapshot", {}) or {})

        if record is not None:
            record.status = normalized_status
            if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                if completed_iso:
                    record.completed_at = job.completed_at
            view = record.to_job_view(
                status=normalized_status.value,
                created_at=created_iso,
                started_at=started_iso,
                completed_at=completed_iso,
                is_active=job.status in {JobStatus.QUEUED, JobStatus.RUNNING},
                last_error=job.error_message,
                worker_id=getattr(job, "worker_id", None),
                result=getattr(job, "result", None),
            )
            summary = record.to_unified_summary()
            setattr(job, "unified_summary", summary)
            return view

        fallback_label = getattr(job, "label", job.job_id) or job.job_id
        fallback_summary = UnifiedJobSummary.from_job(job, normalized_status)
        setattr(job, "unified_summary", fallback_summary)
        return JobView(
            job_id=job.job_id,
            status=normalized_status.value,
            model="unknown",
            prompt="",
            negative_prompt=None,
            seed=getattr(job, "seed", None),
            label=fallback_label,
            positive_preview="",
            negative_preview=None,
            stages_display="txt2img",
            estimated_images=getattr(job, "total_images", 1) or 1,
            created_at=created_iso or datetime.utcnow().isoformat(),
            prompt_pack_id=getattr(job, "prompt_pack_id", "") or "",
            prompt_pack_name="",
            variant_label=None,
            batch_label=None,
            started_at=started_iso,
            completed_at=completed_iso,
            is_active=job.status in {JobStatus.QUEUED, JobStatus.RUNNING},
            last_error=job.error_message,
            worker_id=getattr(job, "worker_id", None),
            result=getattr(job, "result", None),
        )

    def _log_job_started(self, job_id: str | None) -> None:
        if not self._job_lifecycle_logger or not job_id:
            return
        self._job_lifecycle_logger.log_job_started(source="job_service", job_id=job_id)

    def _log_job_finished(self, job_id: str | None, status: str, message: str) -> None:
        if not self._job_lifecycle_logger or not job_id:
            return
        self._job_lifecycle_logger.log_job_finished(
            source="job_service", job_id=job_id, status=status, message=message
        )
