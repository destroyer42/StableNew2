from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from src.contracts import (
    UNSET,
    HistoryProjection,
    OperatorLogEntry,
    PreviewProjection,
    QueueProjection,
    RuntimeProjection,
    WebUIProjection,
)
from src.gui.app_state_v2 import AppStateV2


class AppStateProjectionSink:
    """Single writer adapter from runtime projections into AppStateV2."""

    def __init__(
        self,
        app_state: AppStateV2 | None,
        *,
        dispatcher: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._app_state = app_state
        self._dispatcher = dispatcher
        self._lock = threading.RLock()
        self._surface_revisions: dict[str, int] = {}
        self._applied_counts: dict[str, int] = {}
        self._skipped_counts: dict[str, int] = {}

    def set_app_state(self, app_state: AppStateV2 | None) -> None:
        self._app_state = app_state

    def get_metrics_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "surface_revisions": dict(self._surface_revisions),
                "applied_counts": dict(self._applied_counts),
                "skipped_counts": dict(self._skipped_counts),
            }

    def apply_runtime_projection(self, projection: RuntimeProjection) -> None:
        self._apply(
            "runtime",
            projection.revision,
            lambda: self._apply_runtime(projection),
        )

    def apply_queue_projection(self, projection: QueueProjection) -> None:
        self._apply(
            "queue",
            projection.revision,
            lambda: self._apply_queue(projection),
        )

    def apply_history_projection(self, projection: HistoryProjection) -> None:
        self._apply(
            "history",
            projection.revision,
            lambda: self._apply_history(projection),
        )

    def apply_preview_projection(self, projection: PreviewProjection) -> None:
        self._apply(
            "preview",
            projection.revision,
            lambda: self._apply_preview(projection),
        )

    def apply_webui_projection(self, projection: WebUIProjection) -> None:
        self._apply(
            "webui",
            projection.revision,
            lambda: self._apply_webui(projection),
        )

    def append_operator_log(self, entry: OperatorLogEntry) -> None:
        self._apply(
            "operator_log",
            entry.revision,
            lambda: self._append_operator_log(entry),
        )

    def _apply(self, surface: str, revision: int, fn: Callable[[], None]) -> None:
        def _run() -> None:
            with self._lock:
                latest = self._surface_revisions.get(surface, 0)
                if revision <= latest:
                    self._skipped_counts[surface] = self._skipped_counts.get(surface, 0) + 1
                    return
                self._surface_revisions[surface] = revision
                self._applied_counts[surface] = self._applied_counts.get(surface, 0) + 1
            fn()

        dispatcher = self._dispatcher
        if callable(dispatcher):
            dispatcher(_run)
            return
        _run()

    def _apply_runtime(self, projection: RuntimeProjection) -> None:
        app_state = self._app_state
        if app_state is None:
            return
        if projection.running_job is not UNSET:
            app_state.set_running_job(projection.running_job)  # type: ignore[arg-type]
        if projection.runtime_status is not UNSET:
            app_state.set_runtime_status(projection.runtime_status)  # type: ignore[arg-type]
        if projection.queue_status is not UNSET:
            app_state.set_queue_status(str(projection.queue_status))
        if projection.webui_state is not UNSET:
            app_state.set_webui_state(str(projection.webui_state))
        if projection.last_error is not UNSET:
            app_state.set_last_error(projection.last_error)  # type: ignore[arg-type]

    def _apply_queue(self, projection: QueueProjection) -> None:
        app_state = self._app_state
        if app_state is None:
            return
        app_state.set_queue_items(list(projection.queue_items))
        app_state.set_queue_jobs(list(projection.queue_jobs))

    def _apply_history(self, projection: HistoryProjection) -> None:
        app_state = self._app_state
        if app_state is None:
            return
        app_state.set_history_items(list(projection.history_items))

    def _apply_preview(self, projection: PreviewProjection) -> None:
        app_state = self._app_state
        if app_state is None:
            return
        app_state.set_preview_jobs(list(projection.preview_jobs))

    def _apply_webui(self, projection: WebUIProjection) -> None:
        app_state = self._app_state
        if app_state is None:
            return
        app_state.set_resources(projection.resources)

    def _append_operator_log(self, entry: OperatorLogEntry) -> None:
        app_state = self._app_state
        if app_state is None:
            return
        app_state.append_operator_log_line(entry.line)

