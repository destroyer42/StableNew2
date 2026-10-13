"""PR-QUEUE-GPU-180: the Tk Operator Readiness action for a GPU device-loss quarantine (offline, semantic)."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.gui.main_window_v2 import MainWindowV2
from src.gui.panels_v2.operator_readiness_panel_v2 import OperatorReadinessPanelV2
from src.services.operator_readiness_service import (
    OperatorReadinessRecord,
    OperatorReadinessSnapshot,
    OperatorReadinessState,
    product_support_surfaces,
)
from src.services.ui_state_store import UIStateStore


class _Service:
    def __init__(self, quarantined: bool = True) -> None:
        self.quarantined = quarantined
        self.collects = 0

    def collect(self, *, source_image_path=None) -> OperatorReadinessSnapshot:
        self.collects += 1
        records = [
            OperatorReadinessRecord(
                "webui", "A1111 / WebUI", OperatorReadinessState.READY, "WebUI is ready.", (), (), "test"
            )
        ]
        if self.quarantined:
            records.insert(
                0,
                OperatorReadinessRecord(
                    "gpu_device",
                    "GPU device",
                    OperatorReadinessState.ACTION_REQUIRED,
                    "GPU device loss was confirmed.",
                    ("Incident gpu-1.",),
                    ("Recover the GPU.",),
                    "test",
                ),
            )
        return OperatorReadinessSnapshot(product_support_surfaces(), tuple(records))


@pytest.mark.gui
def test_confirm_action_is_explicit_off_tk_and_reports_the_outcome(tk_root: tk.Tk, tmp_path: Path, monkeypatch):
    service = _Service()
    started: list = []

    def start(done) -> None:  # the application starts the release off the Tk thread and calls back on it
        started.append(done)

    panel = OperatorReadinessPanelV2(
        tk_root,
        service=service,
        on_confirm_gpu_recovery=start,
        ui_state_store=UIStateStore(tmp_path / "ui.json"),
    )
    panel.pack()
    tk_root.update_idletasks()
    button = panel.record_widgets["gpu_device"]["confirm_gpu_recovery"]
    assert "confirm_gpu_recovery" not in panel.record_widgets["webui"]

    # Declining the confirmation dialog does nothing at all.
    monkeypatch.setattr("src.gui.panels_v2.operator_readiness_panel_v2.messagebox.askokcancel", lambda *a, **k: False)
    button.invoke()
    assert started == []

    monkeypatch.setattr("src.gui.panels_v2.operator_readiness_panel_v2.messagebox.askokcancel", lambda *a, **k: True)
    button.invoke()
    assert len(started) == 1  # exactly one release request per confirmation

    started[0]({"released": False, "reason": "no_positive_recovery_evidence"})
    detail = panel.record_widgets["gpu_device"]["detail"].cget("text")
    assert "does not yet enumerate correctly" in detail and "Incident gpu-1." in detail

    service.quarantined = False
    started[0]({"released": True, "reason": "released"})
    assert "gpu_device" not in panel.record_widgets  # the condition is gone once released


@pytest.mark.gui
def test_without_the_application_callback_there_is_no_release_control(tk_root: tk.Tk, tmp_path: Path):
    panel = OperatorReadinessPanelV2(
        tk_root, service=_Service(), ui_state_store=UIStateStore(tmp_path / "ui.json")
    )
    panel.pack()
    assert "confirm_gpu_recovery" not in panel.record_widgets["gpu_device"]


def test_main_window_release_runs_confirmed_and_delivers_on_the_ui_thread(monkeypatch):
    released = SimpleNamespace(to_dict=lambda: {"released": True, "reason": "released"})
    coordinator = SimpleNamespace(release=Mock(return_value=released))
    window = MainWindowV2.__new__(MainWindowV2)
    window.app_controller = SimpleNamespace(job_service=SimpleNamespace(gpu_loss=coordinator))
    delivered: list = []
    window.run_in_main_thread = lambda fn: fn()  # the Tk marshal, synchronous here

    class _Registry:
        def spawn(self, *, target, **_kwargs):
            target()
            return SimpleNamespace()

    monkeypatch.setattr("src.utils.thread_registry.get_thread_registry", lambda: _Registry())
    window._release_gpu_quarantine_async(delivered.append)
    coordinator.release.assert_called_once_with(operator_confirmed=True)
    assert delivered == [{"released": True, "reason": "released"}]


def test_main_window_surfaces_a_new_quarantine_once(monkeypatch):
    listeners: list = []
    state = {"info": None}
    queue = SimpleNamespace(
        register_state_listener=listeners.append,
        is_gpu_quarantined=lambda: state["info"] is not None,
        gpu_quarantine_info=lambda: state["info"],
    )
    window = MainWindowV2.__new__(MainWindowV2)
    window._is_test_mode = True
    window.app_controller = SimpleNamespace(job_service=SimpleNamespace(job_queue=queue))
    opened: list = []
    window.run_in_main_thread = lambda fn: opened.append(fn)
    window._watch_gpu_quarantine()
    assert len(listeners) == 1 and opened == []
    listeners[0]()  # nothing quarantined yet
    assert opened == []
    state["info"] = {"incident_id": "gpu-1"}
    listeners[0]()
    listeners[0]()  # a second notification for the same incident does not re-open the window
    assert len(opened) == 1 and opened[0] == window.open_operator_readiness
    state["info"] = {"incident_id": "gpu-2"}
    listeners[0]()
    assert len(opened) == 2
