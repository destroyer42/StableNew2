from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import src.main as main_module
from src.gui import site_connection_dialog


class _FakeRoot:
    def __init__(self) -> None:
        self.after_calls: list[tuple[int, object]] = []

    def after(self, delay_ms: int, callback) -> None:
        self.after_calls.append((int(delay_ms), callback))

    def mainloop(self) -> None:
        return None


class _FakeWindow:
    def __init__(self) -> None:
        self.exit_handler = None
        self.header_zone = object()

    def set_graceful_exit_handler(self, handler) -> None:
        self.exit_handler = handler

    def schedule_auto_exit(self, _seconds: float) -> None:
        return None


class _FakeSingleInstanceLock:
    def __init__(self) -> None:
        self._acquired = False

    def acquire(self) -> bool:
        self._acquired = True
        return True

    def release(self) -> None:
        self._acquired = False

    def is_acquired(self) -> bool:
        return self._acquired


def test_main_bootstraps_live_app_in_threaded_mode(monkeypatch) -> None:
    fake_root = _FakeRoot()
    fake_window = _FakeWindow()
    fake_controller = object()
    captured: dict[str, object] = {}
    emergency_callbacks = []
    install_site_control = Mock()

    monkeypatch.setattr(main_module, "tk", SimpleNamespace(Tk=lambda: fake_root))
    monkeypatch.setattr(main_module, "messagebox", None)
    monkeypatch.setattr(main_module, "setup_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "SingleInstanceLock", _FakeSingleInstanceLock)
    monkeypatch.setattr(main_module, "_register_emergency_cleanup", lambda _window: None)
    monkeypatch.setattr(main_module, "_async_bootstrap_webui", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "graceful_exit", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.atexit, "register", emergency_callbacks.append)
    monkeypatch.setattr(
        site_connection_dialog, "install_site_connection_control", install_site_control
    )

    def _fake_build_v2_app(**kwargs):
        captured.update(kwargs)
        return fake_root, object(), fake_controller, fake_window

    monkeypatch.setattr(main_module, "build_v2_app", _fake_build_v2_app)
    monkeypatch.delenv("STABLENEW_AUTO_EXIT_SECONDS", raising=False)

    main_module.main()

    assert captured["threaded"] is True
    assert captured["root"] is fake_root
    assert emergency_callbacks == [main_module._emergency_comfy_cleanup]
    if sys.platform == "win32":
        install_site_control.assert_called_once_with(
            fake_root, fake_controller, fake_window.header_zone
        )
    else:
        install_site_control.assert_not_called()
