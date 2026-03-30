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
                    "display_label": "fantasy_dragon | row=1 | job-99",
                    "status": "running",
                    "stage_display": "1/2 txt2img - sampling (42%)",
                    "pid_display": "123",
                    "diagnostics_text": "duration=2400ms | outputs=1",
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
            "controller": {
                "queue_projection_timing": {
                    "elapsed_ms": 18.5,
                    "job_count": 2,
                    "summary_count": 2,
                    "fallback_count": 0,
                }
            },
            "pipeline_controller": {
                "preview_build_timing": {
                    "source": "job_draft",
                    "elapsed_ms": 24.5,
                    "job_count": 2,
                    "pack_entry_count": 1,
                    "error": None,
                }
            },
            "webui_connection": {
                "state": "ready",
                "timing": {
                    "total_elapsed_ms": 1200.0,
                    "retry_attempts_used": 1,
                    "autostart_invoked": True,
                    "error": None,
                },
            },
            "app_state": {
                "running_job": {"display_label": "fantasy_dragon | row=1 | job-99"},
                "runtime_status": {
                    "stage_display": "1/2 txt2img - sampling",
                    "progress_pct": 42,
                    "eta_display": "12s",
                },
            },
            "queue": {
                "runner_running": True,
                "paused": False,
                "queued_job_ids": ["job-99"],
                "job_count": 1,
                "current_job_id": "job-99",
            },
            "pipeline_tab": {
                "hot_surface_scheduler": {
                    "avg_ms": 4.0,
                    "max_ms": 7.0,
                    "slow_count": 0,
                    "dirty_pending": ["preview"],
                },
                "callback_metrics": {
                    "_on_runtime_status_changed": {"avg_ms": 1.5, "max_ms": 2.0, "slow_count": 0}
                },
                "queue_panel": {
                    "refresh_metrics": {
                        "update_from_app_state": {"avg_ms": 2.5, "max_ms": 4.0, "slow_count": 0}
                    }
                },
                "running_job_panel": {
                    "avg_ms": 1.1,
                    "max_ms": 3.0,
                    "skipped_count": 4,
                    "timeline_clear_count": 0,
                },
            },
            "log_trace_panel": {
                "audience": "operator",
                "avg_ms": 1.0,
                "max_ms": 2.0,
                "append_only_count": 3,
                "full_rebuild_count": 1,
            },
            "process_inspector": {
                "scanner_status": "Last scan: 10:00:00 scanned=2 killed=0",
                "protected_pids": [123, 456],
                "risk": {
                    "status": "warning",
                    "stablenew_like_count": 2,
                    "main_process_count": 1,
                    "webui_process_count": 1,
                    "suspicious_processes": [
                        {"pid": 987, "rss_mb": 640.0, "reasons": ["high_rss_512mb_plus"]}
                    ],
                },
            },
            "threads": {
                "thread_count": 2,
                "tracked_status": "[thread_registry] 1 active thread(s):\n  - WorkerThread (normal, alive, age=3.0s)",
                "threads": [
                    {
                        "name": "MainThread",
                        "ident": 1,
                        "daemon": False,
                        "tracked": False,
                        "top_frame": {"file": "app_controller.py", "line": 123, "function": "get_diagnostics_snapshot"},
                    }
                ],
            },
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
    assert "fantasy_dragon" in panel._runtime_var.get()
    assert "queued=1" in panel._queue_state_var.get()
    assert "24.5ms" in panel._preview_timing_var.get()
    assert "ready" in panel._readiness_timing_var.get()
    assert "18.5ms" in panel._queue_timing_var.get()
    watchdog_text = panel._watchdog_text.get("1.0", tk.END)
    assert "reason=MEMORY" in watchdog_text
    process_text = panel._process_text.get("1.0", tk.END)
    assert "warning" in process_text
    thread_text = panel._thread_text.get("1.0", tk.END)
    assert "MainThread" in thread_text
    ui_text = panel._ui_metrics_text.get("1.0", tk.END)
    assert "hot-surface" in ui_text

    panel.destroy()
    root.destroy()
