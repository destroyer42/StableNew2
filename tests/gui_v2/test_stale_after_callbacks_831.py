"""PR-GUI-RELIABILITY-831 (finding F8): widget-owned after() timers must not outlive their widget.

A pending ``after`` callback whose widget was destroyed fires into a deleted command and Tcl reports
``invalid command name "<id>_pump"`` (or ``_tick``) to ``bgerror``.  These tests collect ``bgerror`` calls.
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

import pytest

from src.gui.gui_invoker import GuiInvoker
from src.gui.panels_v2.running_job_panel_v2 import RunningJobPanelV2


@pytest.fixture
def root_and_errors():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    errors: list[str] = []
    root.tk.createcommand("collect_bgerror", lambda message: errors.append(str(message)))
    root.tk.eval("proc bgerror {message} {collect_bgerror $message}")
    yield root, errors
    try:
        root.destroy()
    except tk.TclError:
        pass


def _run_for(root: tk.Tk, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)


def test_disposing_an_invoker_then_destroying_its_widget_leaves_no_stale_pump(root_and_errors):
    root, errors = root_and_errors
    frame = ttk.Frame(root)
    frame.pack()
    invoker = GuiInvoker(frame)
    root.update()

    invoker.dispose()
    frame.destroy()
    _run_for(root, 0.15)

    assert errors == []


def test_disposing_an_invoker_cancels_its_pending_pump(root_and_errors):
    root, _errors = root_and_errors
    frame = ttk.Frame(root)
    frame.pack()
    invoker = GuiInvoker(frame)
    pending = invoker._pump_after_id
    assert pending in set(root.tk.splitlist(root.tk.call("after", "info")))

    invoker.dispose()
    invoker.dispose()  # idempotent

    assert pending not in set(root.tk.splitlist(root.tk.call("after", "info")))


def test_a_running_job_panel_stops_its_elapsed_timer_when_destroyed(root_and_errors):
    root, errors = root_and_errors
    panel = RunningJobPanelV2(root)
    panel.pack()
    panel._start_timer()
    timer = panel._timer_id
    assert timer in set(root.tk.splitlist(root.tk.call("after", "info")))

    panel.destroy()
    _run_for(root, 0.15)

    assert panel._timer_id is None
    assert timer not in set(root.tk.splitlist(root.tk.call("after", "info")))
    assert errors == []
