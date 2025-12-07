"""GUI tests for the diagnostics dashboard."""

from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.views.diagnostics_dashboard_v2 import DiagnosticsDashboardV2


class DummyController:
    def __init__(self) -> None:
        self._snapshot = {
            "jobs": [
                {
                    "job_id": "job-99",
                    "status": "running",
                    "external_pids": [123],
                    "run_mode": "queue",
                    "priority": "HIGH",
                }
            ],
            "watchdog_events": [
                {
                    "job_id": "job-99",
                    "reason": "MEMORY",
                    "info": {"rss_mb": 512},
                    "timestamp": 0,
                }
            ],
            "cleanup_history": [],
            "containers": {},
            "last_bundle": "reports/diagnostics/sample.zip",
            "last_bundle_reason": "manual",
        }

    def get_diagnostics_snapshot(self) -> dict[str, object]:
        return self._snapshot


@pytest.mark.gui
def test_diagnostics_dashboard_renders_snapshot() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")

    controller = DummyController()
    panel = DiagnosticsDashboardV2(root, controller=controller)
    root.update_idletasks()

    job_items = panel._job_tree.get_children()
    assert job_items
    bundle_label = panel._bundle_var.get()
    assert "manual" in bundle_label
    watchdog_text = panel._watchdog_text.get("1.0", tk.END)
    assert "reason=MEMORY" in watchdog_text

    panel.destroy()
    root.destroy()
