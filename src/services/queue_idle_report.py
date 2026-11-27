"""Log why nothing is running while jobs are queued (RUN-LEAN).

The owner queues a day of work and walks away, so an idle queue has to leave evidence. This only observes: it never
claims, releases, pauses or starts anything. It runs on the watchdog thread rather than the queue worker, because
several causes of an idle queue leave no worker at all.
"""

from __future__ import annotations

import logging
from typing import Any

from src.queue.job_model import JobStatus
from src.utils.logger import LogContext, log_with_ctx

logger = logging.getLogger(__name__)

#: Queued work with nothing running for this long is reported.
IDLE_REPORT_AFTER_S = 60.0
#: How often an unchanged idle queue is reported again.
IDLE_REPEAT_S = 600.0
#: How often the queue is looked at.
SAMPLE_EVERY_S = 5.0


def idle_reason(job_service: Any, job_controller: Any = None) -> str:
    """The first condition, in dispatch order, that explains why no queued job is being claimed."""

    queue = job_service.job_queue
    update_hold = queue.update_hold_info()
    if update_hold is not None:
        return f"held for an app update ({update_hold.get('reason') or 'no reason given'})"
    if queue.is_paused():
        return "the queue is paused"
    summary = queue.dispatch_summary()
    if summary["eligible"] == 0 and summary["gpu_quarantine"] is not None:
        return "held after a GPU device loss until the operator confirms recovery"
    if summary["eligible"] == 0 and summary["hold"] is not None:
        return f"held while the WebUI is unavailable ({summary['hold'].get('reason') or 'no reason given'})"
    if getattr(job_controller, "_deferred_autostart", False) is True:
        return "waiting for the WebUI to become ready after start-up"
    if not getattr(job_service, "auto_run_enabled", True):
        return "auto-run is off"
    runner = getattr(job_service, "runner", None)
    if runner is None or not runner.is_running():
        return "no queue worker is running although auto-run is on"
    return "the queue worker is running but has not started a job (it may be preparing a runtime)"


class QueueIdleReporter:
    """One idle episode at a time: report it after the threshold, when its reason changes, and now and then."""

    def __init__(
        self, *, after_s: float = IDLE_REPORT_AFTER_S, repeat_s: float = IDLE_REPEAT_S
    ) -> None:
        self._after_s = after_s
        self._repeat_s = repeat_s
        self._next_sample = float("-inf")
        self._idle_since: float | None = None
        self._reason: str | None = None
        self._reported_at = 0.0
        self._failure_logged = False

    def observe(self, now: float, job_service: Any, job_controller: Any = None) -> None:
        if job_service is None or now < self._next_sample:
            return
        self._next_sample = now + SAMPLE_EVERY_S
        try:
            self._observe(now, job_service, job_controller)
        except Exception:  # noqa: BLE001 - observation must never disturb the watchdog or the queue
            if not self._failure_logged:
                self._failure_logged = True
                logger.warning(
                    "The idle-queue check failed; idle periods may go unreported", exc_info=True
                )

    def _observe(self, now: float, job_service: Any, job_controller: Any) -> None:
        queue = job_service.job_queue
        queued = len(queue.list_jobs(status_filter=JobStatus.QUEUED))
        if queued == 0 or queue.list_jobs(status_filter=JobStatus.RUNNING):
            if self._reason is not None and self._idle_since is not None:
                self._log(
                    logging.INFO,
                    f"QUEUE_IDLE_END | Idle period over after {now - self._idle_since:.0f}s",
                    queued,
                )
            self._idle_since = self._reason = None
            return
        if self._idle_since is None:
            self._idle_since = now
        idle_s = now - self._idle_since
        if idle_s < self._after_s:
            return
        reason = idle_reason(job_service, job_controller)
        if reason == self._reason and now - self._reported_at < self._repeat_s:
            return
        self._reason, self._reported_at = reason, now
        self._log(
            logging.WARNING,
            f"QUEUE_IDLE | {queued} job(s) queued and nothing has run for {idle_s:.0f}s: {reason}",
            queued,
            idle_s=int(idle_s),
            reason=reason,
        )

    @staticmethod
    def _log(level: int, message: str, queued: int, **fields: Any) -> None:
        log_with_ctx(
            logger,
            level,
            message,
            ctx=LogContext(subsystem="queue_idle"),
            extra_fields={"queued": queued, **fields},
        )
