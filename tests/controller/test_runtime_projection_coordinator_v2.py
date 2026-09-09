from __future__ import annotations

import threading
from types import SimpleNamespace

from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.controller.app_controller_services.runtime_projection_coordinator import (
    RuntimeProjectionCoordinator,
)
from src.gui.app_state_projection_sink import AppStateProjectionSink
from src.gui.app_state_v2 import AppStateV2


class _ThreadRegistryStub:
    def __init__(self) -> None:
        self.threads: list[threading.Thread] = []

    def spawn(self, *, target, args=(), kwargs=None, name=None, daemon=False, purpose=None):
        thread = threading.Thread(
            target=target,
            args=args,
            kwargs=kwargs or {},
            name=name,
            daemon=daemon,
        )
        self.threads.append(thread)
        thread.start()
        return thread


def _summary(job_id: str, status: str):
    return SimpleNamespace(job_id=job_id, status=status)


def _signature(values) -> list[tuple[str, str]]:
    return [(str(value.job_id), str(value.status).upper()) for value in values]


def test_queue_projection_latest_request_wins_across_rapid_lifecycle_transitions() -> None:
    app_state = AppStateV2()
    sink = AppStateProjectionSink(app_state, dispatcher=lambda fn: fn())
    registry = _ThreadRegistryStub()
    tasks = BackgroundTaskCoordinator(
        dispatcher=lambda fn: fn(),
        thread_registry=registry,  # type: ignore[arg-type]
    )
    state: list[object] = []
    first_started = threading.Event()
    release_first = threading.Event()
    block_next = False

    def build_projection():
        nonlocal block_next
        snapshot = list(state)
        if block_next:
            block_next = False
            first_started.set()
            release_first.wait(timeout=2.0)
        return ([value.job_id for value in snapshot], snapshot)

    coordinator = RuntimeProjectionCoordinator(
        sink=sink,
        background_tasks=tasks,
        build_queue_projection=build_projection,
        load_history_entries=lambda _limit: [],
        summarize_running_job=lambda _job: None,
    )

    transitions = [
        [_summary("A", "QUEUED")],
        [_summary("A", "QUEUED"), _summary("B", "QUEUED")],
        [_summary("A", "RUNNING"), _summary("B", "QUEUED")],
        [_summary("B", "QUEUED")],
        [],
    ]
    for previous, latest in zip([[]] + transitions[:-1], transitions, strict=True):
        state[:] = previous
        block_next = True
        first_started.clear()
        release_first.clear()
        coordinator.publish_queue_refresh()
        assert first_started.wait(timeout=2.0)
        state[:] = latest
        coordinator.publish_queue_refresh()
        release_first.set()
        for thread in registry.threads:
            thread.join(timeout=2.0)
        assert _signature(app_state.queue_jobs) == _signature(latest)

    metrics = tasks.get_metrics_snapshot()
    assert metrics["stale_dropped"] == len(transitions)
    assert sink.get_metrics_snapshot()["surface_revisions"]["queue"] == len(transitions) * 2
