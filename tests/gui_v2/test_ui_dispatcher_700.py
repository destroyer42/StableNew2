from __future__ import annotations

import threading

from src.controller.ports.ui_dispatcher import ImmediateUiDispatcher
from src.gui.app_state_v2 import AppStateV2
from src.gui.gui_invoker import GuiInvoker, TkInvoker
from src.gui.ui_dispatcher import TkUiDispatcher


class _FakeRoot:
    def __init__(self) -> None:
        self.pending: list[tuple[int, object]] = []

    def after(self, delay_ms: int, callback: object) -> str:
        self.pending.append((delay_ms, callback))
        return str(len(self.pending))


def test_gui_invoker_alias_remains_backward_compatible() -> None:
    assert GuiInvoker is TkInvoker


def test_immediate_dispatcher_runs_all_contract_methods_inline() -> None:
    dispatcher = ImmediateUiDispatcher()
    calls: list[str] = []

    dispatcher.schedule(lambda: calls.append("schedule"))
    dispatcher.invoke_later(10, lambda: calls.append("later"))
    dispatcher.run_on_ui_thread(lambda: calls.append("ui"))
    dispatcher.invoke(lambda: calls.append("legacy"))

    assert calls == ["schedule", "later", "ui", "legacy"]


def test_tk_invoker_schedule_keeps_queued_pump_semantics() -> None:
    root = _FakeRoot()
    invoker = TkInvoker(root)  # type: ignore[arg-type]
    calls: list[str] = []

    invoker.schedule(lambda: calls.append("queued"))

    assert calls == []
    _, pump = root.pending.pop(0)
    pump()  # type: ignore[operator]

    assert calls == ["queued"]
    invoker.dispose()


def test_tk_invoker_run_on_ui_thread_is_inline_on_owner_thread() -> None:
    root = _FakeRoot()
    invoker = TkInvoker(root)  # type: ignore[arg-type]
    calls: list[str] = []

    invoker.run_on_ui_thread(lambda: calls.append("inline"))

    assert calls == ["inline"]
    invoker.dispose()


def test_tk_invoker_run_on_ui_thread_queues_from_worker_thread() -> None:
    root = _FakeRoot()
    invoker = TkInvoker(root)  # type: ignore[arg-type]
    calls: list[str] = []

    worker = threading.Thread(target=lambda: invoker.run_on_ui_thread(lambda: calls.append("w")))
    worker.start()
    worker.join()

    assert calls == []
    _, pump = root.pending.pop(0)
    pump()  # type: ignore[operator]
    assert calls == ["w"]
    invoker.dispose()


def test_tk_ui_dispatcher_exposes_neutral_and_legacy_names() -> None:
    root = _FakeRoot()
    dispatcher = TkUiDispatcher(root=root)
    calls: list[str] = []

    dispatcher.schedule(lambda: calls.append("schedule"))
    dispatcher.invoke(lambda: calls.append("invoke"))
    dispatcher.run_on_ui_thread(lambda: calls.append("inline"))

    assert calls == ["inline"]
    _, pump = root.pending.pop(0)
    pump()  # type: ignore[operator]
    assert calls == ["inline", "schedule", "invoke"]


def test_app_state_accepts_neutral_dispatcher_and_legacy_invoke_only_fakes() -> None:
    state = AppStateV2()
    scheduled: list[object] = []

    class _Neutral:
        def schedule(self, fn):  # noqa: ANN001
            scheduled.append(fn)

        def invoke_later(self, delay_ms, fn):  # noqa: ANN001
            scheduled.append(fn)

        def run_on_ui_thread(self, fn):  # noqa: ANN001
            fn()

    state.set_invoker(_Neutral())
    state.subscribe("prompt", lambda: None)
    state.set_prompt("x")

    assert len(scheduled) == 1
