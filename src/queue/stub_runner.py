# Subsystem: Queue
# Role: Test stub for SingleNodeJobRunner - does not execute real jobs.

"""Test stub runner that satisfies SingleNodeJobRunner interface without execution.

PR-0114C-T(x): This module provides a StubRunner for tests that:
- Do not want to execute real SD/WebUI pipelines.
- Need to verify queue/controller wiring without side effects.
- Want to avoid threading issues in test environments.

Production code should never use StubRunner. It is strictly for test fixtures.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.queue.job_model import Job
    from src.queue.job_queue import JobQueue

logger = logging.getLogger(__name__)


class StubRunner:
    """Test stub for SingleNodeJobRunner.

    - Satisfies the same interface as SingleNodeJobRunner.
    - Does not spawn a worker thread.
    - Does not call PipelineController._run_job or any SD/WebUI client.
    - Safe to use in controller/GUI tests that don't need real execution.
    """

    def __init__(
        self,
        job_queue: JobQueue,
        run_callable: object = None,
        poll_interval: float = 0.1,
        on_status_change: object = None,
    ) -> None:
        """Initialize StubRunner with same signature as SingleNodeJobRunner."""
        self._job_queue = job_queue
        self._run_callable = run_callable  # Ignored - we don't run jobs
        self._poll_interval = poll_interval
        self._on_status_change = on_status_change
        self._running = False
        self._current_job: Job | None = None

    def start(self) -> None:
        """Start the runner (no-op in stub)."""
        logger.debug("StubRunner.start() called - no actual execution")
        self._running = True

    def stop(self) -> None:
        """Stop the runner (no-op in stub)."""
        logger.debug("StubRunner.stop() called")
        self._running = False

    def is_running(self) -> bool:
        """Check if runner is 'running' (always returns current flag state)."""
        return self._running

    def run_once(self, job: Job) -> dict | None:
        """Synchronously 'run' a job (no-op, returns empty result)."""
        logger.debug("StubRunner.run_once() called for job %s - returning empty result", job.job_id)
        return {}

    def cancel_current(self) -> None:
        """Cancel current job (no-op in stub)."""
        logger.debug("StubRunner.cancel_current() called")
        self._current_job = None

    @property
    def current_job(self) -> Job | None:
        """Return current job (always None in stub)."""
        return self._current_job
