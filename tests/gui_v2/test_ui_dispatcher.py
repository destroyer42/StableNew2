from __future__ import annotations

from src.gui.ui_dispatcher import ImmediateUiDispatcher, TkUiDispatcher


class _FakeRoot:
    def __init__(self) -> None:
        self.calls: list[tuple[int, object]] = []

    def after(self, delay_ms: int, fn: object) -> None:
        self.calls.append((delay_ms, fn))


def test_tk_dispatcher_uses_after_zero_delay() -> None:
    root = _FakeRoot()
    dispatcher = TkUiDispatcher(root=root)
    state = {"ran": False}

    def _task() -> None:
        state["ran"] = True

    dispatcher.invoke(_task)

    assert len(root.calls) == 1
    delay, fn = root.calls[0]
    assert delay == 0
    assert callable(fn)
    assert state["ran"] is False


def test_immediate_dispatcher_runs_synchronously() -> None:
    dispatcher = ImmediateUiDispatcher()
    state = {"ran": False}

    dispatcher.invoke(lambda: state.__setitem__("ran", True))

    assert state["ran"] is True
