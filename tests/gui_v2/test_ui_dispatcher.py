from __future__ import annotations

import threading

from src.gui.ui_dispatcher import ImmediateUiDispatcher, TkUiDispatcher


class _FakeRoot:
    def __init__(self) -> None:
        self.calls: list[tuple[int, object]] = []
        self.after_threads: list[int] = []

    def after(self, delay_ms: int, fn: object) -> None:
        self.after_threads.append(threading.get_ident())
        self.calls.append((delay_ms, fn))


def test_tk_dispatcher_queues_via_gui_invoker_pump() -> None:
    root = _FakeRoot()
    dispatcher = TkUiDispatcher(root=root)
    state = {"ran": False}

    def _task() -> None:
        state["ran"] = True

    dispatcher.invoke(_task)

    assert len(root.calls) == 1
    delay, fn = root.calls[0]
    assert delay == 15
    assert callable(fn)
    assert state["ran"] is False

    fn()

    assert state["ran"] is True


def test_tk_dispatcher_background_invoke_does_not_touch_tk_from_worker_thread() -> None:
    root = _FakeRoot()
    dispatcher = TkUiDispatcher(root=root)
    main_thread_id = threading.get_ident()
    state = {"ran": False}

    def _enqueue() -> None:
        dispatcher.invoke(lambda: state.__setitem__("ran", True))

    worker = threading.Thread(target=_enqueue)
    worker.start()
    worker.join()

    assert root.after_threads == [main_thread_id]
    assert len(root.calls) == 1
    _, pump = root.calls[0]
    pump()
    assert state["ran"] is True


def test_immediate_dispatcher_runs_synchronously() -> None:
    dispatcher = ImmediateUiDispatcher()
    state = {"ran": False}

    dispatcher.invoke(lambda: state.__setitem__("ran", True))

    assert state["ran"] is True
