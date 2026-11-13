"""Characterization of process-global exception-hook ownership (ARCH-953).

``DiagnosticsCoordinator`` is the only holder of the original ``sys.excepthook``,
``threading.excepthook`` and Tk ``report_callback_exception`` values.  These tests
pin the install / forward / restore behavior of the three hooks.  Every test
restores the process-global hooks in a ``finally`` block so a failure cannot leak
a hook into other tests.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.app_controller import AppController
from src.controller.app_controller_services.diagnostics_coordinator import (
    DiagnosticsCoordinator,
)


@contextmanager
def _hook_sandbox() -> Iterator[None]:
    saved_sys = sys.excepthook
    saved_thread = threading.excepthook
    try:
        yield
    finally:
        sys.excepthook = saved_sys
        threading.excepthook = saved_thread


def _make_hook(label: str) -> Any:
    def hook(*args: Any) -> None:  # pragma: no cover - identity only
        return None

    hook.__name__ = f"hook_{label}"
    return hook


class FakeRoot:
    """Tk root stand-in exposing a replaceable ``report_callback_exception``."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

        def original(exc_type: Any, exc_value: Any, exc_traceback: Any) -> None:
            self.calls.append((exc_type, exc_value, exc_traceback))

        self.original = original
        self.report_callback_exception = original


class RaisingRoot:
    """Tk root whose hook cannot be replaced (partial-install simulation)."""

    def __init__(self) -> None:
        self._original = lambda *args: None

    @property
    def report_callback_exception(self) -> Any:
        return self._original

    @report_callback_exception.setter
    def report_callback_exception(self, value: Any) -> None:
        raise RuntimeError("cannot replace Tk hook")


def _handlers() -> tuple[Any, Any, Any]:
    return _make_hook("sys"), _make_hook("thread"), _make_hook("tk")


def _install(coordinator: DiagnosticsCoordinator, window: Any, handlers: tuple[Any, ...]) -> None:
    coordinator.install(
        main_window=window,
        on_uncaught_exception=handlers[0],
        on_thread_exception=handlers[1],
        on_tk_exception=handlers[2],
    )


# ---------------------------------------------------------------------------
# Coordinator lifecycle
# ---------------------------------------------------------------------------


def test_construction_does_not_replace_any_hook() -> None:
    with _hook_sandbox():
        original_sys = sys.excepthook
        original_thread = threading.excepthook

        DiagnosticsCoordinator()

        assert sys.excepthook is original_sys
        assert threading.excepthook is original_thread


def test_install_replaces_every_hook_and_uninstall_restores_them() -> None:
    with _hook_sandbox():
        original_sys = _make_hook("orig_sys")
        original_thread = _make_hook("orig_thread")
        sys.excepthook = original_sys
        threading.excepthook = original_thread
        root = FakeRoot()
        window = SimpleNamespace(root=root)
        handlers = _handlers()

        coordinator = DiagnosticsCoordinator()
        _install(coordinator, window, handlers)

        assert sys.excepthook is handlers[0]
        assert threading.excepthook is handlers[1]
        assert root.report_callback_exception is handlers[2]

        coordinator.uninstall(main_window=window)

        assert sys.excepthook is original_sys
        assert threading.excepthook is original_thread
        assert root.report_callback_exception is root.original


def test_system_hook_is_captured_at_construction_thread_hook_at_install() -> None:
    """A hook swapped between construction and install is restored per hook type."""
    with _hook_sandbox():
        at_construction_sys = _make_hook("sys_at_construction")
        at_construction_thread = _make_hook("thread_at_construction")
        sys.excepthook = at_construction_sys
        threading.excepthook = at_construction_thread
        coordinator = DiagnosticsCoordinator()

        later_sys = _make_hook("sys_later")
        later_thread = _make_hook("thread_later")
        sys.excepthook = later_sys
        threading.excepthook = later_thread
        handlers = _handlers()
        _install(coordinator, SimpleNamespace(root=None), handlers)
        coordinator.uninstall(main_window=SimpleNamespace(root=None))

        assert sys.excepthook is at_construction_sys
        assert threading.excepthook is later_thread


@pytest.mark.parametrize(
    "window",
    [None, SimpleNamespace(), SimpleNamespace(root=None), SimpleNamespace(root=object())],
    ids=["no-window", "no-root-attr", "root-none", "root-without-report-hook"],
)
def test_install_without_tk_root_still_manages_process_hooks(window: Any) -> None:
    with _hook_sandbox():
        original_sys = _make_hook("orig_sys")
        original_thread = _make_hook("orig_thread")
        sys.excepthook = original_sys
        threading.excepthook = original_thread
        handlers = _handlers()
        coordinator = DiagnosticsCoordinator()

        _install(coordinator, window, handlers)
        assert sys.excepthook is handlers[0]
        assert threading.excepthook is handlers[1]

        coordinator.uninstall(main_window=window)
        assert sys.excepthook is original_sys
        assert threading.excepthook is original_thread


def test_failed_tk_install_leaves_process_hooks_restorable() -> None:
    with _hook_sandbox():
        original_sys = _make_hook("orig_sys")
        original_thread = _make_hook("orig_thread")
        sys.excepthook = original_sys
        threading.excepthook = original_thread
        window = SimpleNamespace(root=RaisingRoot())
        coordinator = DiagnosticsCoordinator()

        try:
            _install(coordinator, window, _handlers())
        except RuntimeError:
            pass
        finally:
            coordinator.uninstall(main_window=window)

        assert sys.excepthook is original_sys
        assert threading.excepthook is original_thread


def test_repeated_install_uninstall_cycles_restore_the_original_hooks() -> None:
    with _hook_sandbox():
        original_sys = _make_hook("orig_sys")
        original_thread = _make_hook("orig_thread")
        sys.excepthook = original_sys
        threading.excepthook = original_thread
        root = FakeRoot()
        window = SimpleNamespace(root=root)
        coordinator = DiagnosticsCoordinator()

        for _ in range(3):
            handlers = _handlers()
            _install(coordinator, window, handlers)
            assert sys.excepthook is handlers[0]
            assert threading.excepthook is handlers[1]
            assert root.report_callback_exception is handlers[2]
            coordinator.uninstall(main_window=window)
            assert sys.excepthook is original_sys
            assert threading.excepthook is original_thread
            assert root.report_callback_exception is root.original


def test_uninstall_without_install_leaves_hooks_untouched() -> None:
    with _hook_sandbox():
        original_sys = _make_hook("orig_sys")
        original_thread = _make_hook("orig_thread")
        sys.excepthook = original_sys
        threading.excepthook = original_thread
        root = FakeRoot()
        coordinator = DiagnosticsCoordinator()

        coordinator.uninstall(main_window=SimpleNamespace(root=root))

        assert sys.excepthook is original_sys
        assert threading.excepthook is original_thread
        assert root.report_callback_exception is root.original


# ---------------------------------------------------------------------------
# Controller integration: crash bundle first, then forward to the original hook
# ---------------------------------------------------------------------------


class _DummyRunner:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass


class _DummyJobService:
    def __init__(self) -> None:
        from src.queue.job_repository import JobRepository

        self.history_store = JobRepository(":memory:")
        self.callbacks: dict[str, list[Any]] = {}

    def register_callback(self, event: str, callback: Any) -> None:
        self.callbacks.setdefault(event, []).append(callback)

    def get_diagnostics_snapshot(self) -> dict[str, object]:
        return {"jobs": []}


class _HookEnv:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []
        self.root = FakeRoot()
        self.original_sys = self._recorder("original_sys")
        self.original_thread = self._recorder("original_thread")

        def tk_original(exc_type: Any, exc_value: Any, exc_traceback: Any) -> None:
            self.events.append(("original_tk", exc_value))

        self.root.report_callback_exception = tk_original
        self.original_tk = tk_original

    def _recorder(self, label: str) -> Any:
        def hook(*args: Any) -> None:
            self.events.append((label, args))

        return hook


def _build_controller(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env: _HookEnv
) -> AppController:
    def fake_build(**kwargs: Any) -> Path:
        env.events.append(("bundle", kwargs["reason"]))
        return tmp_path / f"{kwargs['reason']}.zip"

    monkeypatch.setattr("src.controller.app_controller.build_crash_bundle", fake_build)
    sys.excepthook = env.original_sys
    threading.excepthook = env.original_thread
    return AppController(
        SimpleNamespace(root=env.root),
        pipeline_runner=_DummyRunner(),
        job_service=_DummyJobService(),
    )


def test_controller_installs_hooks_and_teardown_restores_originals(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with _hook_sandbox():
        env = _HookEnv()
        controller = _build_controller(monkeypatch, tmp_path, env)
        try:
            assert sys.excepthook == controller._handle_uncaught_exception
            assert threading.excepthook == controller._handle_thread_exception
            assert env.root.report_callback_exception == controller._handle_tk_exception
        finally:
            controller._diagnostics_coordinator.uninstall(main_window=controller.main_window)

        assert sys.excepthook is env.original_sys
        assert threading.excepthook is env.original_thread
        assert env.root.report_callback_exception is env.original_tk


def test_system_exception_writes_bundle_before_forwarding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with _hook_sandbox():
        env = _HookEnv()
        controller = _build_controller(monkeypatch, tmp_path, env)
        try:
            error = ValueError("boom")
            sys.excepthook(ValueError, error, None)
        finally:
            controller._diagnostics_coordinator.uninstall(main_window=controller.main_window)

        assert env.events == [
            ("bundle", "uncaught_exception"),
            ("original_sys", (ValueError, error, None)),
        ]


def test_thread_exception_writes_bundle_before_forwarding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with _hook_sandbox():
        env = _HookEnv()
        controller = _build_controller(monkeypatch, tmp_path, env)
        try:
            error = RuntimeError("thread boom")
            worker = threading.Thread(name="HookOwnershipWorker")
            args = threading.ExceptHookArgs((RuntimeError, error, None, worker))
            threading.excepthook(args)
        finally:
            controller._diagnostics_coordinator.uninstall(main_window=controller.main_window)

        assert env.events == [
            ("bundle", "thread_exception"),
            ("original_thread", (args,)),
        ]


def test_tk_exception_writes_bundle_before_forwarding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with _hook_sandbox():
        env = _HookEnv()
        controller = _build_controller(monkeypatch, tmp_path, env)
        try:
            error = KeyError("tk boom")
            env.root.report_callback_exception(KeyError, error, None)
        finally:
            controller._diagnostics_coordinator.uninstall(main_window=controller.main_window)

        assert env.events == [("bundle", "tk_exception"), ("original_tk", error)]


def test_tk_forwarding_failure_is_suppressed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with _hook_sandbox():
        env = _HookEnv()

        def failing_original(*args: Any) -> None:
            env.events.append(("original_tk_failed", None))
            raise RuntimeError("forwarding failed")

        env.root.report_callback_exception = failing_original
        controller = _build_controller(monkeypatch, tmp_path, env)
        try:
            env.root.report_callback_exception(KeyError, KeyError("x"), None)
        finally:
            controller._diagnostics_coordinator.uninstall(main_window=controller.main_window)

        assert env.events == [("bundle", "tk_exception"), ("original_tk_failed", None)]
