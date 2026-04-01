from __future__ import annotations

from types import SimpleNamespace

import src.main as main_module


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
    captured: dict[str, object] = {}

    monkeypatch.setattr(main_module, "tk", SimpleNamespace(Tk=lambda: fake_root))
    monkeypatch.setattr(main_module, "messagebox", None)
    monkeypatch.setattr(main_module, "setup_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "SingleInstanceLock", _FakeSingleInstanceLock)
    monkeypatch.setattr(main_module, "_register_emergency_cleanup", lambda _window: None)
    monkeypatch.setattr(main_module, "_async_bootstrap_webui", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "_async_bootstrap_comfy", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "graceful_exit", lambda *args, **kwargs: None)

    def _fake_build_v2_app(**kwargs):
        captured.update(kwargs)
        return fake_root, object(), object(), fake_window

    monkeypatch.setattr(main_module, "build_v2_app", _fake_build_v2_app)
    monkeypatch.delenv("STABLENEW_AUTO_EXIT_SECONDS", raising=False)

    main_module.main()

    assert captured["threaded"] is True
    assert captured["root"] is fake_root

