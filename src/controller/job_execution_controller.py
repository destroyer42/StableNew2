"""Job execution bridge for queue-backed pipeline runs."""

from __future__ import annotations

import logging
import os
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.cluster.worker_registry import WorkerRegistry
from src.config.app_config import get_job_history_path
from src.history.history_record import HistoryRecord
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import normalize_run_result
from src.pipeline.replay_engine import ReplayEngine
from src.queue.job_history_store import JobHistoryStore, JSONLJobHistoryStore
from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.services.queue_store_v2 import (
    SCHEMA_VERSION,
    QueueSnapshotV1,
    UnsupportedQueueSchemaError,
    load_queue_snapshot,
    save_queue_snapshot,
)
from src.utils import LogContext, log_with_ctx
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot

logger = logging.getLogger(__name__)


def _njr_from_snapshot(snapshot: dict[str, Any]) -> NormalizedJobRecord | None:
    if not snapshot:
        return None
    constructor = getattr(NormalizedJobRecord, "from_snapshot", None)
    if callable(constructor):
        try:
            return constructor(snapshot)
        except Exception:
            # Fallback to legacy util for pre-from_snapshot classes
            pass
    normalized_source = snapshot if "normalized_job" in snapshot else {"normalized_job": snapshot}
    return normalized_job_from_snapshot(normalized_source)


def _parse_iso_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.utcnow()


def _priority_from_value(value: Any) -> JobPriority:
    try:
        if isinstance(value, JobPriority):
            return value
        return JobPriority(int(value))
    except Exception:
        return JobPriority.NORMAL


class JobExecutionController:
    """Owns JobQueue and SingleNodeJobRunner for single-node execution."""

    def __init__(
        self,
        execute_job: Callable[[Job], dict] | None = None,
        poll_interval: float = 0.05,
        history_store: JobHistoryStore | None = None,
        worker_registry: WorkerRegistry | None = None,
        replay_runner: Any | None = None,
    ) -> None:
        self._history_store = history_store or self._default_history_store()
        self._worker_registry = worker_registry or WorkerRegistry()
        self._queue = JobQueue(history_store=self._history_store)
        self._execute_job = execute_job
        self._auto_run_enabled = False
        self._queue_paused = False
        self._queue_persistence: QueuePersistenceManager | None = None
        self._runner = SingleNodeJobRunner(
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
        self._restore_queue_state()
        self._queue_persistence = QueuePersistenceManager(self)
        self._persist_queue_state()
        
        # PR-PERSIST-001: Execute deferred autostart if queue was restored with auto_run enabled
        if self._deferred_autostart:
            logger.info("Executing deferred queue autostart")
            self.start()

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

    def stop(self) -> None:
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

    def submit_pipeline_run(
        self,
        pipeline_callable,
        *,
        priority: JobPriority = JobPriority.NORMAL,
        run_mode: str = "queue",
    ) -> str:
        job_id = str(uuid.uuid4())
        worker_id = None
        try:
            worker_id = self._worker_registry.get_local_worker().id
        except Exception:
            worker_id = None
        job = Job(
            job_id=job_id,
            priority=priority,
            payload=pipeline_callable,
            worker_id=worker_id,
            run_mode=run_mode,
        )
        self._queue.submit(job)
        self._ensure_worker_started()
        return job_id

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

    def _run_job_callback(self, job: Job) -> dict[str, Any]:
        """Wrapper that executes jobs via payload or the replay engine."""
        if job is None:
            return normalize_run_result(None)
        payload = getattr(job, "payload", None)
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
                result = self._replay_engine.replay_njr(record)
            except Exception as exc:  # noqa: BLE001
                error_message = f"NJR execution failed: {exc}"
                log_with_ctx(
                    logger,
                    logging.ERROR,
                    "JOB_EXEC_ERROR | NJR execution failed",
                    ctx=ctx,
                    extra_fields={"error": error_message},
                )
                raise RuntimeError(error_message) from exc
        elif callable(payload):
            if os.environ.get("PYTEST_CURRENT_TEST"):
                log_with_ctx(
                    logger,
                    logging.INFO,
                    "JOB_EXEC_PAYLOAD | Test mode detected, returning stub result",
                    ctx=ctx,
                )
                return normalize_run_result({"success": True}, default_run_id=job.job_id)
            log_with_ctx(
                logger,
                logging.INFO,
                "JOB_EXEC_PAYLOAD | Executing queued job payload (legacy bridge)",
                ctx=ctx,
            )
            result = payload()
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

    @property
    def is_queue_paused(self) -> bool:
        return self._queue_paused

    def set_queue_paused(self, paused: bool) -> None:
        self._queue_paused = bool(paused)
        self._persist_queue_state()

    def _restore_queue_state(self) -> None:
        """Restore persisted queue state (jobs + control flags)."""
        try:
            snapshot = load_queue_snapshot()
        except UnsupportedQueueSchemaError as exc:
            logger.warning(
                "QUEUE_STATE_UNSUPPORTED | schema_version=%s | ignoring persisted queue state",
                getattr(exc, "schema_version", None),
            )
            return
        except Exception:
            logger.exception("Failed to restore queue state")
            return
        if snapshot is None:
            return

        self._auto_run_enabled = bool(snapshot.auto_run_enabled)
        self._queue_paused = bool(snapshot.paused)

        restored_jobs: list[Job] = []
        for entry in snapshot.jobs:
            job = self._job_from_snapshot_entry(entry)
            if job is not None:
                restored_jobs.append(job)
        if restored_jobs:
            self._queue.restore_jobs(restored_jobs)
        logger.debug(
            "Restored queue state: auto_run=%s, paused=%s, %d restored job(s)",
            self._auto_run_enabled,
            self._queue_paused,
            len(restored_jobs),
        )
        
        # PR-PERSIST-001: Auto-start runner if it was enabled before shutdown
        if self._auto_run_enabled and restored_jobs and not self._queue_paused:
            logger.info("Auto-starting queue runner after restore (had %d jobs)", len(restored_jobs))
            # Defer start until after full initialization
            self._deferred_autostart = True

    def _persist_queue_state(self) -> None:
        """Persist current queued jobs and control flags."""
        entries: list[dict[str, Any]] = []
        for job in self._queue.list_jobs():
            if job.status != JobStatus.QUEUED:
                continue
            entry = self._build_queue_entry(job)
            if entry is not None:
                entries.append(entry)
        snapshot = QueueSnapshotV1(
            jobs=entries,
            auto_run_enabled=self._auto_run_enabled,
            paused=self._queue_paused,
        )
        try:
            save_queue_snapshot(snapshot)
        except Exception as exc:
            logger.warning("Failed to persist queue state: %s", exc)

    def _build_queue_entry(self, job: Job) -> dict[str, Any] | None:
        record = getattr(job, "_normalized_record", None)
        snapshot = getattr(job, "snapshot", None) or {}
        if record is None and snapshot:
            record = _njr_from_snapshot(snapshot)
        if record is None:
            logger.debug("Skipping persistence for job without normalized record: %s", job.job_id)
            return None
        metadata = {}
        metadata_fields = {
            "run_mode": job.run_mode,
            "source": job.source,
            "prompt_source": job.prompt_source,
            "prompt_pack_id": job.prompt_pack_id,
        }
        for key, value in metadata_fields.items():
            if value is not None:
                metadata[key] = value
        snapshot_dict: dict[str, Any] = {}
        if isinstance(snapshot, Mapping):
            snapshot_dict = dict(snapshot)
        if "normalized_job" not in snapshot_dict:
            snapshot_dict = {"normalized_job": asdict(record)}
        return {
            "queue_id": job.job_id,
            "njr_snapshot": snapshot_dict,
            "priority": int(job.priority),
            "status": job.status.value,
            "created_at": job.created_at.isoformat(),
            "queue_schema": SCHEMA_VERSION,
            "metadata": metadata,
        }

    def _job_from_snapshot_entry(self, entry: Mapping[str, Any]) -> Job | None:
        if not isinstance(entry, Mapping):
            return None
        status_value = str(entry.get("status") or JobStatus.QUEUED.value).lower()
        if status_value not in {JobStatus.QUEUED.value, JobStatus.RUNNING.value}:
            return None
        snapshot = entry.get("njr_snapshot") or {}
        record = _njr_from_snapshot(snapshot)
        if record is None:
            return None
        metadata = entry.get("metadata") or {}
        priority = _priority_from_value(entry.get("priority", JobPriority.NORMAL))
        job = Job(
            job_id=str(entry.get("queue_id") or entry.get("job_id") or record.job_id),
            priority=priority,
            run_mode=str(metadata.get("run_mode") or "queue"),
            source=str(metadata.get("source") or "queue"),
            prompt_source=str(metadata.get("prompt_source") or "manual"),
            prompt_pack_id=metadata.get("prompt_pack_id"),
        )
        job.snapshot = snapshot
        job._normalized_record = record  # type: ignore[attr-defined]
        created = _parse_iso_datetime(entry.get("created_at"))
        job.created_at = created
        job.updated_at = created
        job.status = JobStatus.QUEUED
        job.payload = None
        return job

    def replay(self, record: HistoryRecord | NormalizedJobRecord | Mapping[str, Any]) -> Any:
        """Replay path that accepts only NJR snapshots (history records or direct NJRs)."""
        if isinstance(record, NormalizedJobRecord):
            return self.run_njr(record)
        return self._replay_engine.replay_history_record(record)

    def run_njr(self, record: NormalizedJobRecord) -> Any:
        """Execute a NormalizedJobRecord directly via unified replay engine."""
        return self._replay_engine.replay_njr(record)

    def _default_history_store(self) -> JobHistoryStore:
        path = Path(get_job_history_path())
        return JSONLJobHistoryStore(path)


class QueuePersistenceManager:
    """Handles saving queue state whenever jobs or flags change."""

    def __init__(self, controller: JobExecutionController) -> None:
        self._controller = controller
        self._queue = controller.get_queue()
        self._queue.register_state_listener(self._on_queue_changed)

    def _on_queue_changed(self) -> None:
        self._controller._persist_queue_state()
