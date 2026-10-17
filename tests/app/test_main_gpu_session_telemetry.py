from __future__ import annotations

from types import SimpleNamespace

import src.main as main_module


class _LoopRoot:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def after(self, _delay_ms: int, _callback) -> None:
        return None

    def mainloop(self) -> None:
        self._events.append("mainloop")


class _FakeWindow:
    def set_graceful_exit_handler(self, _handler) -> None:
        return None

    def schedule_auto_exit(self, _seconds: float) -> None:
        return None


class _FakeSingleInstanceLock:
    def acquire(self) -> bool:
        return True

    def release(self) -> None:
        return None

    def is_acquired(self) -> bool:
        return False


def test_main_starts_the_gpu_session_recorder_before_the_loop_and_stops_it_after(
    monkeypatch,
) -> None:
    events: list[str] = []
    root = _LoopRoot(events)

    monkeypatch.setattr(main_module, "tk", SimpleNamespace(Tk=lambda: root))
    monkeypatch.setattr(main_module, "messagebox", None)
    monkeypatch.setattr(main_module, "setup_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "SingleInstanceLock", _FakeSingleInstanceLock)
    monkeypatch.setattr(main_module, "_register_emergency_cleanup", lambda _window: None)
    monkeypatch.setattr(main_module, "_async_bootstrap_webui", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "_async_bootstrap_comfy", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "graceful_exit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        main_module, "build_v2_app", lambda **_kwargs: (root, object(), object(), _FakeWindow())
    )
    monkeypatch.setattr(main_module, "start_gpu_session_telemetry", lambda: events.append("start"))
    monkeypatch.setattr(
        main_module,
        "stop_gpu_session_telemetry",
        lambda outcome="app_exit": events.append(f"stop:{outcome}"),
    )
    monkeypatch.delenv("STABLENEW_AUTO_EXIT_SECONDS", raising=False)

    main_module.main()

    assert events == ["start", "mainloop", "stop:mainloop_exit"]
