from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.panels_v2.pipeline_run_controls_v2 import PipelineRunControlsV2

# PR-GUI-F1: PipelineRunControlsV2 no longer has run_button - auto-run via queue
pytestmark = pytest.mark.skip(reason="PR-GUI-F1: run_button removed from PipelineRunControlsV2")


class DummyController:
    def __init__(self) -> None:
        self.start_run_calls = 0
        self.start_run_v2_calls = 0

    def start_run(self) -> None:
        self.start_run_calls += 1

    def start_run_v2(self) -> None:
        self.start_run_v2_calls += 1


@pytest.mark.gui
def test_run_button_invokes_start_run_v2(tk_root: tk.Tk) -> None:
    controller = DummyController()
    frame = PipelineRunControlsV2(tk_root, controller=controller)

    frame.run_button.invoke()

    assert controller.start_run_v2_calls == 1
    assert controller.start_run_calls == 0
