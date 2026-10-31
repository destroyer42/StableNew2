"""Projection plumbing shared by both toolkit views: the real sink, ``AppStateV2`` and a toolkit dispatcher.

Nothing here opens a repository or starts a runner; a worker thread hands immutable projections to the real
``AppStateProjectionSink`` exactly as the application's controller does.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from src.contracts import HistoryProjection, QueueProjection, RuntimeProjection
from src.controller.ports.ui_dispatcher import UiDispatcher
from src.gui.app_state_projection_sink import AppStateProjectionSink
from src.gui.app_state_v2 import AppStateV2
from tools.qualification.gui_port_742.fixture import history_entries, queue_summaries

STATUS_PREFIX = "synthetic-status-"


class Plumbing:
    """Owns the AppState + sink; the view supplies UI-thread render callbacks."""

    def __init__(
        self,
        dispatcher: UiDispatcher,
        *,
        on_history: Callable[[], None],
        on_queue: Callable[[], None],
        on_status: Callable[[], None],
        count: int = 500,
    ) -> None:
        self.count = count
        self.ui_thread = threading.get_ident()
        self.state = AppStateV2()
        self.state.set_invoker(dispatcher)
        self.sink = AppStateProjectionSink(self.state)
        self._listeners = {
            "history_items": on_history,
            "queue_jobs": on_queue,
            "queue_status": on_status,
        }
        for key, listener in self._listeners.items():
            self.state.subscribe(key, listener)
        self.closed = False

    def publish(
        self,
        data_revision: int,
        *,
        drop: frozenset[str] = frozenset(),
        sink_revision: int | None = None,
    ):
        """Apply one history+queue projection; ``sink_revision`` defaults to ``data_revision + 1``."""

        revision = data_revision + 1 if sink_revision is None else sink_revision
        jobs = queue_summaries(self.count, data_revision)
        self.sink.apply_queue_projection(
            QueueProjection(
                revision=revision, queue_items=tuple(j.job_id for j in jobs), queue_jobs=jobs
            )
        )
        self.sink.apply_history_projection(
            HistoryProjection(
                revision=revision, history_items=history_entries(self.count, data_revision, drop)
            )
        )

    def publish_status(self, index: int, *, revision: int) -> None:
        self.sink.apply_runtime_projection(
            RuntimeProjection(revision=revision, queue_status=f"{STATUS_PREFIX}{index:03d}")
        )

    def close(self) -> None:
        """Unsubscribe and stop delivery; a late projection after this cannot reach a destroyed view."""

        if self.closed:
            return
        self.closed = True
        for key, listener in self._listeners.items():
            self.state.unsubscribe(key, listener)
        self.state.disable_notifications()
