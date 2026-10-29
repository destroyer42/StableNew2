"""PR-GUI-SEAM-730: one Tk dispatch owner per root and one ordered close path.

The headless cases drive a fake root (no Tk) and fake close collaborators; the ``gui`` cases prove the production
composition path hands one dispatcher instance to the controller scheduler, ``AppStateV2``, the window and its
presentation actions.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk

import pytest

import src.utils.graceful_exit as graceful_exit_module
from src.app_factory import build_v2_app
from src.gui import gui_invoker
from src.gui.main_window_v2 import MainWindowV2
from src.gui.ui_dispatcher import TkUiDispatcher, release_tk_dispatcher, tk_dispatcher_for


class _FakeRoot:
    def __init__(self) -> None:
        self.pending: list[tuple[int, object]] = []

    def after(self, delay_ms: int, callback: object) -> str:
        self.pending.append((delay_ms, callback))
        return str(len(self.pending))

    def pump(self) -> None:
        """Run what is scheduled now once; a live pump reschedules itself for the next pass."""
        due, self.pending = self.pending, []
        for _, callback in due:
            callback()  # type: ignore[operator]


class _FakeWidget:
    """A widget whose Tk root is a fake root, like ``tk.Misc._root()``."""

    def __init__(self, root: _FakeRoot) -> None:
        self._tk_root = root

    def _root(self) -> _FakeRoot:
        return self._tk_root


def test_one_dispatcher_per_root_for_roots_and_widgets() -> None:
    root, other = _FakeRoot(), _FakeRoot()

    owner = tk_dispatcher_for(root)

    assert tk_dispatcher_for(root) is owner
    assert tk_dispatcher_for(_FakeWidget(root)) is owner
    assert tk_dispatcher_for(other) is not owner
    # One owner means one pump scheduled on the root.
    assert len(root.pending) == 1
    owner.dispose()
    other_owner = tk_dispatcher_for(other)
    other_owner.dispose()


def test_dispose_fences_queued_and_later_deliveries() -> None:
    root = _FakeRoot()
    dispatcher = tk_dispatcher_for(root)
    calls: list[str] = []

    dispatcher.schedule(lambda: calls.append("queued-before-dispose"))
    dispatcher.dispose()
    dispatcher.dispose()  # idempotent
    dispatcher.schedule(lambda: calls.append("schedule-after"))
    dispatcher.invoke(lambda: calls.append("invoke-after"))
    dispatcher.invoke_later(0, lambda: calls.append("later-after"))
    dispatcher.run_on_ui_thread(lambda: calls.append("ui-after"))
    root.pump()

    assert calls == []
    assert dispatcher.disposed is True
    assert root.pending == []  # the pump did not reschedule itself


def test_dispose_blocks_delivery_from_a_worker_thread() -> None:
    root = _FakeRoot()
    dispatcher = tk_dispatcher_for(root)
    calls: list[str] = []
    dispatcher.dispose()

    worker = threading.Thread(target=lambda: dispatcher.schedule(lambda: calls.append("late")))
    worker.start()
    worker.join()
    root.pump()

    assert calls == []


def test_dispose_cancels_pending_delayed_callbacks() -> None:
    root = _FakeRoot()
    dispatcher = tk_dispatcher_for(root)
    fired = threading.Event()

    dispatcher.invoke_later(60_000, fired.set)
    dispatcher.dispose()
    root.pump()

    assert not fired.is_set()


def test_a_disposed_dispatcher_stays_registered_so_a_closing_root_is_never_given_a_pump() -> None:
    root = _FakeRoot()
    owner = tk_dispatcher_for(root)
    owner.dispose()

    assert tk_dispatcher_for(root) is owner
    assert tk_dispatcher_for(_FakeWidget(root)) is owner


def test_release_forgets_the_dispatcher_for_standalone_reuse() -> None:
    root = _FakeRoot()
    first = tk_dispatcher_for(root)

    release_tk_dispatcher(root)
    release_tk_dispatcher(root)  # releasing twice is harmless

    assert first.disposed is True
    second = tk_dispatcher_for(root)
    assert second is not first
    assert second.disposed is False
    second.dispose()


def test_tk_dispatcher_keeps_the_ui_dispatcher_contract() -> None:
    root = _FakeRoot()
    dispatcher = TkUiDispatcher(root)
    calls: list[str] = []

    dispatcher.schedule(lambda: calls.append("schedule"))
    dispatcher.invoke(lambda: calls.append("invoke"))
    dispatcher.run_on_ui_thread(lambda: calls.append("inline"))
    root.pump()

    assert calls == ["inline", "schedule", "invoke"]
    dispatcher.dispose()


class _Recorder:
    def __init__(self) -> None:
        self.events: list[str] = []


def _run_graceful_exit(monkeypatch, recorder: _Recorder, **kwargs) -> None:
    class _Exit(BaseException):
        pass

    def fake_exit(code: int) -> None:
        recorder.events.append(f"os._exit({code})")
        raise _Exit

    monkeypatch.setattr(graceful_exit_module, "_shutdown_committed", False)
    monkeypatch.setattr(graceful_exit_module.os, "_exit", fake_exit)
    monkeypatch.setattr(
        graceful_exit_module,
        "stop_gpu_session_telemetry",
        lambda label: recorder.events.append("gpu-telemetry"),
    )
    try:
        graceful_exit_module.graceful_exit(logger=logging.getLogger("test"), **kwargs)
    except _Exit:
        pass


class _Controller:
    _shutdown_completed = True

    def __init__(self, recorder: _Recorder, *, fail: bool = False) -> None:
        self._recorder = recorder
        self._fail = fail

    def shutdown_app(self, reason: str | None = None) -> None:
        self._recorder.events.append("controller.shutdown_app")
        if self._fail:
            raise RuntimeError("controller boom")


class _Window:
    def __init__(self, recorder: _Recorder, *, fail: bool = False) -> None:
        self._recorder = recorder
        self._fail = fail

    def cleanup(self) -> None:
        self._recorder.events.append("window.cleanup")
        if self._fail:
            raise RuntimeError("window boom")


class _Root:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def quit(self) -> None:
        self._recorder.events.append("root.quit")

    def destroy(self) -> None:
        self._recorder.events.append("root.destroy")


class _Lock:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def release(self) -> None:
        self._recorder.events.append("lock.release")

    def is_acquired(self) -> bool:
        return True


_CANONICAL_ORDER = [
    "gpu-telemetry",
    "controller.shutdown_app",
    "window.cleanup",
    "root.quit",
    "root.destroy",
    "lock.release",
    "os._exit(0)",
]


def test_graceful_exit_keeps_the_canonical_close_order(monkeypatch) -> None:
    recorder = _Recorder()

    _run_graceful_exit(
        monkeypatch,
        recorder,
        controller=_Controller(recorder),
        root=_Root(recorder),
        single_instance_lock=_Lock(recorder),
        window=_Window(recorder),
        reason="test",
    )

    assert recorder.events == _CANONICAL_ORDER


def test_graceful_exit_continues_in_order_through_controller_and_window_failures(
    monkeypatch,
) -> None:
    recorder = _Recorder()

    _run_graceful_exit(
        monkeypatch,
        recorder,
        controller=_Controller(recorder, fail=True),
        root=_Root(recorder),
        single_instance_lock=_Lock(recorder),
        window=_Window(recorder, fail=True),
        reason="test",
    )

    assert recorder.events == _CANONICAL_ORDER


@pytest.mark.gui
def test_production_composition_hands_one_dispatcher_to_every_consumer(
    tk_root: tk.Tk, monkeypatch
) -> None:
    constructed_on_root: list[object] = []
    original_init = gui_invoker.TkInvoker.__init__

    def counting_init(self, root, *args, **kwargs):
        if root is tk_root:
            constructed_on_root.append(self)
        return original_init(self, root, *args, **kwargs)

    monkeypatch.setattr(gui_invoker.TkInvoker, "__init__", counting_init)

    _, app_state, controller, window = build_v2_app(root=tk_root)
    try:
        dispatcher = tk_dispatcher_for(tk_root)

        assert len(constructed_on_root) == 1  # one pump on the production root
        assert window._invoker is dispatcher
        assert app_state._invoker is dispatcher
        assert controller._ui_scheduler == dispatcher.invoke
        actions = window._presentation_actions
        assert actions is not None
        assert actions._dispatcher is dispatcher
        assert window._owns_ui_dispatcher is False
    finally:
        window.cleanup()


@pytest.mark.gui
def test_window_cleanup_disposes_the_production_dispatcher_once_and_fences_stale_callbacks(
    tk_root: tk.Tk,
) -> None:
    _, _, _, window = build_v2_app(root=tk_root)
    dispatcher = tk_dispatcher_for(tk_root)
    calls: list[str] = []

    dispatcher.schedule(lambda: calls.append("queued-before-cleanup"))
    window.cleanup()
    window.cleanup()  # repeated close does not repeat cleanup
    dispatcher.schedule(lambda: calls.append("after-cleanup"))
    for _ in range(3):
        tk_root.update()

    assert dispatcher.disposed is True
    assert calls == []
    # The production dispatcher stays registered: a closing root is never given a new pump.
    assert tk_dispatcher_for(tk_root) is dispatcher


@pytest.mark.gui
def test_failed_composition_disposes_the_dispatcher(tk_root: tk.Tk, monkeypatch) -> None:
    import src.app_factory as app_factory

    def boom(*args, **kwargs):
        raise RuntimeError("window construction failed")

    monkeypatch.setattr(app_factory, "MainWindowV2", boom)

    with pytest.raises(RuntimeError, match="window construction failed"):
        build_v2_app(root=tk_root)

    assert tk_dispatcher_for(tk_root).disposed is True


@pytest.mark.gui
def test_standalone_window_resolves_the_root_owner_and_releases_it_on_cleanup(
    tk_root: tk.Tk,
) -> None:
    window = MainWindowV2(tk_root)
    owner = tk_dispatcher_for(tk_root)

    assert window._invoker is owner
    assert window._owns_ui_dispatcher is True
    window.cleanup()

    assert owner.disposed is True
    successor = tk_dispatcher_for(tk_root)
    assert successor is not owner
    assert successor.disposed is False
    successor.dispose()


# Widget-scoped invokers that are disposed when their own widget closes; every other pump comes from
# ``tk_dispatcher_for``.
_WIDGET_SCOPED_INVOKER_FILES = frozenset(
    {
        "src/gui/widgets/lora_picker_panel.py",
        "src/gui/views/embedding_experiment_design_frame.py",
        "src/gui/views/lora_composition_design_frame.py",
    }
)


def test_no_second_dispatcher_owner_is_constructed_in_production_source() -> None:
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    for path in sorted((root / "src").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        if relative == "src/gui/ui_dispatcher.py":
            continue
        if re.search(r"\bTkUiDispatcher\(", text):
            offenders.append(f"{relative}: constructs TkUiDispatcher")
        if re.search(r"\b(?:TkInvoker|GuiInvoker)\(", text) and relative not in (
            _WIDGET_SCOPED_INVOKER_FILES
        ):
            offenders.append(f"{relative}: constructs a Tk pump")

    assert offenders == []
