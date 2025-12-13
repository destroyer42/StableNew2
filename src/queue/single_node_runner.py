# Subsystem: Queue
# Role: Executes queued jobs on a single node in FIFO/priority order.

"""Single-node job runner that executes jobs from an in-memory queue."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict
from typing import Callable, Optional

from src.pipeline.pipeline_runner import normalize_run_result
from src.queue.job_model import JobStatus, Job
from src.queue.job_queue import JobQueue
from src.utils import LogContext, log_with_ctx
from src.utils.error_envelope_v2 import get_attached_envelope, wrap_exception

logger = logging.getLogger(__name__)
QUEUE_JOB_SOFT_TIMEOUT_SECONDS = 600  # seconds


def _ensure_job_envelope(job: Job | None, exc: Exception) -> None:
    envelope = get_attached_envelope(exc)
    if envelope is None:
        envelope = wrap_exception(
            exc,
            subsystem="queue",
            job_id=job.job_id if job else None,
        )
    if job is not None:
        job.error_envelope = envelope
        if job.execution_metadata.retry_attempts:
            envelope.retry_info = {
                "attempts": [asdict(attempt) for attempt in job.execution_metadata.retry_attempts]
            }


class SingleNodeJobRunner:
    """Background worker that executes jobs from a JobQueue."""

    def __init__(
        self,
        job_queue: JobQueue,
        run_callable: Callable[[Job], dict] | None,
        poll_interval: float = 0.1,
        on_status_change: Callable[[Job, JobStatus], None] | None = None,
        on_activity=None,
    ) -> None:
        self.job_queue = job_queue
        self.run_callable = run_callable
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._on_status_change = on_status_change
        self._current_job: Job | None = None
        self._cancel_current = threading.Event()
        # PR-CORE1-D21B: Activity callback
        self._on_activity = on_activity

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2.0)

    def _worker_loop(self) -> None:
        logger.debug("SingleNodeJobRunner worker loop started")
        while not self._stop_event.is_set():
            job = self.job_queue.get_next_job()
            if job is None:
                time.sleep(self.poll_interval)
                continue
            start_time = time.monotonic()
            extra = {
                "job_id": job.job_id,
                "run_mode": getattr(job, "run_mode", None),
                "prompt_pack_id": getattr(job, "prompt_pack_id", None),
                "subsystem": "queue_runner",
            }
            log_with_ctx(
                logger,
                logging.INFO,
                "QUEUE_JOB_START | Starting execution via runner",
                ctx=LogContext(job_id=job.job_id, subsystem="queue_runner"),
                extra_fields=extra,
            )
            log_with_ctx(
                logger,
                logging.INFO,
                "Dequeued job for execution",
                ctx=LogContext(job_id=job.job_id, subsystem="queue_runner"),
                extra_fields={
                    "run_mode": getattr(job, "run_mode", None),
                    "prompt_pack_id": getattr(job, "prompt_pack_id", None),
                },
            )
            self.job_queue.mark_running(job.job_id)
            self._notify(job, JobStatus.RUNNING)
            self._current_job = job
            self._cancel_current.clear()
            try:
                if self._cancel_current.is_set():
                    self.job_queue.mark_cancelled(job.job_id)
                    self._notify(job, JobStatus.CANCELLED)
                    continue
                if self.run_callable:
                    job_log = job.to_log_dict() if hasattr(job, "to_log_dict") else {"job_id": job.job_id}
                    log_with_ctx(
                        logger,
                        logging.INFO,
                        "QUEUE_JOB_PIPELINE_CALL | Invoking pipeline for job",
                        ctx=LogContext(job_id=job.job_id, subsystem="queue_runner"),
                        extra_fields=job_log,
                    )
                    logger.debug("Running job via run_callable", extra={"job_id": job.job_id})
                    result = self.run_callable(job)
                else:
                    result = None
                canonical_result = normalize_run_result(result, default_run_id=job.job_id)
                duration_ms = int((time.monotonic() - start_time) * 1000)
                metadata = canonical_result.get("metadata") or {}
                metadata["duration_ms"] = duration_ms
                canonical_result["metadata"] = metadata
                error_message = canonical_result.get("error")
                success = canonical_result.get("success")
                if success is None:
                    success = error_message is None
                if success is False and error_message is None:
                    success = True
                if success:
                    self.job_queue.mark_completed(job.job_id, result=canonical_result)
                    status_value = "completed"
                    notify_status = JobStatus.COMPLETED
                else:
                    error_msg = error_message or "Job failed without error message"
                    self.job_queue.mark_failed(job.job_id, error_message=error_msg, result=canonical_result)
                    status_value = "failed"
                    notify_status = JobStatus.FAILED
                log_with_ctx(
                    logger,
                    logging.INFO,
                    "QUEUE_JOB_PIPELINE_RETURN | Pipeline finished",
                    ctx=LogContext(job_id=job.job_id, subsystem="queue_runner"),
                    extra_fields={"job_id": job.job_id, "status": status_value},
                )
                log_with_ctx(
                    logger,
                    logging.INFO,
                    "QUEUE_JOB_DONE | Job execution completed",
                    ctx=LogContext(job_id=job.job_id, subsystem="queue_runner"),
                    extra_fields={**extra, "duration_ms": duration_ms, "status": status_value},
                )
                elapsed_s = duration_ms / 1000
                if elapsed_s > QUEUE_JOB_SOFT_TIMEOUT_SECONDS:
                    logger.warning(
                        "QUEUE_JOB_WARNING | Job appears to be running for a long time",
                        extra={**extra, "elapsed_s": elapsed_s},
                    )
                self._notify(job, notify_status)
            except Exception as exc:  # noqa: BLE001
                duration_ms = int((time.monotonic() - start_time) * 1000)
                log_with_ctx(
                    logger,
                    logging.ERROR,
                    "QUEUE_JOB_ERROR | Unhandled exception during job execution",
                    ctx=LogContext(job_id=job.job_id, subsystem="queue_runner"),
                    extra_fields={
                        **extra,
                        "duration_ms": duration_ms,
                        "error": str(exc),
                    },
                )
                logger.exception(
                    "QUEUE_JOB_ERROR | Unhandled exception while executing job",
                    extra={"job_id": job.job_id},
                )
                logger.debug("Queue runner exception", exc_info=exc)
                _ensure_job_envelope(job, exc)
                self.job_queue.mark_failed(job.job_id, error_message=str(exc))
                self._notify(job, JobStatus.FAILED)
            finally:
                self._current_job = None
        return

    def run_once(self, job: Job) -> dict | None:
        """Synchronously execute a single job (used by Run Now)."""
        # PR-CORE1-D21B: Activity after dequeue
        if self._on_activity:
            self._on_activity()
        if job is None:
            return None
        self.job_queue.mark_running(job.job_id)
        self._notify(job, JobStatus.RUNNING)
        self._current_job = job
        self._cancel_current.clear()
        try:
            # PR-CORE1-D21B: Activity before running job
            if self._on_activity:
                self._on_activity()
            if self.run_callable:
                logger.debug("Running job via run_once", extra={"job_id": job.job_id})
                result = self.run_callable(job)
            else:
                result = None
            canonical_result = normalize_run_result(result, default_run_id=job.job_id)
            error_message = canonical_result.get("error")
            success = canonical_result.get("success")
            if success is None:
                success = error_message is None
            if success is False and error_message is None:
                success = True
            if success:
                self.job_queue.mark_completed(job.job_id, result=canonical_result)
                notify_status = JobStatus.COMPLETED
            else:
                error_msg = error_message or "Job failed without error message"
                self.job_queue.mark_failed(job.job_id, error_message=error_msg, result=canonical_result)
                notify_status = JobStatus.FAILED
            log_with_ctx(
                logger,
                logging.INFO,
                "Job completed via run_once",
                ctx=LogContext(job_id=job.job_id, subsystem="queue_runner"),
                extra_fields={"status": notify_status.value},
            )
            # PR-CORE1-D21B: Activity after running job
            if self._on_activity:
                self._on_activity()
            self._notify(job, notify_status)
            return canonical_result
        except Exception as exc:  # noqa: BLE001
            # PR-CORE1-D21B: Activity on exception
            if self._on_activity:
                self._on_activity()
            logger.error("Job %s failed with error: %s", job.job_id, exc, exc_info=True)
            _ensure_job_envelope(job, exc)
            self.job_queue.mark_failed(job.job_id, error_message=str(exc))
            self._notify(job, JobStatus.FAILED)
            raise
        finally:
            self._current_job = None

    def _notify(self, job: Job, status: JobStatus) -> None:
        if self._on_status_change:
            try:
                self._on_status_change(job, status)
            except Exception:
                pass

    def cancel_current(self) -> None:
        self._cancel_current.set()

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    @property
    def current_job_id(self) -> str | None:
        job = self._current_job
        return job.job_id if job else None
