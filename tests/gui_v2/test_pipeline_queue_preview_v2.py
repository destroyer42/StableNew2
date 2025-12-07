from __future__ import annotations

import pytest

# PR-GUI-F1: Tests reference PreviewPanelV2.queue_items_text which was removed
# Queue widgets moved to QueuePanelV2
pytestmark = pytest.mark.skip(reason="PR-GUI-F1: PreviewPanelV2 queue widgets removed")

from src.gui.app_state_v2 import AppStateV2
from src.gui.panels_v2.pipeline_run_controls_v2 import PipelineRunControlsV2
from src.gui.preview_panel_v2 import PreviewPanelV2


class DummyQueueController:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def on_pause_queue(self) -> None:
        self.calls.append("pause")

    def on_resume_queue(self) -> None:
        self.calls.append("resume")

    def on_cancel_current_job(self) -> None:
        self.calls.append("cancel")

    def on_add_job_to_queue(self) -> None:
        self.calls.append("add")

    def on_run_job_now(self) -> None:
        self.calls.append("run")

    def on_clear_job_draft(self) -> None:
        self.calls.append("clear")

    def on_run_queue_now_clicked(self) -> None:
        self.calls.append("run")

    def start_run(self) -> None:
        self.calls.append("start_run")

    def on_stop_clicked(self) -> None:
        self.calls.append("stop")


@pytest.mark.gui
def test_preview_panel_queue_sections_and_controls(tk_root) -> None:
    controller = DummyQueueController()
    app_state = AppStateV2()
    panel = PreviewPanelV2(tk_root, controller=controller, app_state=app_state)

    panel.update_queue_items([])
    queue_text = panel.queue_items_text.get("1.0", "end").strip()
    assert "No pending jobs" in queue_text

    panel.update_queue_items(["job-alpha", "job-beta"])
    queue_text = panel.queue_items_text.get("1.0", "end")
    assert "job-alpha" in queue_text
    assert "job-beta" in queue_text

    panel.update_running_job(
        {"job_id": "job-123", "status": "running", "payload": {"packs": [{"pack_id": "p1"}]}},
    )
    assert "job-123" in panel.running_job_label.cget("text")
    assert panel.running_job_status_label.cget("text") == "Status: Running"

    panel.update_queue_status("paused")
    assert panel.queue_status_label.cget("text") == "Queue Status: Paused"

    panel.pause_button.invoke()
    panel.resume_button.invoke()
    panel.cancel_button.invoke()
    assert controller.calls[-3:] == ["pause", "resume", "cancel"]


@pytest.mark.gui
def test_pipeline_run_controls_invoke_controller_methods(tk_root) -> None:
    controller = DummyQueueController()
    controls = PipelineRunControlsV2(tk_root, controller=controller)

    controls.add_button.invoke()
    controls.run_now_button.invoke()
    controls.clear_draft_button.invoke()

    assert controller.calls == ["add", "run", "clear"]


def test_pipeline_run_controls_start_and_stop_invoke_shim(tk_root) -> None:
    controller = DummyQueueController()
    controls = PipelineRunControlsV2(tk_root, controller=controller)

    controls.run_button.invoke()
    controls.stop_button.invoke()

    assert controller.calls[-2:] == ["start_run", "stop"]
