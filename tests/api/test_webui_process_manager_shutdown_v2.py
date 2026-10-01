from __future__ import annotations

import pytest

from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager


class FakeProcess:
    pid = 424242

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
    # Never inspect a real OS process tree for the fake PID.
    monkeypatch.setattr(WebUIProcessManager, "_owned_descendants", lambda self, pid: [])
    return None


def _make_manager() -> WebUIProcessManager:
    config = WebUIProcessConfig(command=["echo"])
    return WebUIProcessManager(config)


def _adopt_as_owned(manager: WebUIProcessManager, process: FakeProcess) -> None:
    """Model the state ``start()`` establishes for a StableNew-launched process."""
    manager._process = process
    manager._pid = process.pid
    manager._owns_process = True
    assert manager.owns_process


def test_stop_webui_with_no_process() -> None:
    manager = _make_manager()
    manager._process = None
    assert manager.stop_webui()


def test_stop_webui_graceful_path() -> None:
    manager = _make_manager()
    fake = FakeProcess(graceful=True)
    _adopt_as_owned(manager, fake)

    assert manager.stop_webui(grace_seconds=0.1)
    assert fake.terminate_called == 1
    assert fake.kill_called == 0

    # Idempotent: second call uses cleared process
    assert manager.stop_webui()


def test_stop_webui_forced_kill_when_unresponsive() -> None:
    manager = _make_manager()
    fake = FakeProcess(graceful=False)
    _adopt_as_owned(manager, fake)

    assert manager.stop_webui(grace_seconds=0.1)
    assert fake.kill_called == 1
    assert fake.terminate_called == 1

    # Idempotency check
    assert manager.stop_webui()


@pytest.mark.parametrize("graceful", [True, False])
def test_stop_webui_never_mutates_unowned_process(graceful: bool) -> None:
    manager = _make_manager()
    fake = FakeProcess(graceful=graceful)
    manager._process = fake  # injected, but never launched/owned by this manager
    assert not manager.owns_process

    assert manager.stop_webui(grace_seconds=0.1)
    assert fake.terminate_called == 0
    assert fake.kill_called == 0
    assert manager._process is fake


def test_stop_webui_refuses_when_pid_does_not_match_launch_session() -> None:
    manager = _make_manager()
    fake = FakeProcess(graceful=False)
    _adopt_as_owned(manager, fake)
    manager._pid = fake.pid + 1  # process object no longer the launched one

    assert manager.stop_webui(grace_seconds=0.1)
    assert fake.terminate_called == 0
    assert fake.kill_called == 0
