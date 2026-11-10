"""PR-VID-UX-360: the task-first Video Workflow tab.

Real Tk widgets; the production ``VideoWorkflowController`` and NJR builder sit behind the recording
``JobService`` stand-in from ``tests.helpers.make_video_313``.  No GPU, Comfy process, model or network.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.views.video_workflow_task_panel_v2 import (
    PinTracker,
    SuggestedSettingsLine,
    WorkflowTaskSelector,
)

pytestmark = pytest.mark.gui


# ---------------------------------------------------------------- widgets


def test_selector_lists_four_tasks_and_reverts_on_refusal(tk_root):
    calls: list[str] = []

    def on_select(task_id: str) -> bool:
        calls.append(task_id)
        return task_id != "batch"

    sel = WorkflowTaskSelector(tk_root, on_select=on_select)
    assert list(sel.buttons) == ["animate", "follow_clip", "sequence", "batch"]
    sel.set_task("animate")
    sel.buttons["batch"].invoke()
    assert calls == ["batch"]
    assert sel.task_var.get() == "animate"
    sel.buttons["sequence"].invoke()
    assert sel.task_var.get() == "sequence"


def test_set_task_does_not_call_back(tk_root):
    calls: list[str] = []
    sel = WorkflowTaskSelector(tk_root, on_select=lambda t: calls.append(t) or True)
    sel.set_task("follow_clip")
    assert calls == [] and sel.task_var.get() == "follow_clip"


def test_unavailable_task_is_disabled_with_its_reason(tk_root):
    sel = WorkflowTaskSelector(tk_root, on_select=lambda t: True)
    sel.set_availability({"follow_clip": "No installed workflow supports this."})
    assert str(sel.buttons["follow_clip"].cget("state")) == "disabled"
    assert str(sel.buttons["animate"].cget("state")) != "disabled"
    sel.set_availability({})
    assert str(sel.buttons["follow_clip"].cget("state")) != "disabled"


def test_summary_line_joins_and_drops_empty_parts(tk_root):
    line = SuggestedSettingsLine(tk_root, on_change=lambda: None, on_reset=lambda: None)
    line.set_summary(["Engine X", "", "3.4 s", "smoothed"])
    assert line.summary_var.get() == "Engine X · 3.4 s · smoothed"
    line.set_notes(["one", "", "two"])
    assert line.notes_var.get() == "one\ntwo"


def test_summary_line_buttons_call_back(tk_root):
    calls: list[str] = []
    line = SuggestedSettingsLine(
        tk_root, on_change=lambda: calls.append("change"), on_reset=lambda: calls.append("reset")
    )
    line.change_button.invoke()
    line.reset_button.invoke()
    assert calls == ["change", "reset"]


def test_pin_tracker_pins_operator_writes_only(tk_root):
    var = tk.StringVar(master=tk_root)
    pins = PinTracker()
    pins.watch("seed", var)
    with pins.applying():
        var.set("1")
    assert pins.pinned == set()
    var.set("2")
    assert pins.pinned == {"seed"}
    pins.clear()
    assert pins.pinned == set()
    pins.pin_all(["seed", "smooth"])
    assert pins.pinned == {"seed", "smooth"}
