from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.panels_v2.pipeline_run_controls_v2 import PipelineRunControlsV2

# PR-GUI-F1: PipelineRunControlsV2 no longer has add_button - moved to QueuePanelV2
pytestmark = pytest.mark.skip(reason="PR-GUI-F1: add_button removed from PipelineRunControlsV2")


class DummyController:
    def __init__(self) -> None:
        self.add_calls = 0

    def on_add_job_to_queue_v2(self) -> None:
        self.add_calls += 1


@pytest.mark.gui
def test_add_to_queue_button_invokes_on_add_job_to_queue_v2(tk_root: tk.Tk) -> None:
    controller = DummyController()
    controls = PipelineRunControlsV2(tk_root, controller=controller)

    controls.add_button.invoke()

    assert controller.add_calls == 1
