from __future__ import annotations

import tkinter as tk

import pytest

# PR-GUI-F1: PipelineRunControlsV2 no longer has run_now_button - queue-only model
pytestmark = pytest.mark.skip(reason="PR-GUI-F1: run_now_button removed from PipelineRunControlsV2")

from src.gui.panels_v2.pipeline_run_controls_v2 import PipelineRunControlsV2


class DummyRunNowController:
    def __init__(self) -> None:
        self.run_now_v2_calls = 0

    def on_run_job_now_v2(self) -> None:
        self.run_now_v2_calls += 1


@pytest.mark.gui
def test_run_now_button_calls_on_run_job_now_v2(tk_root: tk.Tk) -> None:
    controller = DummyRunNowController()
    controls = PipelineRunControlsV2(tk_root, controller=controller)

    controls.run_now_button.invoke()

    assert controller.run_now_v2_calls == 1
