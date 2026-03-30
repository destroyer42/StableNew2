from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

from src.gui.app_state_v2 import AppStateV2


class _FakeInvoker:
    def __init__(self) -> None:
        self.immediate: list[Callable[[], None]] = []
        self.delayed: list[tuple[int, Callable[[], None]]] = []

    def invoke(self, fn: Callable[[], None]) -> None:
        self.immediate.append(fn)

    def invoke_later(self, delay_ms: int, fn: Callable[[], None]) -> None:
        self.delayed.append((delay_ms, fn))


def test_hot_runtime_keys_batch_into_single_delayed_flush() -> None:
    state = AppStateV2()
    invoker = _FakeInvoker()
    state.set_invoker(invoker)
    calls: list[str] = []

    state.subscribe("runtime_status", lambda: calls.append("runtime"))

    state.set_runtime_status(object())  # type: ignore[arg-type]
    state.set_runtime_status(object())  # type: ignore[arg-type]

    assert calls == []
    assert invoker.immediate == []
    assert len(invoker.delayed) == 1
    assert invoker.delayed[0][0] == 75

    _, delayed_flush = invoker.delayed.pop()
    delayed_flush()

    assert calls == ["runtime"]


def test_non_hot_keys_remain_immediate_via_invoker() -> None:
    state = AppStateV2()
    invoker = _FakeInvoker()
    state.set_invoker(invoker)
    calls: list[str] = []

    state.subscribe("prompt", lambda: calls.append("prompt"))
    state.set_prompt("new prompt")

    assert calls == []
    assert len(invoker.immediate) == 1
    assert invoker.delayed == []

    invoker.immediate.pop()()

    assert calls == ["prompt"]


def test_flush_now_drains_pending_hot_key_notifications() -> None:
    state = AppStateV2()
    invoker = _FakeInvoker()
    state.set_invoker(invoker)
    calls: list[str] = []

    state.subscribe("operator_log", lambda: calls.append("log"))
    state.append_operator_log_line("first")
    state.append_operator_log_line("second")

    assert calls == []
    assert len(invoker.delayed) == 1

    state.flush_now()

    assert calls == ["log"]


def test_queue_jobs_batches_like_other_hot_runtime_keys() -> None:
    state = AppStateV2()
    invoker = _FakeInvoker()
    state.set_invoker(invoker)
    calls: list[str] = []

    state.subscribe("queue_jobs", lambda: calls.append("queue_jobs"))

    state.set_queue_jobs([SimpleNamespace(job_id="job-1")])
    state.set_queue_jobs([
        SimpleNamespace(job_id="job-1"),
        SimpleNamespace(job_id="job-2"),
    ])

    assert calls == []
    assert invoker.immediate == []
    assert len(invoker.delayed) == 1

    _, delayed_flush = invoker.delayed.pop()
    delayed_flush()

    assert calls == ["queue_jobs"]
