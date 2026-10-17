"""Audit P0-6: failures that used to be silent are visible, and the Learning scan completes on the GUI thread."""

from __future__ import annotations

import logging
import threading
from tkinter import ttk
from types import SimpleNamespace

import pytest

from src.gui.main_window_v2 import MainWindowV2
from tests.gui_v2.test_discovered_review_inbox import _make_controller


def _bare_window(tk_root) -> MainWindowV2:
    window = MainWindowV2.__new__(MainWindowV2)
    window._tab_registry = {}
    window.center_notebook = ttk.Notebook(tk_root)
    return window


def _label_texts(widget) -> list[str]:
    texts: list[str] = []
    for child in widget.winfo_children():
        if isinstance(child, ttk.Label):
            texts.append(str(child.cget("text")))
        texts.extend(_label_texts(child))
    return texts


def test_a_tab_that_fails_to_build_is_logged_and_shows_its_error(
    tk_root, caplog: pytest.LogCaptureFixture
) -> None:
    window = _bare_window(tk_root)

    def broken(_parent):
        raise RuntimeError("constructor exploded")

    with caplog.at_level(logging.ERROR, logger="src.gui.main_window_v2"):
        frame = window.add_tab("broken", "Broken Tab", broken)

    assert (
        window.get_tab("broken") is frame
    )  # the tab still exists so the notebook layout is unchanged
    assert any(
        "failed to build" in record.getMessage() and record.exc_info for record in caplog.records
    )
    texts = " ".join(_label_texts(frame))
    assert "Broken Tab" in texts and "RuntimeError" in texts and "constructor exploded" in texts


def test_a_healthy_tab_is_unchanged(tk_root) -> None:
    window = _bare_window(tk_root)
    frame = window.add_tab("ok", "Fine", lambda parent: ttk.Frame(parent))
    assert window.get_tab("ok") is frame and _label_texts(frame) == []


def test_the_scan_completion_callback_runs_through_the_gui_thread_dispatcher(tmp_path) -> None:
    controller = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore

    controller._discovered_review_store = DiscoveredReviewStore(tmp_path)
    dispatched: list[int] = []
    done = threading.Event()
    seen: list[object] = []
    worker_thread_id: list[int] = []

    def fake_run_in_gui_thread(fn) -> None:
        worker_thread_id.append(threading.get_ident())
        dispatched.append(1)
        fn()  # a real dispatcher would queue this for the Tk pump

    controller.app_controller = SimpleNamespace(_run_in_gui_thread=fake_run_in_gui_thread)

    def on_complete(result) -> None:
        seen.append(result)
        done.set()

    controller.trigger_background_scan(
        output_root=str(tmp_path / "no_such_dir"), on_complete=on_complete
    )
    assert done.wait(timeout=5.0)
    assert (
        dispatched == [1] and len(seen) == 1
    )  # delivered via the dispatcher, never called bare from the worker
    assert (
        worker_thread_id[0] != threading.get_ident()
    )  # the scan itself ran off the calling thread


def test_the_scan_worker_is_a_tracked_non_daemon_thread(tmp_path) -> None:
    from src.utils.thread_registry import get_thread_registry

    controller = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore

    controller._discovered_review_store = DiscoveredReviewStore(tmp_path)
    gate = threading.Event()
    done = threading.Event()
    controller.trigger_background_scan(
        output_root=str(tmp_path / "no_such_dir"),
        on_complete=lambda _r: (gate.wait(5.0), done.set()),
    )
    scan_threads = [t for t in threading.enumerate() if t.name == "discovered-scan"]
    try:
        assert scan_threads and not scan_threads[0].daemon
        assert any(name == "discovered-scan" for name in _registered_names(get_thread_registry()))
    finally:
        gate.set()
        done.wait(timeout=5.0)


def _registered_names(registry) -> list[str]:
    with registry._registry_lock:
        return [str(getattr(info, "name", "")) for info in registry._threads.values()]
