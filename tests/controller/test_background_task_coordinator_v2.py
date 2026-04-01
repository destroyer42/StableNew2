from __future__ import annotations

import threading

from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)


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


def test_background_task_coordinator_latest_wins_per_key() -> None:
    registry = _ThreadRegistryStub()
    coordinator = BackgroundTaskCoordinator(
        dispatcher=lambda fn: fn(),
        thread_registry=registry,  # type: ignore[arg-type]
    )
    first_started = threading.Event()
    release_first = threading.Event()
    results: list[str] = []

    def first() -> str:
        first_started.set()
        release_first.wait(timeout=2.0)
        return "first"

    def second() -> str:
        return "second"

    coordinator.submit("preview", first, on_result=results.append, name="first")
    assert first_started.wait(timeout=2.0)
    coordinator.submit("preview", second, on_result=results.append, name="second")
    release_first.set()

    for thread in registry.threads:
        thread.join(timeout=2.0)

    assert results == ["second"]
    metrics = coordinator.get_metrics_snapshot()
    assert metrics["stale_dropped"] >= 1


def test_background_task_coordinator_runs_inline_for_deterministic_callers() -> None:
    coordinator = BackgroundTaskCoordinator(run_inline=True)
    seen: list[int] = []
    coordinator.submit("queue", lambda: 7, on_result=seen.append)
    assert seen == [7]

