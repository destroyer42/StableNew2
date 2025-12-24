# Subsystem: Queue
# Role: Executes queued jobs on a single node in FIFO/priority order.

"""Single-node job runner that executes jobs from an in-memory queue."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from src.api.webui_process_manager import get_global_webui_process_manager
from src.pipeline.pipeline_runner import normalize_run_result
from src.queue.job_model import Job, JobStatus, RetryAttempt
from src.queue.job_queue import JobQueue
from src.utils import LogContext, log_with_ctx
from src.utils.error_envelope_v2 import get_attached_envelope, wrap_exception

logger = logging.getLogger(__name__)
QUEUE_JOB_SOFT_TIMEOUT_SECONDS = 600  # seconds
# Cooldown between reprocess jobs to let WebUI stabilize and free VRAM
REPROCESS_JOB_COOLDOWN_SECONDS = 2.0


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


_MAX_WEBUI_CRASH_RETRIES = 1
_QUEUE_JOB_WEBUI_CRASH_SUSPECTED = "QUEUE_JOB_WEBUI_CRASH_SUSPECTED"
_QUEUE_JOB_WEBUI_RETRY_EXHAUSTED = "QUEUE_JOB_WEBUI_RETRY_EXHAUSTED"
_CRASH_ELIGIBLE_STAGES = {"txt2img", "img2img", "upscale", "adetailer"}
_CRASH_MESSAGE_KEYWORDS = ("connection refused", "actively refused", "webui unavailable")
# Timeout keywords indicate slow processing, NOT a crash - don't restart WebUI for these
_TIMEOUT_KEYWORDS = ("read timed out", "readtimeout", "timeout", "timed out")


def _select_request_summary_stage(summary: dict[str, Any] | None) -> str | None:
    if not summary:
        return None
    stage = summary.get("stage")
    if stage:
        return str(stage)
    endpoint = summary.get("endpoint")
    if endpoint and "/txt2img" in endpoint:
        return "txt2img"
    if endpoint and "/img2img" in endpoint:
        return "img2img"
    if endpoint and "/upscale" in endpoint:
        return "upscale"
    return None


def _get_diagnostics_context(exc: Exception) -> dict[str, Any] | None:
    envelope = get_attached_envelope(exc)
    if envelope and envelope.context:
        diagnostics = envelope.context.get("diagnostics")
        if isinstance(diagnostics, dict):
            return diagnostics
    diagnostics = getattr(exc, "diagnostics_context", None)
    if isinstance(diagnostics, dict):
        return diagnostics
    return None


def _is_webui_crash_exception(exc: Exception) -> tuple[bool, str | None]:
    diag = _get_diagnostics_context(exc)
    if not diag:
        return False, None
    summary = diag.get("request_summary") or {}
    status = summary.get("status")
    method = (summary.get("method") or "").upper()
    attempt_stage = _select_request_summary_stage(summary)
    stage_name = attempt_stage or (getattr(exc, "stage", None) or summary.get("stage"))
    
    # Check if this is a timeout error - timeouts are slow processing, NOT crashes
    # Don't restart WebUI just because a generation took too long
    error_message_lower = str(diag.get("error_message") or exc).lower()
    exc_message_lower = str(exc).lower()
    if any(kw in error_message_lower or kw in exc_message_lower for kw in _TIMEOUT_KEYWORDS):
        logger.info(
            "Timeout detected but NOT treating as crash (slow processing, not WebUI failure): %s",
            str(exc)[:200],
        )
        return False, stage_name
    
    try:
        status_code = int(status)
    except (TypeError, ValueError):
        status_code = None
    if (
        status_code == 500
        and method == "POST"
        and stage_name
        and stage_name.lower() in _CRASH_ELIGIBLE_STAGES
    ):
        return True, stage_name
    if diag.get("webui_unavailable"):
        if any(keyword in error_message_lower for keyword in _CRASH_MESSAGE_KEYWORDS):
            return True, stage_name
    message = str(exc).lower()
    if "webui unavailable" in message:
        return True, stage_name
    return False, stage_name


def _record_retry_attempt(
    job: Job, *, stage: str | None, attempt_index: int, reason: str, max_attempts: int
) -> None:
    job.execution_metadata.retry_attempts.append(
        RetryAttempt(
            stage=stage or "pipeline",
            attempt_index=attempt_index,
            max_attempts=max_attempts,
            reason=reason,
        )
    )


def _restart_webui_process(job_id: str) -> bool:
    manager = get_global_webui_process_manager()
    if manager is None:
        logger.debug("No WebUI process manager available for restart", extra={"job_id": job_id})
        return False
    try:
        return manager.restart_webui()
    except Exception as exc:  # pragma: no cover - best effort
        log_with_ctx(
            logger,
            logging.ERROR,
            "Failed to restart WebUI process",
            ctx=LogContext(job_id=job_id, subsystem="queue_runner"),
            extra_fields={"error": str(exc)},
        )
        return False


def _log_retry_exhausted(job: Job, stage: str | None, reason: str) -> None:
    log_with_ctx(
        logger,
        logging.ERROR,
        f"{_QUEUE_JOB_WEBUI_RETRY_EXHAUSTED} | WebUI crash retry exhausted",
        ctx=LogContext(job_id=job.job_id, subsystem="queue_runner"),
        extra_fields={"stage": stage, "reason": reason},
    )


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
        self._worker: threading.Thread | None = None
        self._on_status_change = on_status_change
        self._current_job: Job | None = None
        self._cancel_current = threading.Event()
        # PR-CORE1-D21B: Activity callback
        self._on_activity = on_activity

    def _run_with_webui_retry(self, job: Job) -> dict | None:
        if self.run_callable is None:
            return None
        max_attempts = _MAX_WEBUI_CRASH_RETRIES + 1
        attempt = 1
        while attempt <= max_attempts:
            try:
                return self.run_callable(job)
            except Exception as exc:  # noqa: BLE001
                crash_eligible, stage = _is_webui_crash_exception(exc)
                if not crash_eligible:
                    raise
                if attempt >= max_attempts:
                    _log_retry_exhausted(job, stage, _QUEUE_JOB_WEBUI_CRASH_SUSPECTED)
                    raise
                next_attempt = attempt + 1
                _record_retry_attempt(
                    job,
                    stage=stage,
                    attempt_index=next_attempt,
                    reason=_QUEUE_JOB_WEBUI_CRASH_SUSPECTED,
                    max_attempts=max_attempts,
                )
                log_with_ctx(
                    logger,
                    logging.WARNING,
                    f"{_QUEUE_JOB_WEBUI_CRASH_SUSPECTED} | Suspected WebUI crash, restarting",
                    ctx=LogContext(job_id=job.job_id, subsystem="queue_runner"),
                    extra_fields={
                        "stage": stage,
                        "attempt": next_attempt,
                        "max_attempts": max_attempts,
                    },
                )
                restarted = _restart_webui_process(job.job_id)
                if not restarted:
                    log_with_ctx(
                        logger,
                        logging.ERROR,
                        "WebUI restart failed during retry",
                        ctx=LogContext(job_id=job.job_id, subsystem="queue_runner"),
                        extra_fields={"stage": stage, "attempt": next_attempt},
                    )
                attempt += 1
        return None

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
                    job_log = (
                        job.to_log_dict() if hasattr(job, "to_log_dict") else {"job_id": job.job_id}
                    )
                    log_with_ctx(
                        logger,
                        logging.INFO,
                        "QUEUE_JOB_PIPELINE_CALL | Invoking pipeline for job",
                        ctx=LogContext(job_id=job.job_id, subsystem="queue_runner"),
                        extra_fields=job_log,
                    )
                    logger.debug("Running job via run_callable", extra={"job_id": job.job_id})
                    result = self._run_with_webui_retry(job)
                else:
                    result = None
                canonical_result = normalize_run_result(result, default_run_id=job.job_id)
                logger.info(f"🔍 DEBUG: canonical_result success={canonical_result.get('success')}, error={canonical_result.get('error')}")
                duration_ms = int((time.monotonic() - start_time) * 1000)
                metadata = canonical_result.get("metadata") or {}
                metadata["duration_ms"] = duration_ms
                canonical_result["metadata"] = metadata
                error_message = canonical_result.get("error")
                success = canonical_result.get("success")
                logger.info(f"🔍 DEBUG: Before fallback logic - success={success}, error_message={error_message}")
                if success is None:
                    success = error_message is None
                if success is False and error_message is None:
                    success = True
                logger.info(f"🔍 DEBUG: After fallback logic - success={success}")
                if success:
                    self.job_queue.mark_completed(job.job_id, result=canonical_result)
                    status_value = "completed"
                    notify_status = JobStatus.COMPLETED
                else:
                    error_msg = error_message or "Job failed without error message"
                    self.job_queue.mark_failed(
                        job.job_id, error_message=error_msg, result=canonical_result
                    )
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
                # Apply cooldown for reprocess jobs to let WebUI stabilize
                job_source = getattr(job, "source", None) or ""
                if job_source == "reprocess_panel":
                    logger.debug(
                        "Applying %.1fs cooldown after reprocess job %s",
                        REPROCESS_JOB_COOLDOWN_SECONDS,
                        job.job_id,
                    )
                    time.sleep(REPROCESS_JOB_COOLDOWN_SECONDS)
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
                result = self._run_with_webui_retry(job)
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
                self.job_queue.mark_failed(
                    job.job_id, error_message=error_msg, result=canonical_result
                )
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
