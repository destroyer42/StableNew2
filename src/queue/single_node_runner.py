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

from src.api.webui_failure_evidence import FailureAssessment
from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.pipeline_runner import normalize_run_result
from src.queue.dispatch_evidence import NEVER_INVOKED, NO_EVIDENCE, assess_dispatch
from src.queue.job_model import Job, JobStatus, StageCheckpoint
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


def _extract_stage_checkpoints(canonical_result: dict[str, Any]) -> list[StageCheckpoint]:
    stage_events = canonical_result.get("stage_events") or []
    variants = canonical_result.get("variants") or []
    output_paths: list[str] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        path = variant.get("path") or variant.get("output_path")
        if path:
            output_paths.append(str(path))
    exit_stages: list[str] = []
    for event in stage_events:
        if not isinstance(event, dict):
            continue
        if str(event.get("phase") or event.get("event") or "").lower() != "exit":
            continue
        stage_name = str(event.get("stage") or "").strip()
        if stage_name and stage_name not in exit_stages:
            exit_stages.append(stage_name)
    checkpoints: list[StageCheckpoint] = []
    for index, stage_name in enumerate(exit_stages):
        checkpoints.append(
            StageCheckpoint(
                stage_name=stage_name,
                output_paths=list(output_paths) if index == len(exit_stages) - 1 else [],
                metadata={"source": "canonical_result", "event": "exit"},
            )
        )
    if not checkpoints and output_paths:
        checkpoints.append(
            StageCheckpoint(
                stage_name="final_output",
                output_paths=list(output_paths),
                metadata={"source": "canonical_result", "event": "final_output"},
            )
        )
    return checkpoints


def _merge_stage_checkpoints(
    existing: list[StageCheckpoint], incoming: list[StageCheckpoint]
) -> list[StageCheckpoint]:
    if not existing:
        return list(incoming)
    merged: list[StageCheckpoint] = list(existing)
    by_stage = {checkpoint.stage_name: index for index, checkpoint in enumerate(merged)}
    for checkpoint in incoming:
        index = by_stage.get(checkpoint.stage_name)
        if index is None:
            merged.append(checkpoint)
            by_stage[checkpoint.stage_name] = len(merged) - 1
            continue
        current = merged[index]
        if checkpoint.output_paths and not current.output_paths:
            merged[index] = checkpoint
    return merged


#: Longest an idle worker waits before re-checking on its own (queue changes wake it immediately).
IDLE_HEARTBEAT_SECONDS = 1.0


class _WakingEvent(threading.Event):
    """A stop flag whose ``set`` also wakes the (event-driven) idle wait, so a stop never waits out the heartbeat."""

    def __init__(self, on_set: Callable[[], None]) -> None:
        super().__init__()
        self._on_set = on_set

    def set(self) -> None:
        super().set()
        try:
            self._on_set()
        except Exception:  # noqa: BLE001 - waking is best-effort; the flag is already set
            logger.debug("Could not wake the idle queue wait", exc_info=True)


class SingleNodeJobRunner:
    """Background worker that executes jobs from a JobQueue."""

    def __init__(
        self,
        job_queue: JobQueue,
        run_callable: Callable[[Job], dict] | None,
        poll_interval: float = 0.1,
        on_status_change: Callable[[Job, JobStatus], None] | None = None,
        on_activity=None,
        is_paused: Callable[[], bool] | None = None,
        continuous_dispatch_allowed: Callable[[], bool] | None = None,
        outage_observer: Any | None = None,
        held_poll_interval: float = 1.0,
        gpu_loss_observer: Any | None = None,
    ) -> None:
        self.job_queue = job_queue
        self.run_callable = run_callable
        self.poll_interval = poll_interval
        self._stop_event = _WakingEvent(self._wake_queue)
        self._worker: threading.Thread | None = None
        # Every worker thread this runner has launched and not yet seen exit. ``_worker`` is only the latest;
        # a worker that decided to retire can still be unwinding when its replacement starts, and the repository
        # may be closed only once *none* of them is alive (PR-RUNTIME-SHUTDOWN-140).
        self._workers: list[threading.Thread] = []
        self._shutting_down = False
        self._on_status_change = on_status_change
        self._current_job: Job | None = None
        self._cancel_current = threading.Event()
        self._current_cancel_token: CancelToken | None = None
        self._cancel_return_to_queue = False
        # The job the run callable was last invoked for: the worker's own proof of whether a stop request found
        # the job before or after anything could have been dispatched.
        self._invoked_job_id: str | None = None
        # PR-CORE1-D21B: Activity callback
        self._on_activity = on_activity
        # BUGFIX: Pause state callback
        self._is_paused = is_paused
        self._continuous_dispatch_allowed = continuous_dispatch_allowed or (lambda: True)
        # PR-QUEUE-WEBUI-171: typed outage assessment/recovery (duck-typed; see WebUIOutageCoordinator). The
        # runner never replays a job: a failed job is published once, or restored to QUEUED on positive
        # evidence that nothing was dispatched.
        self._outage_observer = outage_observer
        # PR-QUEUE-GPU-180: confirmed GPU device loss applies the queue's dispatch quarantine before the next claim.
        self._gpu_loss_observer = gpu_loss_observer
        self._held_poll_interval = max(0.01, float(held_poll_interval))
        # Worker lifecycle handoff state. All transitions happen under
        # ``_lifecycle_lock`` so a thread's decision to retire and a concurrent
        # request for continuous dispatch can never miss each other.
        self._lifecycle_lock = threading.RLock()
        self._worker_mode: str | None = None  # "once" | "continuous"
        self._worker_retiring = False
        self._continue_after_once = False

    def set_continuous_dispatch_allowed(self, callback: Callable[[], bool]) -> None:
        """Set the service-owned policy checked before each continuous claim."""
        self._continuous_dispatch_allowed = callback

    def set_outage_observer(self, observer: Any | None) -> None:
        """Bind the service-owned WebUI outage coordinator (assessment + bounded owned recovery)."""
        self._outage_observer = observer

    def set_gpu_loss_observer(self, observer: Any | None) -> None:
        """Bind the service-owned GPU device-loss coordinator (assessment + queue quarantine)."""
        self._gpu_loss_observer = observer

    def _observe_gpu_loss(
        self, job: Job, *, result: dict | None = None, exc: BaseException | None = None
    ) -> None:
        observer = self._gpu_loss_observer
        if observer is None:
            return
        try:
            observer.assess_failure(job, result=result, exc=exc)
        except Exception:  # noqa: BLE001 - containment must never break the worker
            logger.exception("GPU device-loss assessment failed; the job result is published unchanged")

    def _observe_failure(
        self, job: Job, *, result: dict | None = None, exc: BaseException | None = None
    ) -> Any | None:
        # Device loss first: it must be in force before any other assessment or recovery can act, and before the
        # worker's next claim.
        self._observe_gpu_loss(job, result=result, exc=exc)
        observer = self._outage_observer
        if observer is None:
            return None
        try:
            return observer.assess(job, result=result, exc=exc)
        except Exception:  # noqa: BLE001 - containment must never break the worker
            logger.exception("WebUI outage assessment failed; the job result is published unchanged")
            return None

    def _after_failure(self, decision: Any | None) -> None:
        observer = self._outage_observer
        if observer is None or decision is None or not getattr(decision, "outage_confirmed", False):
            return
        try:
            observer.recover(decision)
        except Exception:  # noqa: BLE001
            logger.exception("WebUI outage recovery failed")

    def _restore_if_undispatched(self, job: Job, decision: Any | None) -> bool:
        """Restore a job to QUEUED only on positive evidence that nothing was dispatched."""
        if decision is None or not getattr(decision, "requeue", False):
            return False
        if job.execution_metadata.stage_checkpoints:
            return False
        assessment = getattr(decision, "assessment", None)
        if assessment is None:
            return False
        restored = self.job_queue.return_undispatched_to_queue(
            job.job_id, reason="webui_outage", assessment=assessment
        )
        if restored is None:
            return False
        self._notify(restored, JobStatus.QUEUED)
        return True

    def _maybe_release_hold(self, *, force: bool = False) -> None:
        observer = self._outage_observer
        if observer is None:
            return
        try:
            observer.maybe_release(force=force)
        except Exception:  # noqa: BLE001
            logger.debug("WebUI hold release check failed", exc_info=True)

    def _idle_wait(self) -> None:
        """Wait for work; when only held work remains (WebUI hold or GPU quarantine), wait longer (no hot spin)."""
        try:
            gpu_quarantined = getattr(self.job_queue, "is_gpu_quarantined", None)
            held_only = False
            # The full summary is O(queue): only build it while a hold or quarantine can be the reason for idling.
            if self.job_queue.is_webui_held() or (callable(gpu_quarantined) and gpu_quarantined()):
                summary = self.job_queue.dispatch_summary()
                held_only = summary["held"] > 0 and summary["eligible"] == 0
        except Exception:  # noqa: BLE001
            held_only = False
        if held_only:
            self._stop_event.wait(self._held_poll_interval)
            return
        wait_for_change = getattr(self.job_queue, "wait_for_change", None)
        if callable(wait_for_change):
            # Event-driven: the queue wakes us when work is admitted or state changes; the heartbeat only covers
            # conditions that change without a queue event.  A stop request wakes the queue (see ``_wake_queue``).
            wait_for_change(IDLE_HEARTBEAT_SECONDS)
        else:
            time.sleep(self.poll_interval)

    def _wake_queue(self) -> None:
        wake = getattr(self.job_queue, "wake_worker", None)
        if callable(wake):
            wake()

    def set_activity_callback(self, callback) -> None:
        """Bind the existing runner activity signal to an external observer."""
        self._on_activity = callback

    def _can_continue_dispatching(self) -> bool:
        try:
            return bool(self._continuous_dispatch_allowed())
        except Exception:
            logger.exception("Continuous queue dispatch policy failed closed")
            return False

    def _run_job_callable(self, job: Job) -> dict | None:
        """Invoke the job's callable exactly once: a failure is assessed, never replayed."""
        if self.run_callable is None:
            return None
        self._invoked_job_id = job.job_id
        return self.run_callable(job)

    def _return_evidence(
        self, job: Job, *, result: dict[str, Any] | None, exc: BaseException | None
    ) -> FailureAssessment:
        """Dispatch evidence for a stop request that asked to return the job (never guessed; unknown stays unknown)."""
        if self._invoked_job_id != job.job_id:
            return NEVER_INVOKED  # the callable was never called: no stage, no backend request can have started
        try:
            return assess_dispatch(job, result=result, exc=exc)[0]
        except Exception:  # noqa: BLE001 - fail closed: an unassessable attempt is never requeued
            logger.exception("Dispatch assessment failed for job %s; it will not be returned to the queue", job.job_id)
            return NO_EVIDENCE

    def _settle_cancel(
        self, job: Job, *, result: dict[str, Any] | None = None, exc: BaseException | None = None
    ) -> Job:
        """Carry out the pending Cancel (and Return) of ``job`` and announce the status it actually reached.

        A return happens only on positive evidence that nothing was dispatched; otherwise the queue cancels the job
        and records the operator-action-required envelope (see ``JobQueue.cancel_running_job``).
        """
        evidence = (
            self._return_evidence(job, result=result, exc=exc) if self._cancel_return_to_queue else None
        )
        settled = self.job_queue.cancel_running_job(
            return_to_queue=self._cancel_return_to_queue, job_id=job.job_id, assessment=evidence
        )
        if settled is None:  # the job moved on first: report what is durable
            settled = self.job_queue.get_job(job.job_id) or job
        self._notify(settled, settled.status)
        return settled

    def _launch_worker(self, mode: str, job: Job | None = None) -> None:
        """Start a worker thread of ``mode``; the caller holds ``_lifecycle_lock``."""
        if not self._shutting_down:
            self._stop_event.clear()
        self._worker_mode = mode
        self._worker_retiring = False
        self._continue_after_once = False
        # PR-THREAD-001: non-daemon thread with proper tracking
        self._worker = threading.Thread(
            target=self._worker_main,
            args=(mode, job),
            daemon=False,
            name="QueueWorker" if mode == "continuous" else "QueueWorkerOnce",
        )
        self._workers = [worker for worker in self._workers if worker.is_alive()]
        self._workers.append(self._worker)
        self._worker.start()

    def start(self) -> None:
        """Ensure continuous dispatch is running.

        A live continuous worker is left alone. A live one-shot worker is asked to
        hand off to continuous draining when its job retires (same thread, no gap),
        and a worker that has already decided to retire is replaced.

        PR-THREAD-001: Changed to non-daemon thread for clean shutdown.
        """
        with self._lifecycle_lock:
            if self._shutting_down:
                return
            worker = self._worker
            if worker and worker.is_alive() and not self._worker_retiring:
                if self._worker_mode == "once":
                    self._continue_after_once = True
                return
            self._launch_worker("continuous")

    def request_continuous_dispatch(self) -> None:
        """Idempotent request used by JobService when auto-run is enabled."""
        self.start()

    def run_next_once(self) -> bool:
        """Dispatch exactly the next queued job on a worker thread."""
        with self._lifecycle_lock:
            if self._shutting_down or self.is_running() or self.job_queue.is_paused():
                return False
            # Operator intent: with auto-run off no worker loop is checking, so ask for a fresh readiness proof.
            self._maybe_release_hold(force=True)
            # One atomic claim: eligibility (WebUI hold) and QUEUED -> RUNNING cannot be separated by a hold change.
            job = self.job_queue.claim_next_job()
            if job is None:
                return False
            self._launch_worker("once", job)
            return True

    def _worker_main(self, mode: str, job: Job | None) -> None:
        if mode == "once" and job is not None:
            failure: Exception | None = None
            try:
                self.run_once(job)
            except Exception as exc:  # noqa: BLE001 - run_once already recorded the failure
                failure = exc
            with self._lifecycle_lock:
                handoff = (
                    self._continue_after_once
                    and not self._shutting_down
                    and not self._stop_event.is_set()
                    and self._can_continue_dispatching()
                )
                if handoff:
                    self._worker_mode = "continuous"
                    threading.current_thread().name = "QueueWorker"
                else:
                    self._worker_retiring = True
                self._continue_after_once = False
            if not handoff:
                if failure is not None:
                    raise failure
                return
            # A failed one-shot job must not strand the remaining queue: it is already
            # persisted FAILED, so keep draining and let the loop own later failures.
        self._worker_loop()

    def begin_shutdown(self) -> None:
        """Terminal admission fence for application shutdown (idempotent, cannot be undone).

        Fences the queue first (the atomic claim boundary), then retires dispatch: no new worker starts, a
        one-shot worker does not hand off to continuous draining, and a running worker leaves its loop after the
        job it already owns. That job is untouched here (cancellation stays with ``cancel_current``). QUEUED jobs
        stay durably QUEUED and the user's auto-run preference is not read or changed.
        """
        # Deliberately lock-free: the safety property is the queue's atomic fence, and a worker holds
        # ``_lifecycle_lock`` while it evaluates the dispatch policy, which must never be able to delay shutdown.
        self.job_queue.fence_dispatch()
        self._shutting_down = True
        self._stop_event.set()

    def is_quiescent(self) -> bool:
        """True only when no worker thread this runner launched is alive (so none can touch the repository)."""
        return not any(worker.is_alive() for worker in list(self._workers))

    def stop(self, timeout: float = 10.0) -> bool:
        """Ask the worker to stop and wait at most ``timeout`` seconds in total.

        Returns whether every worker has definitively quiesced: ``True`` only when no worker thread is alive. A
        join that merely returned at the timeout is not quiescence, so callers must use this result (or
        ``is_quiescent()``) before closing anything the worker may still use.

        PR-THREAD-001: the default stays 10s for clean shutdown.
        """
        self._stop_event.set()
        deadline = time.monotonic() + max(0.0, float(timeout))
        for worker in list(self._workers):
            if worker is threading.current_thread():
                continue
            worker.join(timeout=max(0.0, deadline - time.monotonic()))
        return self.is_quiescent()

    def _worker_loop(self) -> None:
        logger.debug("SingleNodeJobRunner worker loop started")
        while not self._stop_event.is_set():
            # Check if queue is paused before dequeuing
            if self._is_paused and self._is_paused():
                self._stop_event.wait(self.poll_interval)
                continue
            with self._lifecycle_lock:
                if self._shutting_down or not self._can_continue_dispatching():
                    self._worker_retiring = True
                    logger.debug("SingleNodeJobRunner retiring (auto-run disabled or shutting down)")
                    break
            self._cancel_current.clear()
            self._cancel_return_to_queue = False
            self._maybe_release_hold()
            # Clear before claiming: a change that lands between the claim and the wait leaves the event set.
            clear_wake = getattr(self.job_queue, "clear_wake", None)
            if callable(clear_wake):
                clear_wake()
            job = self.job_queue.claim_next_job()
            if job is None:
                self._idle_wait()
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
            self._notify(job, JobStatus.RUNNING)
            self._invoked_job_id = None
            self._current_job = job
            self._current_cancel_token = CancelToken()
            job._cancel_token = self._current_cancel_token
            try:
                if self._cancel_current.is_set():
                    self._settle_cancel(job)
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
                    result = self._run_job_callable(job)
                else:
                    result = None
                canonical_result = normalize_run_result(result, default_run_id=job.job_id)
                logger.debug(
                    "[queue/result] canonical result success=%s error=%s",
                    canonical_result.get("success"),
                    canonical_result.get("error"),
                )
                duration_ms = int((time.monotonic() - start_time) * 1000)
                metadata = canonical_result.get("metadata") or {}
                metadata["duration_ms"] = duration_ms
                canonical_result["metadata"] = metadata
                if self._cancel_current.is_set():
                    self._settle_cancel(job, result=canonical_result)
                    continue
                error_message = canonical_result.get("error")
                success = canonical_result.get("success")
                logger.debug(
                    "[queue/result] before fallback success=%s error=%s",
                    success,
                    error_message,
                )
                if success is None:
                    success = error_message is None
                logger.debug("[queue/result] after fallback success=%s", success)
                checkpoints = _merge_stage_checkpoints(
                    job.execution_metadata.stage_checkpoints,
                    _extract_stage_checkpoints(canonical_result),
                )
                elapsed_s = duration_ms / 1000
                if elapsed_s > QUEUE_JOB_SOFT_TIMEOUT_SECONDS:
                    # This message is only truthful while this worker still owns
                    # the RUNNING job; terminal state is written immediately below.
                    logger.warning(
                        "QUEUE_JOB_WARNING | Job appears to be running for a long time",
                        extra={**extra, "elapsed_s": elapsed_s},
                    )
                notify_status = JobStatus.COMPLETED if success else JobStatus.FAILED
                error_msg = (
                    None if success else (error_message or "Job failed without error message")
                )
                decision = None if success else self._observe_failure(job, result=canonical_result)
                if self._restore_if_undispatched(job, decision):
                    self._after_failure(decision)
                    continue
                published_job = self.job_queue.publish_result(
                    job.job_id,
                    status=notify_status,
                    result=canonical_result,
                    stage_checkpoints=checkpoints,
                    error_message=error_msg,
                )
                if published_job is None:
                    durable_job = self.job_queue.get_job(job.job_id)
                    durable_status = durable_job.status if durable_job is not None else job.status
                    if durable_status in {JobStatus.CANCELLED, JobStatus.QUEUED}:
                        self._notify(durable_job or job, durable_status)
                        continue
                    raise RuntimeError(
                        f"Job {job.job_id} lost RUNNING ownership before result publication"
                    )
                status_value = notify_status.value
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
                self._notify(job, notify_status)
                self._after_failure(decision)
            except Exception as exc:  # noqa: BLE001
                if self._cancel_current.is_set() or isinstance(exc, CancellationError):
                    self._settle_cancel(job, exc=exc)
                    continue
                decision = self._observe_failure(job, exc=exc)
                if self._restore_if_undispatched(job, decision):
                    self._after_failure(decision)
                    continue
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
                self._after_failure(decision)
            finally:
                job._cancel_token = None
                self._current_cancel_token = None
                self._current_job = None
                self._cancel_return_to_queue = False
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
        self._cancel_current.clear()
        self._cancel_return_to_queue = False
        self._invoked_job_id = None
        self._current_cancel_token = CancelToken()
        job._cancel_token = self._current_cancel_token
        self._current_job = job
        already_claimed = job.status is JobStatus.RUNNING  # claimed atomically by run_next_once
        if (
            not already_claimed
            and self.job_queue.mark_running(job.job_id) is None
            and (self._queue_dispatch_fenced() or self._queue_holds(job.job_id))
        ):
            # Shutdown fenced admission, or the WebUI hold applies, between the decision and its RUNNING
            # transition: the job stays durably QUEUED.
            job._cancel_token = None
            self._current_cancel_token = None
            self._current_job = None
            return None
        self._notify(job, JobStatus.RUNNING)
        try:
            if self._cancel_current.is_set():
                self._settle_cancel(job)
                return None
            # PR-CORE1-D21B: Activity before running job
            if self._on_activity:
                self._on_activity()
            if self.run_callable:
                logger.debug("Running job via run_once", extra={"job_id": job.job_id})
                result = self._run_job_callable(job)
            else:
                result = None
            canonical_result = normalize_run_result(result, default_run_id=job.job_id)
            if self._cancel_current.is_set():
                self._settle_cancel(job, result=canonical_result)
                return canonical_result
            error_message = canonical_result.get("error")
            success = canonical_result.get("success")
            if success is None:
                success = error_message is None
            checkpoints = _merge_stage_checkpoints(
                job.execution_metadata.stage_checkpoints,
                _extract_stage_checkpoints(canonical_result),
            )
            notify_status = JobStatus.COMPLETED if success else JobStatus.FAILED
            error_msg = None if success else error_message or "Job failed without error message"
            decision = None if success else self._observe_failure(job, result=canonical_result)
            if self._restore_if_undispatched(job, decision):
                self._after_failure(decision)
                return None
            published_job = self.job_queue.publish_result(
                job.job_id,
                status=notify_status,
                result=canonical_result,
                stage_checkpoints=checkpoints,
                error_message=error_msg,
            )
            if published_job is None:
                durable_job = self.job_queue.get_job(job.job_id)
                durable_status = durable_job.status if durable_job is not None else job.status
                if durable_status in {JobStatus.CANCELLED, JobStatus.QUEUED}:
                    self._notify(durable_job or job, durable_status)
                    return None
                raise RuntimeError(
                    f"Job {job.job_id} lost RUNNING ownership before result publication"
                )
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
            self._after_failure(decision)
            return canonical_result
        except Exception as exc:  # noqa: BLE001
            if self._cancel_current.is_set() or isinstance(exc, CancellationError):
                self._settle_cancel(job, exc=exc)
                return None
            # PR-CORE1-D21B: Activity on exception
            if self._on_activity:
                self._on_activity()
            logger.error("Job %s failed with error: %s", job.job_id, exc, exc_info=True)
            decision = self._observe_failure(job, exc=exc)
            if self._restore_if_undispatched(job, decision):
                self._after_failure(decision)
                return None
            _ensure_job_envelope(job, exc)
            self.job_queue.mark_failed(job.job_id, error_message=str(exc))
            self._notify(job, JobStatus.FAILED)
            self._after_failure(decision)
            raise
        finally:
            job._cancel_token = None
            self._current_cancel_token = None
            self._current_job = None
            self._cancel_return_to_queue = False

    def _queue_holds(self, job_id: str) -> bool:
        check = getattr(self.job_queue, "is_job_held", None)
        return callable(check) and check(job_id) is True

    def _queue_dispatch_fenced(self) -> bool:
        check = getattr(self.job_queue, "is_dispatch_fenced", None)
        return callable(check) and check() is True

    def _notify(self, job: Job, status: JobStatus) -> None:
        if self._on_status_change:
            try:
                self._on_status_change(job, status)
            except Exception:
                pass

    @property
    def current_job(self) -> Job | None:
        return self._current_job

    def cancel_current(self, *, return_to_queue: bool = False) -> None:
        self._cancel_return_to_queue = bool(return_to_queue)
        self._cancel_current.set()
        if self._current_cancel_token is not None:
            self._current_cancel_token.cancel()

    def is_running(self) -> bool:
        """True while a worker is alive and has not committed to retiring."""
        worker = self._worker
        return worker is not None and worker.is_alive() and not self._worker_retiring

    @property
    def current_job_id(self) -> str | None:
        job = self._current_job
        return job.job_id if job else None

    def get_current_job(self) -> Job | None:
        """Get the currently executing job, if any."""
        return self._current_job
