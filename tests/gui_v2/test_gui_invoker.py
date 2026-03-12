from __future__ import annotations

import threading

from src.gui.gui_invoker import GuiInvoker


class _FakeRoot:
    def __init__(self) -> None:
        self.calls: list[tuple[int, object]] = []

    def after(self, delay_ms: int, fn: object) -> None:
        self.calls.append((delay_ms, fn))


def test_gui_invoker_queues_background_calls_without_touching_tk_immediately() -> None:
    root = _FakeRoot()
    invoker = GuiInvoker(root)
    state = {"ran": False}

    assert len(root.calls) == 1
    initial_delay, pump = root.calls[0]
    assert initial_delay == 15
    assert callable(pump)

    def _enqueue() -> None:
        invoker.invoke(lambda: state.__setitem__("ran", True))

    worker = threading.Thread(target=_enqueue)
    worker.start()
    worker.join()

    assert state["ran"] is False
    assert len(root.calls) == 1

    pump()

    assert state["ran"] is True
    assert len(root.calls) == 2


def test_gui_invoker_dispose_prevents_future_callbacks() -> None:
    root = _FakeRoot()
    invoker = GuiInvoker(root)
    state = {"ran": False}

    invoker.invoke(lambda: state.__setitem__("ran", True))
    invoker.dispose()

    _, pump = root.calls[0]
    pump()

    assert state["ran"] is False
