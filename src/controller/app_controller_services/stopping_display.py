"""Display-only "Stopping..." row for an operator cancel (owner decision 12, 2026-11-28).

A plain cancel commits the queue's guarded durable CANCELLED before the backend has stopped, and the queue announces it
at once. The single worker claims nothing else until the cancelled job's ``run_njr`` returns, so only the display is
wrong in between: the running row would vanish while the GPU is still busy. This keeps that row, labelled
``Stopping...``, until the runner releases the job.

It changes no job status, database row, history record or sync payload: the label exists only in the GUI projection,
and the release is decided by re-reading the runner's ``current_job`` on the UI thread.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

STOPPING_LABEL = "Stopping..."
RELEASE_CHECK_MS = 250


def defer_on_ui_loop(
    main_window: Any | None,
    delay_ms: int,
    fn: Callable[[], None],
    root_after: Callable[[int, Callable[[], None]], bool],
) -> bool:
    """Run ``fn`` on the UI loop after ``delay_ms``; False (``fn`` not scheduled) when there is no UI loop."""
    later = getattr(main_window, "run_in_main_thread_later", None)
    if callable(later):
        later(int(delay_ms), fn)
        return True
    return bool(root_after(int(delay_ms), fn))


class StoppingDisplay:
    """Holds the running row of one cancelled job until the runner lets it go.

    ``schedule_later(delay_ms, fn)`` must return False when it cannot defer ``fn`` (no Tk loop, headless tests); the
    row is then released as soon as the queue reports the job settled, exactly as before.
    """

    def __init__(
        self,
        *,
        current_runner_job: Callable[[], Any | None],
        publish_running_job: Callable[[Any | None], Any],
        schedule_later: Callable[[int, Callable[[], None]], bool],
        check_ms: int = RELEASE_CHECK_MS,
    ) -> None:
        self._current_runner_job = current_runner_job
        self._publish_running_job = publish_running_job
        self._schedule_later = schedule_later
        self._check_ms = check_ms
        self._job_id: str | None = None
        self._can_defer = False
        self._arming = False
        self._ran_inline = False

    def begin(self) -> None:
        """Call on the UI thread just before an operator cancel of the runner's current job."""
        job = self._current_runner_job()
        job_id = getattr(job, "job_id", None)
        if job is None or not job_id:
            return
        self._job_id = str(job_id)
        self._publish_running_job(job)
        self._can_defer = self._arm()

    def holds(self, job: Any | None) -> bool:
        return self._job_id is not None and getattr(job, "job_id", None) == self._job_id

    def keeps_row(self, job: Any | None) -> bool:
        """True when the caller must not clear the running row for ``job`` (a deferred check will)."""
        if not self.holds(job):
            return False
        if not self._can_defer:
            self._job_id = None
            return False
        return True

    def clear(self) -> None:
        self._job_id = None

    def _arm(self) -> bool:
        # A scheduler may run the callback inline when it has no UI loop (the main window falls back to calling it
        # at once); that is not a deferral, and re-checking inline would recurse while the runner holds the job.
        self._arming, self._ran_inline = True, False
        try:
            scheduled = bool(self._schedule_later(self._check_ms, self._deferred_check))
        finally:
            self._arming = False
        return scheduled and not self._ran_inline

    def _deferred_check(self) -> None:
        if self._arming:
            self._ran_inline = True
            return
        self._check()

    def _check(self) -> None:
        if self._job_id is None:
            return
        current = self._current_runner_job()
        held = current is not None and getattr(current, "job_id", None) == self._job_id
        if held and self._arm():
            return
        self._job_id = None
        self._publish_running_job(None if held else current)
