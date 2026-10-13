# Subsystem: Queue
# Role: Provides the runnable projection of the durable job repository.

"""Thread-safe runnable projection with priority + FIFO behavior.

PR-CORE1-060: queue runtime is NJR-only for active jobs. Queue items rely on
`_normalized_record`, `config_snapshot`, and `snapshot`, not `pipeline_config`.
"""

from __future__ import annotations

import copy
import heapq
import logging
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from threading import Lock
from typing import Any

from src.queue.backend_dependency import DependencyAssessment, classify_job
from src.queue.job_model import Job, JobStatus, StageCheckpoint
from src.queue.job_repository import JobRepository, JobStatusChanged

logger = logging.getLogger(__name__)

#: Repository setting that persists the GPU device-loss dispatch quarantine (PR-QUEUE-GPU-180).
GPU_QUARANTINE_SETTING = "gpu_dispatch_quarantine"


@dataclass(frozen=True, slots=True)
class QueuedCancelOutcome:
    """What a guarded queued-only cancel actually did to one job."""

    job_id: str
    #: ``cancelled`` (this call performed QUEUED -> CANCELLED), ``skipped`` (not QUEUED at the transition
    #: or unknown to the queue) or ``error`` (the repository refused the write).
    outcome: str
    #: The status the job was observed in when it was skipped.
    observed_status: JobStatus | None = None
    detail: str = ""


class JobQueue:
    """Thread-safe runnable projection of one authoritative repository."""

    _FINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

    def __init__(
        self,
        *,
        repository: JobRepository | None = None,
        history_store: JobRepository | None = None,
    ) -> None:
        if repository is not None and history_store is not None and repository is not history_store:
            raise ValueError("JobQueue accepts exactly one JobRepository authority")
        selected = repository or history_store
        if selected is not None and not isinstance(selected, JobRepository):
            raise TypeError("JSON/JSONL stores cannot be attached to the live queue")
        self._repository = selected or JobRepository()
        self._queue: list[tuple[int, int, str]] = []
        self._jobs: dict[str, Job] = {}
        self._counter = 0
        self._lock = Lock()
        # Serializes durable queue-order writers (admission and complete reorders) with the
        # projection step that follows them.  Lock order: _admission_lock, then _lock.
        self._admission_lock = Lock()
        self._paused = False
        # Process-lifetime dispatch fence (PR-RUNTIME-SHUTDOWN-140). Never persisted: unlike ``_paused`` it
        # must not survive the process, so jobs left QUEUED resume under the normal startup policy.
        self._dispatch_fenced = False
        # Process-lifetime, in-memory WebUI dispatch hold (PR-QUEUE-WEBUI-171). Never persisted and never a
        # lifecycle status: held jobs stay durably QUEUED in their original order, and independent work (native
        # SVD / Comfy video) remains claimable. Distinct from ``_paused`` (the user's whole-queue pause).
        self._webui_hold: dict[str, Any] | None = None
        # GPU device-loss dispatch quarantine (PR-QUEUE-GPU-180). Unlike the WebUI hold it IS persisted through the
        # repository's settings, so a reboot cannot silently authorize execution; it is still not a lifecycle
        # status, not the user's whole-queue pause and not the auto-run preference.
        self._gpu_quarantine: dict[str, Any] | None = None
        self._quarantine_lock = Lock()
        self._dependency_cache: dict[str, DependencyAssessment] = {}
        # Heap counter of a claimed job, so an undispatched return restores its original position.
        self._claimed_counters: dict[str, int] = {}
        self._history_store = self._repository
        # PR-MEMORY-001: Bounded finalized jobs (max 100) using deque for FIFO eviction
        self._finalized_jobs_order: deque[str] = deque(maxlen=100)
        self._finalized_jobs: dict[str, Job] = {}
        self._status_callbacks: list[Callable[[Job, JobStatus], None]] = []
        self._state_listeners: list[Callable[[], None]] = []
        self._state_notifications_suppressed = 0
        self._state_notifications_pending = False
        self._restore_repository_projection()

    @property
    def repository(self) -> JobRepository:
        return self._repository

    def _restore_repository_projection(self) -> None:
        for job in self._repository.load_runnable_jobs(recover_interrupted=True):
            job._persist_runtime_state = lambda current=job: self.persist_runtime_state(current)
            self._counter += 1
            self._jobs[job.job_id] = job
            heapq.heappush(self._queue, (-int(job.priority), self._counter, job.job_id))
        self._paused = bool(self._repository.get_setting("queue_paused", False))
        stored = self._repository.get_setting(GPU_QUARANTINE_SETTING, None)
        if isinstance(stored, dict) and stored.get("incident_id"):
            self._gpu_quarantine = dict(stored)

    def submit(self, job: Job) -> None:
        self.submit_many([job])

    def submit_many(self, jobs: Iterable[Job]) -> None:
        """Admit a batch all-or-none: durable commit first, then ONE projection step.

        The repository commits the whole batch in a single transaction.  If that raises, nothing
        was added to the runnable projection and no state change is announced.  Only after the
        commit are all new jobs made runnable together under the queue lock, so a worker can never
        observe a partially projected batch. Admissions serialize durable commit and projection
        together, preserving repository FIFO order across concurrent callers.
        """

        batch = list(jobs)
        if not batch:
            return
        # Keep the projection lock free for repository observers that read the queue.
        with self._admission_lock:
            self._repository.record_job_submissions(batch)
            for job in batch:
                job._persist_runtime_state = lambda current=job: self.persist_runtime_state(current)
            with self._lock:
                for job in batch:
                    self._counter += 1
                    self._jobs[job.job_id] = job
                    heapq.heappush(self._queue, (-int(job.priority), self._counter, job.job_id))
        self._notify_state_listeners()

    def fence_dispatch(self) -> None:
        """Irreversibly refuse every new QUEUED -> RUNNING transition (application shutdown).

        The flag is read and written under the same lock that makes ``claim_next_job`` and ``mark_running``
        atomic with their durable transition, so a claim either completed before this returns or sees the
        fence: there is no check-then-claim window. Nothing else changes: QUEUED jobs stay durably QUEUED,
        the active job is untouched, and the persisted pause setting is not used.
        """
        with self._lock:
            self._dispatch_fenced = True

    def is_dispatch_fenced(self) -> bool:
        with self._lock:
            return self._dispatch_fenced

    # -- WebUI dispatch hold (PR-QUEUE-WEBUI-171) ---------------------------------------------------------------

    def hold_webui_dispatch(self, *, reason: str, incident_id: str | None = None) -> bool:
        """Stop claiming WebUI-dependent (and unresolved) work; independent video keeps flowing.

        Returns whether the hold was newly applied. The first reason/incident is kept while a hold is active. The hold
        is read and written under the lock that makes eligibility and the QUEUED -> RUNNING transition atomic.
        """

        with self._lock:
            if self._webui_hold is not None:
                return False
            self._webui_hold = {"reason": str(reason or ""), "incident_id": incident_id}
        self._notify_state_listeners()
        return True

    def release_webui_dispatch(self) -> bool:
        """Make held jobs claimable again, in their original priority/FIFO order."""

        with self._lock:
            if self._webui_hold is None:
                return False
            self._webui_hold = None
        self._notify_state_listeners()
        return True

    def webui_hold_info(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._webui_hold) if self._webui_hold is not None else None

    def is_webui_held(self) -> bool:
        with self._lock:
            return self._webui_hold is not None

    # -- GPU device-loss dispatch quarantine (PR-QUEUE-GPU-180) -------------------------------------------------------

    def quarantine_gpu_dispatch(self, incident: Mapping[str, Any]) -> bool:
        """Stop claiming GPU-dependent work after a confirmed device loss; first incident wins.

        The quarantine is effective in memory under the claim lock *before* it is made durable, so there is no
        window in which a claim can slip through while the write is in flight, and a failed write cannot weaken it.
        Returns whether it was newly applied. Queued jobs keep their identity, status and order.
        """

        record = copy.deepcopy(dict(incident))
        if not str(record.get("incident_id") or ""):
            raise ValueError("a GPU quarantine requires an incident_id")
        # ``_quarantine_lock`` keeps the durable write and the projection of one apply/release together, so a
        # concurrent release can never leave the persisted record and the in-memory flag disagreeing. It is only
        # ever taken before ``_lock`` and never held across a listener notification.
        with self._quarantine_lock:
            with self._lock:
                if self._gpu_quarantine is not None:
                    return False
                self._gpu_quarantine = record
            try:
                self._repository.set_setting(GPU_QUARANTINE_SETTING, record)
            except Exception:  # noqa: BLE001 - containment must hold even when it cannot be made durable
                logger.exception("GPU quarantine %s could not be persisted", record["incident_id"])
                with self._lock:
                    if self._gpu_quarantine is not None:
                        self._gpu_quarantine = {**self._gpu_quarantine, "persisted": False}
        self._notify_state_listeners()
        return True

    def release_gpu_quarantine(self, incident_id: str | None = None) -> bool:
        """Make GPU work claimable again, in original priority/FIFO order (durable first, then in memory).

        ``incident_id`` (when given) must name the active incident, so a stale approval releases nothing. Policy
        (positive evidence, operator confirmation) belongs to the caller; this only performs the transition.
        """

        with self._quarantine_lock:
            with self._lock:
                current = self._gpu_quarantine
                if current is None or (incident_id is not None and current.get("incident_id") != incident_id):
                    return False
            try:
                self._repository.set_setting(GPU_QUARANTINE_SETTING, None)
            except Exception:  # noqa: BLE001 - a durable record that cannot be cleared must not be half-released
                if current.get("persisted") is not False:
                    logger.exception("GPU quarantine %s could not be durably released", current.get("incident_id"))
                    return False
                # The apply never became durable, so no record exists to clear: the in-memory flag stays releasable.
                logger.warning("GPU quarantine %s was never persisted; releasing in memory", current.get("incident_id"))
            with self._lock:
                self._gpu_quarantine = None
        self._notify_state_listeners()
        return True

    def gpu_quarantine_info(self) -> dict[str, Any] | None:
        with self._lock:
            return copy.deepcopy(self._gpu_quarantine) if self._gpu_quarantine is not None else None

    def is_gpu_quarantined(self) -> bool:
        with self._lock:
            return self._gpu_quarantine is not None

    def _assessment_locked(self, job: Job) -> DependencyAssessment:
        assessment = self._dependency_cache.get(job.job_id)
        if assessment is None:
            assessment = classify_job(job)
            self._dependency_cache[job.job_id] = assessment
        return assessment

    def _held_by_webui_locked(self, job: Job) -> bool:
        return self._webui_hold is not None and self._assessment_locked(job).held_by_webui_outage

    def _held_by_gpu_loss_locked(self, job: Job) -> bool:
        return self._gpu_quarantine is not None and self._assessment_locked(job).held_by_gpu_loss

    def _is_held_locked(self, job: Job) -> bool:
        return self._held_by_gpu_loss_locked(job) or self._held_by_webui_locked(job)

    def is_job_held(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job is not None and self._is_held_locked(job))

    def is_job_held_by_webui(self, job_id: str) -> bool:
        """Held by the WebUI outage hold specifically (projections must not blame the WebUI for a GPU hold)."""

        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job is not None and self._held_by_webui_locked(job))

    def is_job_held_by_gpu_loss(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job is not None and self._held_by_gpu_loss_locked(job))

    def dispatch_summary(self) -> dict[str, Any]:
        """Deterministic counts of QUEUED work by dispatch eligibility (projection only)."""

        with self._lock:
            queued = [job for job in self._jobs.values() if job.status == JobStatus.QUEUED]
            held = [job for job in queued if self._is_held_locked(job)]
            return {
                "queued": len(queued),
                "held_webui": sum(1 for job in queued if self._held_by_webui_locked(job)),
                "held_gpu_loss": sum(1 for job in queued if self._held_by_gpu_loss_locked(job)),
                "held": len(held),
                "eligible": len(queued) - len(held),
                "independent": sum(
                    1
                    for job in queued
                    if not self._assessment_locked(job).held_by_webui_outage
                    and not self._held_by_gpu_loss_locked(job)
                ),
                "unresolved": sum(
                    1
                    for job in held
                    if self._assessment_locked(job).dependency.value == "unresolved_dependency"
                ),
                "hold": dict(self._webui_hold) if self._webui_hold is not None else None,
                "gpu_quarantine": (
                    copy.deepcopy(self._gpu_quarantine) if self._gpu_quarantine is not None else None
                ),
            }

    def _pop_next_eligible_locked(self) -> tuple[tuple[int, int, str], Job, list[tuple[int, int, str]]] | None:
        """Highest-priority, FIFO eligible QUEUED entry popped from the heap; held entries are set aside intact."""

        skipped: list[tuple[int, int, str]] = []
        while self._queue:
            item = heapq.heappop(self._queue)
            job = self._jobs.get(item[2])
            if job is None or job.status != JobStatus.QUEUED:
                continue
            if self._is_held_locked(job):
                skipped.append(item)
                continue
            return item, job, skipped
        for item in skipped:
            heapq.heappush(self._queue, item)
        return None

    def get_next_job(self) -> Job | None:
        """Pop the next eligible job (held jobs are skipped without losing their place)."""
        with self._lock:
            if self._paused or self._dispatch_fenced:
                return None
            found = self._pop_next_eligible_locked()
            if found is None:
                return None
            item, job, skipped = found
            for held in skipped:
                heapq.heappush(self._queue, held)
            self._claimed_counters[job.job_id] = item[1]
            return job

    def pause(self) -> None:
        self._repository.set_setting("queue_paused", True)
        with self._lock:
            self._paused = True
        self._notify_state_listeners()

    def resume(self) -> None:
        self._repository.set_setting("queue_paused", False)
        with self._lock:
            self._paused = False
        self._notify_state_listeners()

    def is_paused(self) -> bool:
        with self._lock:
            return bool(self._paused)

    def pause_running_job(self) -> Job | None:
        self.pause()
        with self._lock:
            return next(
                (job for job in self._jobs.values() if job.status == JobStatus.RUNNING), None
            )

    def resume_running_job(self) -> Job | None:
        self.resume()
        with self._lock:
            return next(
                (job for job in self._jobs.values() if job.status == JobStatus.RUNNING), None
            )

    def cancel_running_job(self, *, return_to_queue: bool = False) -> Job | None:
        with self._lock:
            running = next(
                (job for job in self._jobs.values() if job.status == JobStatus.RUNNING), None
            )
            if running is None:
                return None
        if return_to_queue:
            running.execution_metadata.last_control_action = "return_to_queue"
            running.execution_metadata.return_to_queue_count += 1
            running.progress = 0.0
            running.eta_seconds = None
            running.error_message = None
            running.result = None
            persisted = self._repository.transition_job(running, JobStatus.QUEUED)
            with self._lock:
                self._copy_persisted_state(running, persisted)
                self._counter += 1
                self._queue = [(p, c, jid) for (p, c, jid) in self._queue if jid != running.job_id]
                heapq.heappush(self._queue, (-int(running.priority), self._counter, running.job_id))
                heapq.heapify(self._queue)
            self._notify_status(running, JobStatus.QUEUED)
            self._notify_state_listeners()
        else:
            running.execution_metadata.last_control_action = "cancelled"
            self._update_status(running.job_id, JobStatus.CANCELLED, "cancelled")
        return running

    def return_undispatched_to_queue(self, job_id: str, *, reason: str) -> Job | None:
        """Restore a RUNNING job to QUEUED with its original identity and position.

        Only the outage coordinator calls this, and only on positive evidence that no part of the job was dispatched.
        Durable queue order is untouched by the transition, and the in-memory heap entry keeps its original counter.
        """

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != JobStatus.RUNNING:
                return None
            counter = self._claimed_counters.get(job_id)
        job.execution_metadata.last_control_action = "outage_requeue_undispatched"
        job.execution_metadata.return_to_queue_count += 1
        job.progress = 0.0
        job.eta_seconds = None
        job.error_message = None
        job.error_envelope = None
        job.result = None
        persisted = self._repository.transition_job(job, JobStatus.QUEUED)
        with self._lock:
            self._copy_persisted_state(job, persisted)
            if counter is None:
                self._counter += 1
                counter = self._counter
            self._queue = [(p, c, jid) for (p, c, jid) in self._queue if jid != job_id]
            heapq.heappush(self._queue, (-int(job.priority), counter, job_id))
        self._notify_status(job, JobStatus.QUEUED)
        self._notify_state_listeners()
        return job

    def mark_running(self, job_id: str) -> Job | None:
        """Move a job to RUNNING; ``None`` when unknown or when the dispatch fence refuses a QUEUED job."""
        return self._update_status(job_id, JobStatus.RUNNING)

    def mark_completed(self, job_id: str, result: dict | None = None) -> None:
        self._update_status(job_id, JobStatus.COMPLETED, result=result)

    def mark_failed(self, job_id: str, error_message: str, result: dict | None = None) -> None:
        job = self._update_status(job_id, JobStatus.FAILED, error_message, result=result)
        if job:
            job.error_message = error_message

    def mark_cancelled(self, job_id: str, reason: str | None = None) -> Job | None:
        return self._update_status(job_id, JobStatus.CANCELLED, reason or "cancelled")

    def publish_result(
        self,
        job_id: str,
        *,
        status: JobStatus,
        result: dict[str, Any],
        stage_checkpoints: list[StageCheckpoint],
        error_message: str | None = None,
    ) -> Job | None:
        """Publish a terminal runner result only while the job still owns RUNNING."""
        if status not in {JobStatus.COMPLETED, JobStatus.FAILED}:
            raise ValueError("Runner results may only publish completed or failed status")
        return self._update_status(
            job_id,
            status,
            error_message,
            result=result,
            stage_checkpoints=stage_checkpoints,
            require_running=True,
        )

    def list_jobs(self, status_filter: JobStatus | None = None) -> list[Job]:
        with self._lock:
            if status_filter is None:
                return list(self._jobs.values())
            return [job for job in self._jobs.values() if job.status == status_filter]

    def list_active_jobs_ordered(self) -> list[Job]:
        """Return running + queued jobs in display order.

        Running jobs appear first, followed by queued jobs in actual queue order.
        """
        with self._lock:
            running_jobs = [job for job in self._jobs.values() if job.status == JobStatus.RUNNING]
            queued_jobs = [
                self._jobs[jid]
                for _, _, jid in self._get_ordered_queued_jobs()
                if jid in self._jobs
            ]
            return running_jobs + queued_jobs

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return job
            finalized = self._finalized_jobs.get(job_id)
        return finalized or self._repository.get_job_model(job_id)

    def _update_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: str | None = None,
        result: dict | None = None,
        stage_checkpoints: list[StageCheckpoint] | None = None,
        require_running: bool = False,
        require_queued: bool = False,
    ) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or (require_running and job.status != JobStatus.RUNNING):
                return None
            if require_queued and job.status != JobStatus.QUEUED:
                return None
            if status is JobStatus.RUNNING and job.status is JobStatus.QUEUED:
                if self._dispatch_fenced or self._is_held_locked(job):
                    return None
            transition_job = job
            if stage_checkpoints is not None:
                execution_metadata = replace(
                    job.execution_metadata,
                    stage_checkpoints=list(stage_checkpoints),
                )
                transition_job = replace(job, execution_metadata=execution_metadata)
            persisted = self._repository.transition_job(
                transition_job,
                status,
                error_message=error_message,
                result=result,
                expected_status=JobStatus.QUEUED if require_queued else None,
            )
            self._copy_persisted_state(job, persisted)
            should_prune = status in self._FINAL_STATUSES
            if should_prune:
                # PR-MEMORY-001: Add to bounded finalized jobs collection
                self._add_finalized_job(job_id, job)
                self._prune_job(job_id)
        self._notify_status(job, status)
        self._notify_state_listeners()
        return job

    def cancel_if_queued(self, job_id: str, reason: str | None = None) -> QueuedCancelOutcome:
        """Cancel ``job_id`` only if it is still QUEUED at the moment of the transition.

        The in-memory check and the durable transition both run under the lock that makes
        ``claim_next_job``'s QUEUED -> RUNNING atomic, and the repository re-checks the durable status in
        the same transaction that writes CANCELLED. A job that a worker claimed first is therefore skipped,
        never cancelled: its generation, process and cancellation token are not touched. The ordinary
        status callbacks, persistence and heap cleanup of ``mark_cancelled`` apply to a job that is cancelled.
        """

        try:
            cancelled = self._update_status(
                job_id, JobStatus.CANCELLED, reason or "cancelled", require_queued=True
            )
        except JobStatusChanged as changed:
            return QueuedCancelOutcome(job_id, "skipped", changed.actual, "status changed")
        except Exception as exc:  # noqa: BLE001 - reported per job; the rest of a batch continues
            return QueuedCancelOutcome(job_id, "error", None, f"{type(exc).__name__}: {exc}")
        if cancelled is not None:
            return QueuedCancelOutcome(job_id, "cancelled", JobStatus.CANCELLED)
        with self._lock:
            live = self._jobs.get(job_id)
            observed = live.status if live is not None else None
        if observed is None:
            stored = self._repository.get_job(job_id)
            observed = stored.status if stored is not None else None
        if observed is None:
            detail = "unknown job"
        elif observed is JobStatus.QUEUED:
            detail = "queued but not in the runnable projection"
        else:
            detail = "status changed"
        return QueuedCancelOutcome(job_id, "skipped", observed, detail)

    def cancel_queued_jobs(
        self, job_ids: Iterable[str], *, reason: str | None = None
    ) -> list[QueuedCancelOutcome]:
        """Guarded queued-only cancel of exactly ``job_ids`` (no other job is considered), in order."""

        outcomes: list[QueuedCancelOutcome] = []
        with self.coalesce_state_notifications():
            for job_id in dict.fromkeys(job_ids):
                outcomes.append(self.cancel_if_queued(job_id, reason))
        return outcomes

    def claim_next_job(self) -> Job | None:
        """Atomically claim the next runnable job for the single-node worker."""
        claimed: Job | None = None
        with self._lock:
            if self._paused or self._dispatch_fenced:
                return None
            found = self._pop_next_eligible_locked()
            if found is not None:
                queue_item, job, skipped = found
                try:
                    persisted = self._repository.transition_job(job, JobStatus.RUNNING)
                except Exception:
                    heapq.heappush(self._queue, queue_item)
                    for held in skipped:
                        heapq.heappush(self._queue, held)
                    raise
                for held in skipped:
                    heapq.heappush(self._queue, held)
                self._copy_persisted_state(job, persisted)
                self._claimed_counters[job.job_id] = queue_item[1]
                claimed = job
        if claimed is not None:
            self._notify_status(claimed, JobStatus.RUNNING)
            self._notify_state_listeners()
        return claimed

    def _add_finalized_job(self, job_id: str, job: Job) -> None:
        """Add job to bounded finalized collection.

        PR-MEMORY-001: Maintains max 100 finalized jobs. When full, evicts oldest.
        Also clears job payload to free memory.
        """
        # Clear payload to free memory (PR-MEMORY-001)
        job.payload = None

        # Check if deque is full and will evict oldest
        if len(self._finalized_jobs_order) == self._finalized_jobs_order.maxlen:
            # Get the oldest job_id that will be evicted
            oldest_jid = self._finalized_jobs_order[0] if self._finalized_jobs_order else None
            if oldest_jid and oldest_jid in self._finalized_jobs:
                self._finalized_jobs.pop(oldest_jid, None)

        # Add new job (deque will auto-evict if at maxlen)
        self._finalized_jobs_order.append(job_id)
        self._finalized_jobs[job_id] = job

    @staticmethod
    def _copy_persisted_state(target: Job, source: Job) -> None:
        for name in (
            "status",
            "updated_at",
            "started_at",
            "completed_at",
            "progress",
            "eta_seconds",
            "worker_id",
            "execution_metadata",
            "error_message",
            "error_envelope",
            "result",
        ):
            setattr(target, name, getattr(source, name))

    def persist_runtime_state(self, job: Job) -> None:
        """Durably checkpoint mutable execution metadata for an active job."""
        self._repository.persist_runtime_state(job)

    def register_status_callback(self, callback: Callable[[Job, JobStatus], None]) -> None:
        """Allow observers to react to job status changes."""
        self._status_callbacks.append(callback)

    def _notify_status(self, job: Job, status: JobStatus) -> None:
        """Notify registered callbacks about status transitions."""
        for callback in list(self._status_callbacks):
            try:
                callback(job, status)
            except Exception:
                continue

    # ------------------------------------------------------------------
    # PR-GUI-F2: Queue Manipulation Methods
    # ------------------------------------------------------------------
    # Each move derives a complete durable order from the projection, so it holds the
    # admission lock to avoid ordering around rows an admission has committed but not yet
    # projected.


    def move_up(self, job_id: str) -> bool:
        """Move a queued job up one position (higher priority).

        Args:
            job_id: The ID of the job to move.

        Returns:
            True if the job was moved, False if not found or already at top.
        """
        moved = False
        with self._admission_lock, self._lock:
            # Find queued jobs in order
            queued = self._get_ordered_queued_jobs()
            for i, (priority, counter, jid) in enumerate(queued):
                if jid == job_id:
                    if i == 0:
                        return False  # Already at top
                    # Swap counters with the job above to change ordering
                    prev_priority, prev_counter, prev_jid = queued[i - 1]
                    if priority != prev_priority:
                        return False
                    candidate = list(queued)
                    candidate[i - 1], candidate[i] = candidate[i], candidate[i - 1]
                    self._repository.update_queue_order([item[2] for item in candidate])
                    self._swap_queue_positions(job_id, prev_jid, counter, prev_counter)
                    moved = True
                    break
        if moved:
            self._notify_state_listeners()
        return moved

    def move_down(self, job_id: str) -> bool:
        """Move a queued job down one position (lower priority).

        Args:
            job_id: The ID of the job to move.

        Returns:
            True if the job was moved, False if not found or already at bottom.
        """
        moved = False
        with self._admission_lock, self._lock:
            queued = self._get_ordered_queued_jobs()
            for i, (priority, counter, jid) in enumerate(queued):
                if jid == job_id:
                    if i == len(queued) - 1:
                        return False  # Already at bottom
                    # Swap counters with the job below to change ordering
                    next_priority, next_counter, next_jid = queued[i + 1]
                    if priority != next_priority:
                        return False
                    candidate = list(queued)
                    candidate[i], candidate[i + 1] = candidate[i + 1], candidate[i]
                    self._repository.update_queue_order([item[2] for item in candidate])
                    self._swap_queue_positions(job_id, next_jid, counter, next_counter)
                    moved = True
                    break
        if moved:
            self._notify_state_listeners()
        return moved

    def move_to_front(self, job_id: str) -> bool:
        """Move a queued job to the front of the queue (highest priority within its priority level).

        Args:
            job_id: The ID of the job to move.

        Returns:
            True if the job was moved, False if not found or already at front.
        """
        moved = False
        with self._admission_lock, self._lock:
            queued = self._get_ordered_queued_jobs()
            if not queued:
                return False

            # Find the job
            job_index = None
            job_priority = None
            for i, (priority, _counter, jid) in enumerate(queued):
                if jid == job_id:
                    job_index = i
                    job_priority = priority
                    break

            if job_index is None:
                return False  # Job not found

            if job_index == 0:
                return False  # Already at front

            # Get the minimum counter value (front of queue) for this priority
            # We want to assign a counter lower than the first job in the same priority level
            min_counter_for_priority = float("inf")
            for priority, counter, _jid in queued:
                if priority == job_priority:
                    min_counter_for_priority = min(min_counter_for_priority, counter)

            # Assign a new lower counter (move to front)
            new_counter = min_counter_for_priority - 1

            candidate = [item for item in queued if item[2] != job_id]
            insert_at = next(
                (index for index, item in enumerate(candidate) if item[0] == job_priority),
                0,
            )
            candidate.insert(insert_at, queued[job_index])
            self._repository.update_queue_order([item[2] for item in candidate])

            # Update the in-memory projection after the durable order succeeds.
            new_queue = []
            for priority, counter, jid in self._queue:
                if jid == job_id:
                    new_queue.append((priority, new_counter, jid))
                else:
                    new_queue.append((priority, counter, jid))
            self._queue = new_queue
            heapq.heapify(self._queue)
            moved = True
        if moved:
            self._notify_state_listeners()
        return moved

    def move_to_back(self, job_id: str) -> bool:
        """Move a queued job to the back of the queue (lowest priority within its priority level).

        Args:
            job_id: The ID of the job to move.

        Returns:
            True if the job was moved, False if not found or already at back.
        """
        moved = False
        with self._admission_lock, self._lock:
            queued = self._get_ordered_queued_jobs()
            if not queued:
                return False

            # Find the job
            job_index = None
            job_priority = None
            for i, (priority, _counter, jid) in enumerate(queued):
                if jid == job_id:
                    job_index = i
                    job_priority = priority
                    break

            if job_index is None:
                return False  # Job not found

            if job_index == len(queued) - 1:
                return False  # Already at back

            # Get the maximum counter value (back of queue) for this priority
            # We want to assign a counter higher than the last job in the same priority level
            max_counter_for_priority = float("-inf")
            for priority, counter, _jid in queued:
                if priority == job_priority:
                    max_counter_for_priority = max(max_counter_for_priority, counter)

            # Assign a new higher counter (move to back)
            new_counter = max_counter_for_priority + 1

            candidate = [item for item in queued if item[2] != job_id]
            insert_at = (
                max(
                    (index for index, item in enumerate(candidate) if item[0] == job_priority),
                    default=len(candidate) - 1,
                )
                + 1
            )
            candidate.insert(insert_at, queued[job_index])
            self._repository.update_queue_order([item[2] for item in candidate])

            # Update the in-memory projection after the durable order succeeds.
            new_queue = []
            for priority, counter, jid in self._queue:
                if jid == job_id:
                    new_queue.append((priority, new_counter, jid))
                else:
                    new_queue.append((priority, counter, jid))
            self._queue = new_queue
            heapq.heapify(self._queue)
            moved = True
        if moved:
            self._notify_state_listeners()
        return moved

    def remove(self, job_id: str) -> Job | None:
        """Remove a job from the queue.

        Args:
            job_id: The ID of the job to remove.

        Returns:
            The removed Job, or None if not found.
        """
        with self._lock:
            live_job = self._jobs.get(job_id)
            if live_job is None or live_job.status == JobStatus.RUNNING:
                return None
        return self.mark_cancelled(job_id, "removed from queue")

    def clear(self) -> int:
        """Clear all queued jobs (not running or completed).

        Returns:
            The number of jobs removed.
        """
        with self._lock:
            queued_ids = [jid for jid, job in self._jobs.items() if job.status == JobStatus.QUEUED]
        with self.coalesce_state_notifications():
            for job_id in queued_ids:
                self.mark_cancelled(job_id, "queue cleared")
        return len(queued_ids)

    def _get_ordered_queued_jobs(self) -> list[tuple[int, int, str]]:
        """Get queued jobs in priority order (internal, must hold lock)."""
        queued = []
        for priority, counter, jid in self._queue:
            job = self._jobs.get(jid)
            if job and job.status == JobStatus.QUEUED:
                queued.append((priority, counter, jid))
        # Sort by priority (higher first), then by counter (lower first)
        queued.sort(key=lambda x: (x[0], x[1]))
        return queued

    def _swap_queue_positions(
        self, job_id1: str, job_id2: str, counter1: int, counter2: int
    ) -> None:
        """Swap queue positions between two jobs (internal, must hold lock)."""
        # Swap counters to preserve priority ordering while reordering within priority.
        new_queue = []
        for priority, counter, jid in self._queue:
            if jid == job_id1:
                new_queue.append((priority, counter2, jid))
            elif jid == job_id2:
                new_queue.append((priority, counter1, jid))
            else:
                new_queue.append((priority, counter, jid))
        self._queue = new_queue
        heapq.heapify(self._queue)

    def _prune_job(self, job_id: str) -> None:
        """Remove a terminal job from the queue heap."""
        self._jobs.pop(job_id, None)
        self._dependency_cache.pop(job_id, None)
        self._claimed_counters.pop(job_id, None)
        self._queue = [(p, c, jid) for (p, c, jid) in self._queue if jid != job_id]
        heapq.heapify(self._queue)

    def register_state_listener(self, callback: Callable[[], None]) -> None:
        """Register a listener for queue state changes."""
        if callback not in self._state_listeners:
            self._state_listeners.append(callback)

    def coalesce_state_notifications(self) -> _QueueStateNotificationBatch:
        return _QueueStateNotificationBatch(self)

    def _notify_state_listeners(self) -> None:
        """Notify listeners that the queue state has changed."""
        with self._lock:
            if self._state_notifications_suppressed > 0:
                self._state_notifications_pending = True
                return
            listeners = list(self._state_listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:
                continue

    def restore_jobs(self, jobs: Iterable[Job]) -> None:
        """Submit recovered jobs through repository authority.

        Offline legacy recovery should normally use the migration tool; this
        method remains for callers that already hold valid NJR-backed jobs.
        """
        with self.coalesce_state_notifications():
            for job in jobs:
                job.status = JobStatus.QUEUED
                self.submit(job)


class _QueueStateNotificationBatch:
    def __init__(self, queue: JobQueue) -> None:
        self._queue = queue

    def __enter__(self) -> _QueueStateNotificationBatch:
        with self._queue._lock:
            self._queue._state_notifications_suppressed += 1
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        listeners: list[Callable[[], None]] = []
        with self._queue._lock:
            self._queue._state_notifications_suppressed = max(
                0,
                self._queue._state_notifications_suppressed - 1,
            )
            should_flush = (
                self._queue._state_notifications_suppressed == 0
                and self._queue._state_notifications_pending
            )
            if should_flush:
                self._queue._state_notifications_pending = False
                listeners = list(self._queue._state_listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:
                continue
        return False
