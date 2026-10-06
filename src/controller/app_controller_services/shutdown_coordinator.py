"""Application-shutdown sequencing for the job queue (PR-RUNTIME-SHUTDOWN-140).

``AppController`` coordinates; the synchronization lives below it: the atomic claim fence in ``JobQueue``, the worker
lifecycle in ``SingleNodeJobRunner`` and the service boundary in ``JobService``. This module only sequences those
existing owners for application shutdown and enforces one invariant: **the shared SQLite ``JobRepository`` is closed
only after every queue worker has definitively quiesced.** It creates no queue, repository or lifecycle authority.

Order (driven by ``AppController.shutdown_app``): fence admission -> cancel the active job (existing semantics) ->
runtime/background teardown -> bounded stop with a verified quiescence result -> final queue-state save while the
repository is still open -> repository close, only when quiescent.
"""

from __future__ import annotations

import logging
from typing import Any

from src.controller.job_service_shutdown import stop_with_timeout

logger = logging.getLogger(__name__)

#: Bounded wait for the queue worker to finish the job it already owns and exit (the long-standing 10 s join).
QUEUE_QUIESCE_TIMEOUT_SECONDS = 10.0
#: Extra bounded wait when ``AppController.shutdown`` is reached without a prior quiescent stop.
REPOSITORY_FINAL_CHECK_SECONDS = 1.0


def fence_queue_admission(job_service: Any) -> bool:
    """Make shutdown authoritative for the queue *before* any slow teardown. Never raises."""
    fence = getattr(job_service, "begin_shutdown", None)
    if not callable(fence):
        return False
    try:
        fence()
    except Exception:
        logger.exception("Error fencing queue admission during shutdown")
        return False
    logger.info("[controller] Queue admission fenced: no queued job can start; pending jobs stay durable")
    return True


def _verdict(job_service: Any, stop_result: Any) -> bool:
    if isinstance(stop_result, bool):
        return stop_result
    query = getattr(job_service, "is_quiescent", None)
    # A service that cannot report quiescence (a test double) has no queue worker this controller can inspect.
    return bool(query()) if callable(query) else True


def quiesce_job_service(job_service: Any, timeout: float | None = None) -> bool:
    """Stop the queue worker within a bound and return whether it has definitively quiesced."""
    if not job_service or not callable(getattr(job_service, "stop", None)):
        return True
    limit = QUEUE_QUIESCE_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        result = stop_with_timeout(job_service, limit)
    except Exception:
        logger.exception("Error stopping job service")
        result = None
    quiescent = _verdict(job_service, result)
    if not quiescent:
        logger.error(
            "[controller] Queue worker did not quiesce within %.1fs; shutdown continues without closing the repository",
            limit,
        )
    return quiescent


def close_repository_when_quiescent(job_service: Any) -> bool:
    """Close the shared ``JobRepository`` only after verified worker quiescence; never under a live worker."""
    store = getattr(job_service, "history_store", None) if job_service else None
    close = getattr(store, "close", None) or getattr(store, "shutdown", None)
    if not callable(close):
        return False
    query = getattr(job_service, "is_quiescent", None)
    if callable(query) and not query() and not quiesce_job_service(job_service, REPOSITORY_FINAL_CHECK_SECONDS):
        logger.error(
            "[controller] shutdown(): Job repository NOT closed: a queue worker is still alive. Closing SQLite "
            "under it would fail its result persistence; queued jobs remain durably QUEUED."
        )
        return False
    try:
        close()
    except Exception as exc:
        logger.error("[controller] shutdown(): Error closing job repository: %s", exc)
        return False
    logger.info("[controller] shutdown(): Job repository closed")
    return True
