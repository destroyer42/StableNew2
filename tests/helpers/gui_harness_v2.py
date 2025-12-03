from __future__ import annotations

import tkinter as tk

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.main_window_v2 import MainWindowV2
from tests.journeys.fakes.fake_pipeline_runner import FakePipelineRunner


class GuiV2Harness:
    """Lightweight helper for bootstrapping GUI V2 components in tests."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.pipeline_runner = FakePipelineRunner()
        self.controller = AppController(
            None,
            threaded=False,
            pipeline_runner=self.pipeline_runner,
        )
        self.controller.app_state = AppStateV2()
        self.window = MainWindowV2(
            root,
            app_state=self.controller.app_state,
            app_controller=self.controller,
            pipeline_controller=self.controller,
        )
        self.pipeline_tab = getattr(self.window, "pipeline_tab", None)

    def cleanup(self) -> None:
        try:
            self.window.cleanup()
        except Exception:
            pass
