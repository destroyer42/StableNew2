import socket
from types import SimpleNamespace
from unittest import mock

import pytest

import src.main as main_module
from src.runtime_host import RuntimeHostLaunchError


@pytest.fixture
def unique_lock_port(monkeypatch):
    """Use a high, likely-unused port to avoid colliding with a real instance."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    monkeypatch.setattr(main_module, "_INSTANCE_PORT", port)
    return port


def test_single_instance_lock_allows_first_and_blocks_second(unique_lock_port):
    first = main_module._acquire_single_instance_lock()
    try:
        assert first is not None
        # With the port still held, a second call should fail
        second = main_module._acquire_single_instance_lock()
        assert second is None
    finally:
        if first is not None:
            first.close()


def test_main_reports_runtime_host_launch_failure_and_releases_lock(monkeypatch):
    class DummyLock:
        def __init__(self) -> None:
            self._acquired = False
            self.released = False

        def acquire(self) -> bool:
            self._acquired = True
            return True

        def is_acquired(self) -> bool:
            return self._acquired

        def release(self) -> None:
            self.released = True
            self._acquired = False

    class DummyRoot:
        def __init__(self) -> None:
            self.destroyed = False

        def destroy(self) -> None:
            self.destroyed = True

    runtime_root = DummyRoot()
    lock = DummyLock()
    showerror = mock.Mock()
    build_kwargs: dict[str, object] = {}

    def _raise_launch_error(**kwargs):
        build_kwargs.update(kwargs)
        raise RuntimeHostLaunchError("runtime host command 'handshake' timed out after 1.00s")

    monkeypatch.setattr(main_module, "setup_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "SingleInstanceLock", lambda: lock)
    monkeypatch.setattr(main_module, "tk", SimpleNamespace(Tk=lambda: runtime_root))
    monkeypatch.setattr(main_module, "messagebox", SimpleNamespace(showerror=showerror))
    monkeypatch.setattr(main_module, "build_v2_app", _raise_launch_error)

    main_module.main()

    assert build_kwargs.get("root") is runtime_root
    assert build_kwargs.get("launch_runtime_host") is True
    assert runtime_root.destroyed is True
    assert lock.released is True
    showerror.assert_called_once()


def test_main_does_not_schedule_gui_owned_runtime_bootstraps(monkeypatch):
    class DummyLock:
        def __init__(self) -> None:
            self._acquired = False

        def acquire(self) -> bool:
            self._acquired = True
            return True

        def is_acquired(self) -> bool:
            return self._acquired

        def release(self) -> None:
            self._acquired = False

    class DummyRoot:
        def __init__(self) -> None:
            self.after_calls: list[int] = []

        def after(self, delay, callback):
            self.after_calls.append(int(delay))

        def mainloop(self) -> None:
            return None

    class DummyWindow:
        def __init__(self) -> None:
            self.webui_process_manager = None
            self.comfy_process_manager = None
            self.exit_handler = None

        def set_graceful_exit_handler(self, handler):
            self.exit_handler = handler

    runtime_root = DummyRoot()
    lock = DummyLock()
    async_webui = mock.Mock()
    async_comfy = mock.Mock()

    monkeypatch.setattr(main_module, "setup_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "SingleInstanceLock", lambda: lock)
    monkeypatch.setattr(main_module, "tk", SimpleNamespace(Tk=lambda: runtime_root))
    monkeypatch.setattr(main_module, "messagebox", SimpleNamespace(showerror=mock.Mock()))
    monkeypatch.setattr(
        main_module,
        "build_v2_app",
        lambda **kwargs: (runtime_root, SimpleNamespace(), SimpleNamespace(), DummyWindow()),
    )
    monkeypatch.setattr(main_module, "_async_bootstrap_webui", async_webui)
    monkeypatch.setattr(main_module, "_async_bootstrap_comfy", async_comfy)

    main_module.main()

    async_webui.assert_not_called()
    async_comfy.assert_not_called()
