from __future__ import annotations

import pytest
import tkinter as tk

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.main_window_v2 import MainWindowV2
from tests.journeys.fakes.fake_pipeline_runner import FakePipelineRunner


@pytest.mark.gui
def test_main_window_v2_smoke(tk_root: tk.Tk) -> None:
    runner = FakePipelineRunner()
    controller = AppController(None, threaded=False, pipeline_runner=runner)
    controller.app_state = AppStateV2()
    window = MainWindowV2(
        tk_root,
        app_state=controller.app_state,
        app_controller=controller,
        pipeline_controller=controller,
    )
    try:
        notebook = window.center_notebook
        tab_texts = [notebook.tab(idx, "text") for idx in range(notebook.index("end"))]
        assert "Prompt" in tab_texts
        assert "Pipeline" in tab_texts
        assert "Learning" in tab_texts
    finally:
        window.cleanup()
