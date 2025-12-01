from __future__ import annotations

import pytest
import tkinter as tk

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from tests.journeys.fakes.fake_pipeline_runner import FakePipelineRunner


@pytest.mark.gui
def test_pipeline_tab_frame_v2_wiring(tk_root: tk.Tk) -> None:
    runner = FakePipelineRunner()
    controller = AppController(None, threaded=False, pipeline_runner=runner)
    controller.app_state = AppStateV2()

    tab = PipelineTabFrame(
        tk_root,
        app_state=controller.app_state,
        app_controller=controller,
        pipeline_controller=controller,
    )
    try:
        assert hasattr(tab, "sidebar")
        assert hasattr(tab, "stage_cards_panel")
        assert hasattr(tab, "preview_panel")
        assert tab.left_column.winfo_exists()
        assert tab.center_column.winfo_exists()
        assert tab.right_column.winfo_exists()
    finally:
        tab.destroy()
