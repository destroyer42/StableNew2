from __future__ import annotations

import pytest

from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager


class FakeProcess:
    def __init__(self, graceful: bool) -> None:
        self.graceful = graceful
        self.terminate_called = 0
        self.kill_called = 0
        self.wait_called = 0
        self._state: int | None = None
        self.poll_calls = 0

    def poll(self) -> int | None:
        self.poll_calls += 1
        if self.graceful and self.poll_calls >= 2:
            self._state = 0
        return self._state

    def terminate(self) -> None:
        self.terminate_called += 1

    def wait(self, timeout: float | None = None) -> int:
        self.wait_called += 1
        self._state = 0
        return 0

    def kill(self) -> None:
        self.kill_called += 1
        self._state = 1


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("src.api.webui_process_manager.time.sleep", lambda *_: None)
    return None


def _make_manager() -> WebUIProcessManager:
    config = WebUIProcessConfig(command=["echo"])
    return WebUIProcessManager(config)


def test_stop_webui_with_no_process() -> None:
    manager = _make_manager()
    manager._process = None
    assert manager.stop_webui()


def test_stop_webui_graceful_path() -> None:
    manager = _make_manager()
    fake = FakeProcess(graceful=True)
    manager._process = fake

    assert manager.stop_webui(grace_seconds=0.1)
    assert fake.terminate_called == 1
    assert fake.kill_called == 0

    # Idempotent: second call uses cleared process
    assert manager.stop_webui()


def test_stop_webui_forced_kill_when_unresponsive() -> None:
    manager = _make_manager()
    fake = FakeProcess(graceful=False)
    manager._process = fake

    assert manager.stop_webui(grace_seconds=0.1)
    assert fake.kill_called == 1
    assert fake.terminate_called == 1

    # Idempotency check
    assert manager.stop_webui()
