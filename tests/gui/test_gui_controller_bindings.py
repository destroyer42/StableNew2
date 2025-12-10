import tkinter as tk
from types import SimpleNamespace

import pytest

from src.gui.panels_v2.pipeline_run_controls_v2 import PipelineRunControlsV2
from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2


@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


def test_preview_panel_calls_controller_methods(tk_root: tk.Tk) -> None:
    class PreviewController:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def on_add_to_queue(self) -> None:
            self.calls.append("add")

        def on_clear_draft(self) -> None:
            self.calls.append("clear")

        def show_log_trace_panel(self) -> None:
            self.calls.append("details")

    controller = PreviewController()
    panel = PreviewPanelV2(tk_root, controller=controller)
    panel._on_add_to_queue()
    panel._on_clear_draft()
    panel._on_details_clicked()
    panel.destroy()
    assert controller.calls == ["add", "clear", "details"]


def test_pipeline_run_controls_forward_requests(tk_root: tk.Tk) -> None:
    class RunControlsController:
        def __init__(self) -> None:
            self.calls: list[str | tuple[str, bool]] = []

        def on_set_auto_run_v2(self, enabled: bool) -> None:
            self.calls.append(("auto", enabled))

        def on_pause_queue_v2(self) -> None:
            self.calls.append("pause")

        def on_resume_queue_v2(self) -> None:
            self.calls.append("resume")

    controller = RunControlsController()
    panel = PipelineRunControlsV2(tk_root, controller=controller)
    panel.auto_run_var.set(True)
    panel._on_auto_run_changed()
    panel._is_queue_paused = False
    panel._on_pause_resume()
    panel._is_queue_paused = True
    panel._on_pause_resume()
    panel.destroy()
    assert controller.calls == [("auto", True), "pause", "resume"]


def test_queue_panel_invokes_controller_actions(tk_root: tk.Tk) -> None:
    class QueueController:
        def __init__(self) -> None:
            self.calls: list[str | tuple[str, str]] = []

        def on_set_auto_run_v2(self, enabled: bool) -> None:
            self.calls.append(("auto", enabled))

        def on_pause_queue_v2(self) -> None:
            self.calls.append("pause")

        def on_resume_queue_v2(self) -> None:
            self.calls.append("resume")

        def on_queue_move_up_v2(self, job_id: str) -> None:
            self.calls.append(("move_up", job_id))

        def on_queue_move_down_v2(self, job_id: str) -> None:
            self.calls.append(("move_down", job_id))

        def on_queue_remove_job_v2(self, job_id: str) -> None:
            self.calls.append(("remove", job_id))

        def on_queue_clear_v2(self) -> None:
            self.calls.append("clear")

        def on_queue_send_job_v2(self) -> None:
            self.calls.append("send")

    controller = QueueController()
    panel = QueuePanelV2(tk_root, controller=controller)
    panel._jobs = [
        SimpleNamespace(job_id="job-1"),
        SimpleNamespace(job_id="job-2"),
    ]
    panel._get_selected_job = lambda: panel._jobs[0]
    panel._get_selected_index = lambda: 0
    panel.auto_run_var.set(False)
    panel._on_auto_run_changed()
    panel._is_queue_paused = False
    panel._on_pause_resume()
    panel._is_queue_paused = True
    panel._on_pause_resume()
    panel._on_move_up()
    panel._on_move_down()
    panel._on_remove()
    panel._on_clear()
    panel._on_send_job()
    panel.destroy()
    assert controller.calls == [
        ("auto", False),
        "pause",
        "resume",
        ("move_up", "job-1"),
        ("move_down", "job-1"),
        ("remove", "job-1"),
        "clear",
        "send",
    ]
