import tkinter as tk
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from src.controller.app_controller import AppController
from src.pipeline.job_models_v2 import JobHistoryItemDTO, JobQueueItemDTO
from src.queue.job_model import Job, JobPriority, JobStatus
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


def test_job_status_updates_use_ui_dispatcher() -> None:
    class FakeQueuePanel:
        def __init__(self) -> None:
            self.upsert_calls: list[JobQueueItemDTO] = []
            self.remove_calls: list[str] = []

        def upsert_job(self, dto: JobQueueItemDTO) -> None:
            self.upsert_calls.append(dto)

        def remove_job(self, job_id: str) -> None:
            self.remove_calls.append(job_id)

    class FakeHistoryPanel:
        def __init__(self) -> None:
            self.append_calls: list[JobHistoryItemDTO] = []

        def append_history_item(self, dto: JobHistoryItemDTO) -> None:
            self.append_calls.append(dto)

    class FakeMainWindow:
        def __init__(self) -> None:
            self.queue_panel = FakeQueuePanel()
            self.history_panel = FakeHistoryPanel()
            self.dispatched: list[Callable[[], None]] = []

        def run_in_main_thread(self, fn: Callable[[], None]) -> None:
            self.dispatched.append(fn)

    controller = AppController.__new__(AppController)
    controller.main_window = FakeMainWindow()
    controller._append_log = lambda *args, **kwargs: None

    job = Job(job_id="queued-job", priority=JobPriority.NORMAL)
    controller._on_job_status_for_panels(job, JobStatus.QUEUED)

    assert controller.main_window.queue_panel.upsert_calls == []
    assert controller.main_window.queue_panel.remove_calls == []
    assert controller.main_window.history_panel.append_calls == []
    assert len(controller.main_window.dispatched) == 1

    for fn in controller.main_window.dispatched:
        fn()

    assert len(controller.main_window.queue_panel.upsert_calls) == 1
    assert controller.main_window.queue_panel.remove_calls == []
    assert controller.main_window.history_panel.append_calls == []


def test_job_status_updates_with_root_fallback_run() -> None:
    class FakeQueuePanel:
        def __init__(self) -> None:
            self.upsert_calls: list[JobQueueItemDTO] = []
            self.remove_calls: list[str] = []

        def upsert_job(self, dto: JobQueueItemDTO) -> None:
            self.upsert_calls.append(dto)

        def remove_job(self, job_id: str) -> None:
            self.remove_calls.append(job_id)

    class FakeHistoryPanel:
        def __init__(self) -> None:
            self.append_calls: list[JobHistoryItemDTO] = []

        def append_history_item(self, dto: JobHistoryItemDTO) -> None:
            self.append_calls.append(dto)

    class FakeRoot:
        def __init__(self) -> None:
            self.after_calls: list[tuple[int, Callable[[], None]]] = []

        def after(self, delay: int, fn: Callable[[], None]) -> None:
            self.after_calls.append((delay, fn))
            fn()

    class FakeMainWindow:
        def __init__(self) -> None:
            self.queue_panel = FakeQueuePanel()
            self.history_panel = FakeHistoryPanel()
            self.root = FakeRoot()

    controller = AppController.__new__(AppController)
    controller.main_window = FakeMainWindow()
    controller._append_log = lambda *args, **kwargs: None

    job = Job(job_id="completed-job", priority=JobPriority.NORMAL)
    controller._on_job_status_for_panels(job, JobStatus.COMPLETED)

    assert controller.main_window.root.after_calls
    assert controller.main_window.queue_panel.remove_calls == ["completed-job"]
    assert controller.main_window.history_panel.append_calls
