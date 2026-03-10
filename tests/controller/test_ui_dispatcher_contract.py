from __future__ import annotations

from src.controller.app_controller import AppController


class _RootStub:
    def __init__(self) -> None:
        self.calls: list[tuple[int, object]] = []

    def after(self, delay_ms: int, fn: object) -> None:
        self.calls.append((delay_ms, fn))


def _build_controller_stub(root: object | None) -> AppController:
    controller = AppController.__new__(AppController)
    controller.main_window = type("MW", (), {"root": root})() if root is not None else None
    controller._ui_scheduler = None
    controller._ui_thread_id = 0
    return controller


def test_ui_dispatch_later_uses_root_after_for_delays() -> None:
    root = _RootStub()
    controller = _build_controller_stub(root)
    called = {"ran": False}

    controller._ui_dispatch_later(125, lambda: called.__setitem__("ran", True))

    assert len(root.calls) == 1
    delay, fn = root.calls[0]
    assert delay == 125
    assert callable(fn)
    assert called["ran"] is False


def test_ui_dispatch_later_falls_back_without_root() -> None:
    controller = _build_controller_stub(None)
    called = {"ran": False}

    controller._ui_dispatch_later(50, lambda: called.__setitem__("ran", True))

    assert called["ran"] is True
