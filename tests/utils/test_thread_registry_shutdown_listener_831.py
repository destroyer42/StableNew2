"""PR-GUI-RELIABILITY-831: a worker can hear the exit request before its thread is joined."""

from __future__ import annotations

import threading
import time

from src.utils.thread_registry import ThreadRegistry


def _fresh() -> ThreadRegistry:
    registry = ThreadRegistry()
    with registry._registry_lock:
        registry._threads.clear()
        registry._shutdown_listeners.clear()
        registry._shutdown_requested = False
    return registry


def test_shutdown_listener_runs_before_the_join_and_lets_the_worker_exit() -> None:
    registry = _fresh()
    stop = threading.Event()
    registry.add_shutdown_listener(stop.set)
    worker = registry.spawn(target=lambda: stop.wait(30), name="listener-worker")
    started = time.monotonic()

    stats = registry.shutdown_all(timeout=5.0)

    assert not worker.is_alive()
    assert stats["timeout"] == 0 and time.monotonic() - started < 2.0


def test_removed_listener_is_not_called_and_a_failing_listener_does_not_stop_shutdown() -> None:
    registry = _fresh()
    called: list[str] = []
    remove = registry.add_shutdown_listener(lambda: called.append("removed"))
    remove()
    remove()  # idempotent
    registry.add_shutdown_listener(lambda: 1 / 0)
    registry.add_shutdown_listener(lambda: called.append("after-failure"))

    registry.shutdown_all(timeout=1.0)

    assert called == ["after-failure"]
