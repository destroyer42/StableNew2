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
                "webui",
                "A1111 / WebUI",
                OperatorReadinessState.READY,
                "WebUI is ready.",
                (),
                (),
                "test",
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
def test_confirm_action_is_explicit_off_tk_and_reports_the_outcome(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch
):
    service = _Service()
    started: list = []

    def start(
        done,
    ) -> None:  # the application starts the release off the Tk thread and calls back on it
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
    monkeypatch.setattr(
        "src.gui.panels_v2.operator_readiness_panel_v2.messagebox.askokcancel",
        lambda *a, **k: False,
    )
    button.invoke()
    assert started == []

    monkeypatch.setattr(
        "src.gui.panels_v2.operator_readiness_panel_v2.messagebox.askokcancel", lambda *a, **k: True
    )
    button.invoke()
    assert len(started) == 1  # exactly one release request per confirmation

    started[0]({"released": False, "reason": "no_positive_recovery_evidence"})
    detail = panel.record_widgets["gpu_device"]["detail"].cget("text")
    assert "does not yet enumerate correctly" in detail and "Incident gpu-1." in detail

    service.quarantined = False
    started[0]({"released": True, "reason": "released"})
    assert "gpu_device" not in panel.record_widgets  # the condition is gone once released


@pytest.mark.gui
def test_without_the_application_callback_there_is_no_release_control(
    tk_root: tk.Tk, tmp_path: Path
):
    panel = OperatorReadinessPanelV2(
        tk_root, service=_Service(), ui_state_store=UIStateStore(tmp_path / "ui.json")
    )
    panel.pack()
    assert "confirm_gpu_recovery" not in panel.record_widgets["gpu_device"]


def test_main_window_release_goes_through_the_application_controller(monkeypatch):
    confirm = Mock(return_value={"released": True, "reason": "released"})
    window = MainWindowV2.__new__(MainWindowV2)
    # The controller exposes only the delegate: the window has no path to the job service, queue or coordinator.
    window.app_controller = SimpleNamespace(confirm_gpu_recovery=confirm)
    delivered: list = []
    window.run_in_main_thread = lambda fn: fn()  # the Tk marshal, synchronous here

    class _Registry:
        def spawn(self, *, target, **_kwargs):
            target()
            return SimpleNamespace()

    monkeypatch.setattr("src.utils.thread_registry.get_thread_registry", lambda: _Registry())
    window._release_gpu_quarantine_async(delivered.append)
    confirm.assert_called_once_with()
    assert delivered == [{"released": True, "reason": "released"}]


def test_main_window_release_failure_is_reported_not_raised(monkeypatch):
    window = MainWindowV2.__new__(MainWindowV2)
    window.app_controller = SimpleNamespace(
        confirm_gpu_recovery=Mock(side_effect=RuntimeError("boom"))
    )
    delivered: list = []
    window.run_in_main_thread = lambda fn: fn()

    class _Registry:
        def spawn(self, *, target, **_kwargs):
            target()
            return SimpleNamespace()

    monkeypatch.setattr("src.utils.thread_registry.get_thread_registry", lambda: _Registry())
    window._release_gpu_quarantine_async(delivered.append)
    assert delivered == [{"released": False, "reason": "release_error"}]
    missing = MainWindowV2.__new__(MainWindowV2)
    missing.app_controller = SimpleNamespace()
    missing._release_gpu_quarantine_async(delivered.append)
    assert delivered[-1] == {"released": False, "reason": "not_quarantined"}


def test_main_window_surfaces_a_quarantine_through_the_application_controller():
    registered: list = []

    def add(listener, *, replay_active=False):
        registered.append((listener, replay_active))

    window = MainWindowV2.__new__(MainWindowV2)
    window._is_test_mode = False
    window.app_controller = SimpleNamespace(add_gpu_quarantine_listener=add)
    opened: list = []
    window.run_in_main_thread = lambda fn: opened.append(fn)
    window._watch_gpu_quarantine()
    assert (
        len(registered) == 1 and registered[0][1] is True
    )  # a restored incident is announced at startup
    assert opened == []
    registered[0][0]({"status": "quarantined", "incident_id": "gpu-1"})
    assert opened == [window.open_operator_readiness]

    under_test = MainWindowV2.__new__(MainWindowV2)
    under_test._is_test_mode = True
    under_test.app_controller = SimpleNamespace(add_gpu_quarantine_listener=add)
    under_test._watch_gpu_quarantine()
    assert registered[-1][1] is False
    # No controller delegate (a stub application): nothing is registered and nothing fails.
    bare = MainWindowV2.__new__(MainWindowV2)
    bare._is_test_mode = True
    bare.app_controller = SimpleNamespace()
    bare._watch_gpu_quarantine()


def test_application_controller_delegates_to_the_coordinator_only():
    from src.controller.app_controller import AppController

    outcome = SimpleNamespace(
        to_dict=lambda: {"released": False, "reason": "no_positive_recovery_evidence"}
    )
    coordinator = SimpleNamespace(release=Mock(return_value=outcome), add_incident_listener=Mock())
    controller = AppController.__new__(AppController)
    controller.job_service = SimpleNamespace(gpu_loss=coordinator)
    projections = SimpleNamespace(publish_queue_refresh=Mock())
    controller._runtime_projection_coordinator = projections
    assert controller.confirm_gpu_recovery() == {
        "released": False,
        "reason": "no_positive_recovery_evidence",
    }
    coordinator.release.assert_called_once_with(operator_confirmed=True)
    projections.publish_queue_refresh.assert_called_once_with()  # the queue's hold message must be recomputed

    def listener(_snapshot):
        return None

    controller.add_gpu_quarantine_listener(listener, replay_active=True)
    coordinator.add_incident_listener.assert_called_once_with(listener, replay_active=True)
