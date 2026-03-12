from __future__ import annotations

import threading
import time

from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager


class _FakeRegistry:
    def __init__(self) -> None:
        self.unregistered: list[threading.Thread] = []

    def unregister(self, thread: threading.Thread) -> None:
        self.unregistered.append(thread)


def test_stop_output_capture_unregisters_reader_threads(monkeypatch, tmp_path) -> None:
    manager = WebUIProcessManager(
        WebUIProcessConfig(command=["python", "-c", "print('test')"], working_dir=str(tmp_path))
    )
    registry = _FakeRegistry()
    monkeypatch.setattr("src.utils.thread_registry.get_thread_registry", lambda: registry)

    done = threading.Event()

    def worker() -> None:
        done.wait(timeout=1.0)

    stdout_thread = threading.Thread(target=worker, name="stdout")
    stderr_thread = threading.Thread(target=worker, name="stderr")
    stdout_thread.start()
    stderr_thread.start()
    manager._stdout_thread = stdout_thread
    manager._stderr_thread = stderr_thread
    done.set()

    manager._stop_output_capture()

    assert stdout_thread in registry.unregistered
    assert stderr_thread in registry.unregistered
    assert manager._stdout_thread is None
    assert manager._stderr_thread is None


def test_stop_orphan_monitor_unregisters_thread(monkeypatch, tmp_path) -> None:
    manager = WebUIProcessManager(
        WebUIProcessConfig(command=["python", "-c", "print('test')"], working_dir=str(tmp_path))
    )
    registry = _FakeRegistry()
    monkeypatch.setattr("src.utils.thread_registry.get_thread_registry", lambda: registry)

    stop = threading.Event()

    def worker() -> None:
        while not stop.is_set():
            time.sleep(0.01)

    thread = threading.Thread(target=worker, name="orphan-monitor")
    thread.start()
    manager._orphan_monitor_thread = thread
    manager._orphan_monitor_stop.clear()

    original_join = thread.join

    def join_with_stop(timeout: float | None = None) -> None:
        stop.set()
        original_join(timeout=timeout)

    thread.join = join_with_stop  # type: ignore[assignment]

    manager._stop_orphan_monitor()

    assert thread in registry.unregistered
    assert manager._orphan_monitor_thread is None
