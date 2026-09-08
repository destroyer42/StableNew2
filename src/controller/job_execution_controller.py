"""Job execution bridge for queue-backed pipeline runs."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Mapping
from typing import Any

from src.cluster.worker_registry import WorkerRegistry
from src.history.history_record import HistoryRecord
from src.history.history_schema_v26 import InvalidHistoryRecord, validate_entry
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import normalize_run_result
from src.pipeline.replay_engine import ReplayEngine
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.job_history_store import JobHistoryStore
from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from src.state.workspace_paths import workspace_paths
from src.utils import LogContext, log_with_ctx
from src.utils.error_envelope_v2 import attach_envelope, get_attached_envelope
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot

logger = logging.getLogger(__name__)


class JobExecutionController:
    """Owns JobQueue and SingleNodeJobRunner for single-node execution."""

    def __init__(
        self,
        execute_job: Callable[[Job], dict] | None = None,
        poll_interval: float = 0.05,
        history_store: JobHistoryStore | None = None,
        repository: JobRepository | None = None,
        worker_registry: WorkerRegistry | None = None,
        replay_runner: Any | None = None,
        queue: JobQueue | None = None,
        runner: SingleNodeJobRunner | None = None,
        restore_state: bool = True,
    ) -> None:
        if history_store is not None:
            if not isinstance(history_store, JobRepository):
                raise TypeError("Live history must project from JobRepository")
            if repository is not None and repository is not history_store:
                raise ValueError("Controller accepts exactly one JobRepository authority")
            repository = history_store
        if queue is not None:
            if repository is not None and queue.repository is not repository:
                raise ValueError("Controller queue and repository must share one authority")
            repository = queue.repository
        if repository is None:
            path = ":memory:" if os.environ.get("PYTEST_CURRENT_TEST") else workspace_paths.job_repository()
            repository = JobRepository(path)
        self._history_store = repository
        self._worker_registry = worker_registry or WorkerRegistry()
        self._queue = queue or JobQueue(repository=repository)
        self._execute_job = execute_job
        self._auto_run_enabled = True
        self._queue_paused = False
        self._runner = runner or SingleNodeJobRunner(
            self._queue,
            self._run_job_callback,
            poll_interval=poll_interval,
            on_status_change=self._on_status,
        )
        self._worker_thread_name: str | None = None

        replay_target: Any | None = replay_runner
        if replay_target is None and hasattr(self._runner, "run_njr"):
            replay_target = self._runner
        if replay_target is None and callable(self._execute_job):

            class _ExecuteAdapter:
                def __init__(self, fn: Callable[[Any], Any]) -> None:
                    self._fn = fn

                def run_njr(self, record: NormalizedJobRecord, *_: Any, **__: Any) -> Any:
                    # Call run_njr method on the runner, not the runner as a function
                    if hasattr(self._fn, "run_njr"):
                        return self._fn.run_njr(record, *_, **__)
                    return self._fn(record)  # type: ignore[arg-type]

            replay_target = _ExecuteAdapter(self._execute_job)
        self._replay_engine = ReplayEngine(replay_target, cancel_token=None)
        self._started = False
        self._lock = threading.Lock()
        self._callbacks: dict[str, Callable[[Job, JobStatus], None]] = {}
        self._status_dispatcher: Callable[[Callable[[], None]], None] | None = None
        self._deferred_autostart = False  # PR-PERSIST-001: Track if we need to auto-start after init
        self._app_state: Any | None = None  # For runtime status updates
        if restore_state:
            self._restore_queue_state()
        
        # PR-STARTUP-PERF: Deferred autostart is now triggered externally after GUI is ready
        # (previously executed here, blocking GUI startup for ~10 seconds)

    def trigger_deferred_autostart(self) -> None:
        """Execute deferred queue autostart if flagged during restore.
        
        PR-STARTUP-PERF: Called after GUI is fully rendered to avoid blocking
        startup when there are queued jobs.
        """
        logger.info("[STARTUP-PERF] trigger_deferred_autostart called, _deferred_autostart=%s", self._deferred_autostart)
        if self._deferred_autostart:
            logger.info("Executing deferred queue autostart")
            self.start()
            self._deferred_autostart = False
        else:
            logger.info("[STARTUP-PERF] Deferred autostart not needed (flag is False)")

    def start(self) -> None:
        with self._lock:
            if not self._started:
                runner_type = type(self._runner).__name__
                self._runner.start()
                thread = getattr(self._runner, "_worker", None)
                self._worker_thread_name = thread.name if thread is not None else None
                logger.info(
                    "Queue worker starting (runner=%s, thread=%s)",
                    runner_type,
                    self._worker_thread_name or "pending",
                )
                self._started = True

    def set_app_state(self, app_state: Any) -> None:
        """Set the app state for runtime status updates."""
        self._app_state = app_state

    def _handle_runtime_status_update(self, status_data: dict[str, Any]) -> None:
        """Handle runtime status updates from pipeline execution.
        
        Converts status dict to RuntimeJobStatus and forwards to app_state.
        """
        job_id = str(status_data.get("job_id") or "")
        job = self._queue.get_job(job_id) if job_id else None
        if job is not None and job.status == JobStatus.RUNNING:
            job.progress = float(status_data.get("progress") or 0.0)
            eta = status_data.get("eta_seconds")
            job.eta_seconds = float(eta) if eta is not None else None
            self._queue.persist_runtime_state(job)

        if not self._app_state:
            return
        
        try:
            from datetime import datetime

            from src.pipeline.job_models_v2 import RuntimeJobStatus
            
            # Create RuntimeJobStatus from status_data
            runtime_status = RuntimeJobStatus(
                job_id=status_data.get("job_id", ""),
                current_stage=status_data.get("current_stage", ""),
                stage_detail=status_data.get("stage_detail"),
                stage_index=status_data.get("stage_index", 0),
                total_stages=status_data.get("total_stages", 1),
                progress=status_data.get("progress", 0.0),
                eta_seconds=status_data.get("eta_seconds"),
                started_at=status_data.get("started_at") or datetime.utcnow(),
                actual_seed=status_data.get("actual_seed"),
                current_step=status_data.get("current_step", 0),
                total_steps=status_data.get("total_steps", 0),
            )
            
            # Update app_state
            if hasattr(self._app_state, "set_runtime_status"):
                self._app_state.set_runtime_status(runtime_status)
        except Exception as exc:
            logger.warning(f"Failed to process runtime status update: {exc}")

    def stop(self) -> None:
        """Stop the queue worker and persist queue state."""
        with self._lock:
            if self._started:
                logger.info(
                    "Queue worker stopping (runner=%s, thread=%s)",
                    type(self._runner).__name__,
                    self._worker_thread_name or "unknown",
                )
                self._runner.stop()
                self._started = False
                self._worker_thread_name = None
        
        # PR-PERSIST-FIX: Save queue state when stopping to ensure queued jobs are persisted
        try:
            self._persist_queue_state()
            logger.debug("Queue state persisted during stop()")
        except Exception as exc:
            logger.warning(f"Failed to persist queue state during stop: {exc}")

    def _ensure_worker_started(self) -> None:
        """Idempotently start the background worker thread if not already running."""
        self.start()

    def cancel_job(self, job_id: str) -> None:
        # Mark as cancelled so runner will skip it if not already running.
        job = next((j for j in self._queue.list_jobs() if j.job_id == job_id), None)
        if job and job.status == JobStatus.QUEUED:
            job.mark_status(JobStatus.CANCELLED)

    def get_job_status(self, job_id: str) -> JobStatus | None:
        job = next((j for j in self._queue.list_jobs() if j.job_id == job_id), None)
        return job.status if job else None

    def set_status_callback(self, key: str, callback: Callable[[Job, JobStatus], None]) -> None:
        self._callbacks[key] = callback

    def clear_status_callback(self, key: str) -> None:
        self._callbacks.pop(key, None)

    def set_status_dispatcher(
        self, dispatcher: Callable[[Callable[[], None]], None] | None
    ) -> None:
        """Set dispatcher used to marshal status callbacks onto the GUI thread."""
        self._status_dispatcher = dispatcher

    def _on_status(self, job: Job, status: JobStatus) -> None:
        for cb in list(self._callbacks.values()):
            try:
                if self._status_dispatcher:

                    def _call(callback=cb, j=job, s=status):
                        callback(j, s)

                    try:
                        self._status_dispatcher(_call)
                    except Exception:
                        cb(job, status)
                else:
                    cb(job, status)
            except Exception:
                pass

    def get_history_store(self) -> JobHistoryStore:
        return self._history_store

    def get_queue(self) -> JobQueue:
        return self._queue

    def get_worker_registry(self) -> WorkerRegistry:
        return self._worker_registry

    def get_runner(self) -> SingleNodeJobRunner:
        return self._runner

    def replace_runner(self, runner: SingleNodeJobRunner) -> None:
        runner_queue = getattr(runner, "job_queue", None)
        if runner_queue is not None and runner_queue is not self._queue:
            raise ValueError("Replacement runner must use JobExecutionController queue")
        with self._lock:
            previous = self._runner
            if previous is runner:
                return
            try:
                if self._started or previous.is_running():
                    previous.stop()
            except Exception:
                pass
            self._runner = runner
            self._started = False
            self._worker_thread_name = None

    def _run_job_callback(self, job: Job) -> dict[str, Any]:
        """Wrapper that executes jobs via payload or the replay engine."""
        if job is None:
            return normalize_run_result(None)
        record = getattr(job, "_normalized_record", None)
        ctx = LogContext(job_id=job.job_id, subsystem="job_exec")
        log_with_ctx(
            logger,
            logging.INFO,
            "JOB_EXEC_START | Dispatching job for execution",
            ctx=ctx,
            extra_fields={
                "run_mode": job.run_mode,
                "has_njr": record is not None,
                "prompt_pack_id": job.prompt_pack_id,
            },
        )
        result: Any | None = None
        if record is not None:
            try:
                log_with_ctx(
                    logger,
                    logging.INFO,
                    "JOB_EXEC_REPLAY | Executing NJR via replay engine",
                    ctx=ctx,
                )
                result = self._replay_engine.replay_njr(record, job=job)
            except Exception as exc:  # noqa: BLE001
                error_message = f"NJR execution failed: {exc}"
                log_with_ctx(
                    logger,
                    logging.ERROR,
                    "JOB_EXEC_ERROR | NJR execution failed",
                    ctx=ctx,
                    extra_fields={"error": error_message},
                )
                wrapped = RuntimeError(error_message)
                diagnostics = getattr(exc, "diagnostics_context", None)
                if isinstance(diagnostics, dict):
                    wrapped.diagnostics_context = diagnostics
                envelope = get_attached_envelope(exc)
                if envelope is not None:
                    attach_envelope(wrapped, envelope)
                raise wrapped from exc
        else:
            error_message = "Missing normalized record for queued job"
            log_with_ctx(
                logger,
                logging.ERROR,
                "JOB_EXEC_ERROR | Missing normalized record for queued job",
                ctx=ctx,
                extra_fields={"run_mode": job.run_mode, "error": error_message},
            )
            raise ValueError(error_message)
        return normalize_run_result(result, default_run_id=job.job_id)

    @property
    def auto_run_enabled(self) -> bool:
        return self._auto_run_enabled

    def set_auto_run_enabled(self, enabled: bool) -> None:
        self._auto_run_enabled = bool(enabled)
        if self._auto_run_enabled:
            log_with_ctx(
                logger,
                logging.INFO,
                "Ensuring queue worker is running (auto_run enabled)",
                ctx=LogContext(subsystem="job_execution_controller"),
                extra_fields={"auto_run": True},
            )
            self._ensure_worker_started()
        self._persist_queue_state()

    def persist_queue_state(self) -> None:
        """Persist the current queue snapshot through the controller-owned store."""
        self._persist_queue_state()

    @property
    def is_queue_paused(self) -> bool:
        return self._queue_paused

    def set_queue_paused(self, paused: bool) -> None:
        self._queue_paused = bool(paused)
        if self._queue_paused:
            self._queue.pause()
        else:
            self._queue.resume()
        self._persist_queue_state()

    def _restore_queue_state(self) -> None:
        """Restore control flags; JobQueue already loaded its repository projection."""
        self._auto_run_enabled = bool(self._history_store.get_setting("auto_run_enabled", True))
        self._queue_paused = self._queue.is_paused()
        restored_jobs = self._queue.list_jobs(status_filter=JobStatus.QUEUED)
        logger.info(
            "[STARTUP-PERF] Restored queue state: auto_run=%s, paused=%s, %d restored job(s)",
            self._auto_run_enabled,
            self._queue_paused,
            len(restored_jobs),
        )
        
        # PR-PERSIST-001: Auto-start runner if it was enabled before shutdown
        if self._auto_run_enabled and restored_jobs and not self._queue_paused:
            logger.info("[STARTUP-PERF] Auto-starting queue runner after restore (had %d jobs)", len(restored_jobs))
            # Defer start until after full initialization
            self._deferred_autostart = True
            logger.info("[STARTUP-PERF] Deferred autostart flag set to True (will start after GUI ready)")
        else:
            logger.info("[STARTUP-PERF] Not setting deferred autostart: auto_run=%s, jobs=%d, paused=%s", 
                       self._auto_run_enabled, len(restored_jobs), self._queue_paused)

    def _persist_queue_state(self) -> None:
        """Persist queue control flags; jobs are persisted at each mutation."""
        self._history_store.set_setting("auto_run_enabled", self._auto_run_enabled)
        self._history_store.set_setting("queue_paused", self._queue.is_paused())

    def replay(self, record: HistoryRecord | NormalizedJobRecord | Mapping[str, Any]) -> Any:
        """Compile replay intent and submit it through the canonical queue path."""
        if isinstance(record, NormalizedJobRecord):
            source_record = record
        else:
            data = record.to_dict() if isinstance(record, HistoryRecord) else dict(record)
            ok, errors = validate_entry(data)
            if not ok:
                raise InvalidHistoryRecord(errors)
            source_record = normalized_job_from_snapshot(data.get("njr_snapshot") or {})
            if source_record is None:
                raise InvalidHistoryRecord(["njr_snapshot could not be hydrated"])
        replay_record = compile_replay_intent(ReplayIntent(source_record))
        job = Job(
            job_id=replay_record.job_id,
            priority=JobPriority.NORMAL,
            run_mode="queue",
            source=replay_record.source.kind.value,
            prompt_source="manual",
            snapshot={"normalized_job": replay_record.to_dict()},
        )
        job._normalized_record = replay_record
        self._queue.submit(job)
        if self._auto_run_enabled:
            self._ensure_worker_started()
        return job.job_id
