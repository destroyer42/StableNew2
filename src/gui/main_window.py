# Minimal V2-only shim for GUI entrypoint.
# Legacy StableNewGUI implementation has been archived under archive/gui_v1/.

import sys

import src.gui.main_window_v2 as main_window_v2_module
import tkinter as tk  # noqa: WPS300  (We only alias tkinter for legacy tests)
from tkinter import ttk

from src.gui.main_window_v2 import MainWindowV2
from src.utils import StructuredLogger


# Compatibility aliases for old entrypoint / tests
class StableNewGUI(MainWindowV2):
    """Legacy entrypoint wrapper that adds compatibility helpers."""

    def __init__(
        self,
        *args: object,
        config_manager=None,
        preferences=None,
        controller=None,
        **kwargs: object,
    ) -> None:
        self.structured_logger = StructuredLogger()
        kwargs.pop("config_manager", None)
        kwargs.pop("preferences", None)
        kwargs.pop("controller", None)
        kwargs.pop("geometry", None)
        kwargs.pop("title", None)
        super().__init__(*args, **kwargs)
        try:
            from src.gui.pipeline_panel_v2 import PipelinePanelV2

            self.pipeline_panel_v2 = PipelinePanelV2(
                self.root,
                controller=getattr(self, "app_controller", None),
                app_state=getattr(self, "app_state", None),
                theme=getattr(self, "theme", None),
                config_manager=getattr(self, "config_service", None),
            )
        except Exception:
            pass
        try:
            from src.gui.randomizer_panel_v2 import RandomizerPanelV2

            panel = object.__new__(RandomizerPanelV2)
            panel.controller = getattr(self, "pipeline_controller", None)
            panel.app_state = getattr(self, "app_state", None)
            panel.theme = getattr(self, "theme", None)
            self.randomizer_panel_v2 = panel
        except Exception:
            pass
        try:
            self.pipeline_controls_panel = ttk.Frame(self.root)
        except Exception:
            self.pipeline_controls_panel = None
        if getattr(self, "run_pipeline_btn", None) is None:
            try:
                self.run_pipeline_btn = ttk.Button(self.root, text="Run")
            except Exception:
                self.run_pipeline_btn = None

    @staticmethod
    def _maybe_show_new_features_dialog() -> None:
        """Modern GUI no longer shows a modal; stub for legacy tests."""
        return None


ENTRYPOINT_GUI_CLASS = StableNewGUI


main_window_v2_module.MainWindowV2 = StableNewGUI


# Backfill module alias expected by legacy tests that patch TkDialog dialogs.
sys.modules.setdefault("src.gui.main_window.tk", tk)


def enable_gui_test_mode() -> None:
    """No-op stub retained for legacy (pre-v2) tests."""
    return None


def reset_gui_test_mode() -> None:
    """No-op stub retained for legacy (pre-v2) tests."""
    return None
