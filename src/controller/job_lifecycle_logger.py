from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from src.gui.app_state_v2 import AppStateV2
from src.pipeline.job_models_v2 import JobLifecycleLogEvent


class JobLifecycleLogger:
    """Emit structured job lifecycle events into AppStateV2."""

    def __init__(
        self,
        app_state: AppStateV2 | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._app_state = app_state
        self._clock = clock or datetime.utcnow

    def set_app_state(self, app_state: AppStateV2 | None) -> None:
        self._app_state = app_state

    def log_add_to_job(self, *, source: str, draft_size: int) -> None:
        self._log(
            source=source,
            event_type="add_to_job",
            message=f"Add to Job clicked; draft contains {draft_size} part(s).",
            draft_size=draft_size,
        )

    def log_add_to_queue(self, *, source: str, job_id: str | None, draft_size: int) -> None:
        self._log(
            source=source,
            event_type="add_to_queue",
            job_id=job_id,
            draft_size=draft_size,
            message=f"Submitted draft to queue (job_id={job_id}) with {draft_size} part(s).",
        )

    def log_job_submitted(self, *, source: str, job_id: str | None) -> None:
        """Track whenever a job leaves controller and is accepted for execution."""
        self._log(
            source=source,
            event_type="job_submitted",
            job_id=job_id,
            message="Job accepted by JobService for execution.",
        )

    def log_job_started(self, *, source: str, job_id: str | None) -> None:
        self._log(
            source=source,
            event_type="job_started",
            job_id=job_id,
            message="Runner picked up job.",
        )

    def log_job_finished(self, *, source: str, job_id: str | None, status: str, message: str) -> None:
        self._log(
            source=source,
            event_type=f"job_{status}",
            job_id=job_id,
            message=message,
        )

    def _log(
        self,
        *,
        source: str,
        event_type: str,
        message: str,
        job_id: str | None = None,
        bundle_id: str | None = None,
        draft_size: int | None = None,
    ) -> None:
        if self._app_state is None:
            return
        event = JobLifecycleLogEvent(
            timestamp=self._clock(),
            source=source,
            event_type=event_type,
            job_id=job_id,
            bundle_id=bundle_id,
            draft_size=draft_size,
            message=message,
        )
        try:
            self._app_state.append_log_event(event)
        except Exception:
            pass
