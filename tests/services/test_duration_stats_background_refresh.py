"""Duration stats are recomputed off the UI thread and never expose a half-built cache."""

from __future__ import annotations

import threading
from datetime import datetime
from types import SimpleNamespace

from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.controller.app_controller_services.runtime_projection_coordinator import (
    RuntimeProjectionCoordinator,
)
from src.gui.app_state_projection_sink import AppStateProjectionSink
from src.gui.app_state_v2 import AppStateV2
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from src.services.duration_stats_service import DurationStatsService


def _entry(job_id: str, duration_ms: int) -> JobHistoryEntry:
    return JobHistoryEntry(
        job_id=job_id,
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        duration_ms=duration_ms,
        snapshot={"normalized_job": {"stage_chain": ["txt2img"]}},
    )


class _Store:
    def __init__(self, entries, gate: threading.Event | None = None) -> None:
        self.entries = entries
        self.gate = gate
        self.reading = threading.Event()

    def list_jobs(self, status=None, limit=50, offset=0):
        self.reading.set()
        if self.gate is not None:
            self.gate.wait(timeout=5.0)
        return self.entries[:limit]


def test_readers_keep_the_previous_stats_while_a_refresh_is_in_progress() -> None:
    gate = threading.Event()
    store = _Store([_entry(f"j{i}", 10_000) for i in range(5)])
    service = DurationStatsService(store, min_samples_for_stats=3)
    service.refresh()
    assert service.get_estimate_for_chain(["txt2img"]) == 10.0

    store.entries = [_entry(f"k{i}", 20_000) for i in range(5)]
    store.gate = gate
    store.reading.clear()
    worker = threading.Thread(target=service.refresh)
    worker.start()
    assert store.reading.wait(timeout=2.0)

    assert service.get_estimate_for_chain(["txt2img"]) == 10.0  # old cache still served mid-refresh

    gate.set()
    worker.join(timeout=5.0)
    assert service.get_estimate_for_chain(["txt2img"]) == 20.0


def _coordinator(*, run_inline: bool = True) -> RuntimeProjectionCoordinator:
    sink = AppStateProjectionSink(AppStateV2(), dispatcher=lambda fn: fn())
    tasks = BackgroundTaskCoordinator(dispatcher=lambda fn: fn(), run_inline=run_inline)
    return RuntimeProjectionCoordinator(
        sink=sink,
        background_tasks=tasks,
        build_queue_projection=lambda: ([], []),
        load_history_entries=lambda _limit: [],
        summarize_running_job=lambda _job: None,
    )


def test_the_coordinator_runs_the_refresh_through_the_background_tasks() -> None:
    store = _Store([_entry(f"j{i}", 8_000) for i in range(5)])
    service = DurationStatsService(store, min_samples_for_stats=3)

    _coordinator().publish_duration_stats_refresh(service)

    assert service.get_estimate_for_chain(["txt2img"]) == 8.0


def test_a_missing_service_is_ignored() -> None:
    _coordinator().publish_duration_stats_refresh(None)


def test_a_failing_refresh_is_reported_not_raised() -> None:
    errors: list[Exception] = []
    service = SimpleNamespace(
        refresh=lambda: (_ for _ in ()).throw(RuntimeError("history unreadable"))
    )

    _coordinator().publish_duration_stats_refresh(service, on_error=errors.append)

    assert [str(error) for error in errors] == ["history unreadable"]


def test_refresh_does_not_run_on_the_calling_thread_when_threaded() -> None:
    gate = threading.Event()
    ran_on: list[str] = []
    started = threading.Event()

    def refresh() -> None:
        ran_on.append(threading.current_thread().name)
        started.set()
        gate.wait(timeout=5.0)

    coordinator = _coordinator(run_inline=False)
    coordinator.publish_duration_stats_refresh(
        SimpleNamespace(refresh=refresh)
    )  # returns without waiting

    assert started.wait(timeout=2.0)
    assert ran_on and ran_on[0] != threading.current_thread().name
    gate.set()
