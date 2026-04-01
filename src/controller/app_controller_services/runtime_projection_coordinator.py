from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from src.contracts import (
    HistoryProjection,
    OperatorLogEntry,
    PreviewProjection,
    PreviewRequest,
    ProjectionSink,
    QueueProjection,
    RuntimeProjection,
    WebUIProjection,
)
from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.pipeline.job_models_v2 import NormalizedJobRecord, RuntimeJobStatus, UnifiedJobSummary
from src.queue.job_history_store import JobHistoryEntry


class RuntimeProjectionCoordinator:
    """Serialize runtime-originated projections through a single sink."""

    def __init__(
        self,
        *,
        sink: ProjectionSink,
        background_tasks: BackgroundTaskCoordinator,
        build_queue_projection: Callable[[], tuple[list[str], list[UnifiedJobSummary]]],
        load_history_entries: Callable[[int | None], list[JobHistoryEntry]],
        summarize_running_job: Callable[[Any], UnifiedJobSummary | None],
        logger: logging.Logger | None = None,
    ) -> None:
        self._sink = sink
        self._background_tasks = background_tasks
        self._build_queue_projection = build_queue_projection
        self._load_history_entries = load_history_entries
        self._summarize_running_job = summarize_running_job
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._revisions: dict[str, int] = {}

    def get_metrics_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "surface_revisions": dict(self._revisions),
                "background_tasks": self._background_tasks.get_metrics_snapshot(),
            }

    def publish_queue_refresh(self) -> int:
        revision = self._next_revision("queue")
        self._background_tasks.submit(
            "projection:queue",
            self._build_queue_projection,
            on_result=lambda result, revision=revision: self._sink.apply_queue_projection(
                QueueProjection(
                    revision=revision,
                    queue_items=tuple(result[0]),
                    queue_jobs=tuple(result[1]),
                )
            ),
            on_error=lambda exc: self._logger.error(
                "Queue projection refresh failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            ),
            name="QueueProjectionRefresh",
            purpose="Refresh queue projections off the UI thread",
        )
        return revision

    def publish_history_refresh(self, *, limit: int | None = None) -> int:
        revision = self._next_revision("history")
        self._background_tasks.submit(
            "projection:history",
            lambda: self._load_history_entries(limit),
            on_result=lambda entries, revision=revision: self._sink.apply_history_projection(
                HistoryProjection(revision=revision, history_items=tuple(entries))
            ),
            on_error=lambda exc: self._logger.error(
                "History projection refresh failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            ),
            name="HistoryProjectionRefresh",
            purpose="Refresh history projections off the UI thread",
        )
        return revision

    def publish_preview_refresh(
        self,
        request: PreviewRequest,
        *,
        build_preview_jobs: Callable[[PreviewRequest], list[NormalizedJobRecord]],
        on_complete: Callable[[bool, Exception | None], None] | None = None,
    ) -> int:
        revision = self._next_revision("preview")
        self._background_tasks.submit(
            "projection:preview",
            lambda: build_preview_jobs(request),
            on_result=lambda jobs, revision=revision: self._sink.apply_preview_projection(
                PreviewProjection(revision=revision, preview_jobs=tuple(jobs or []))
            ),
            on_error=lambda exc: self._logger.error(
                "Preview projection refresh failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            ),
            on_complete=on_complete,
            name="PreviewProjectionRefresh",
            purpose="Refresh preview projections off the UI thread",
        )
        return revision

    def publish_running_job(self, job: Any | None) -> int:
        revision = self._next_revision("runtime")
        summary = self._summarize_running_job(job)
        self._sink.apply_runtime_projection(
            RuntimeProjection(revision=revision, running_job=summary)
        )
        return revision

    def publish_runtime_status(self, status: RuntimeJobStatus | None) -> int:
        revision = self._next_revision("runtime")
        self._sink.apply_runtime_projection(
            RuntimeProjection(revision=revision, runtime_status=status)
        )
        return revision

    def publish_queue_status(self, status: str) -> int:
        revision = self._next_revision("runtime")
        self._sink.apply_runtime_projection(
            RuntimeProjection(revision=revision, queue_status=status)
        )
        return revision

    def publish_webui_state(self, state: str) -> int:
        revision = self._next_revision("runtime")
        self._sink.apply_runtime_projection(
            RuntimeProjection(revision=revision, webui_state=state)
        )
        return revision

    def publish_last_error(self, message: str | None) -> int:
        revision = self._next_revision("runtime")
        self._sink.apply_runtime_projection(
            RuntimeProjection(revision=revision, last_error=message)
        )
        return revision

    def publish_webui_resources(self, resources: dict[str, list[Any]] | None) -> int:
        if resources is None:
            return self._current_revision("webui")
        revision = self._next_revision("webui")
        self._sink.apply_webui_projection(
            WebUIProjection(revision=revision, resources=resources)
        )
        return revision

    def append_operator_log(self, text: str) -> int:
        revision = self._next_revision("operator_log")
        self._sink.append_operator_log(
            OperatorLogEntry(revision=revision, line=str(text))
        )
        return revision

    def _current_revision(self, surface: str) -> int:
        with self._lock:
            return self._revisions.get(surface, 0)

    def _next_revision(self, surface: str) -> int:
        with self._lock:
            revision = self._revisions.get(surface, 0) + 1
            self._revisions[surface] = revision
            return revision
