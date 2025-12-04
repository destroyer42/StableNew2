from __future__ import annotations

import tkinter as tk
from typing import Optional, Tuple

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.main_window_v2 import MainWindowV2
from src.api.webui_process_manager import WebUIProcessManager
from src.utils.config import ConfigManager
from src.utils import attach_gui_log_handler


def build_v2_app(
    *,
    root: Optional[tk.Tk] = None,
    pipeline_runner=None,
    webui_manager: WebUIProcessManager | None = None,
    threaded: bool = False,
    config_manager: ConfigManager | None = None,
) -> Tuple[tk.Tk, AppStateV2, AppController, MainWindowV2]:
    """
    Build the V2 application stack with injectable runner for tests.

    Returns (root, app_state, app_controller, window).
    """

    if root is None:
        root = tk.Tk()

    app_state = AppStateV2()

    # Create controller first to get gui_log_handler
    config_manager = config_manager or ConfigManager()
    app_controller = AppController(
        None,  # main_window=None for now
        pipeline_runner=pipeline_runner,
        threaded=threaded,
        webui_process_manager=webui_manager,
        config_manager=config_manager,
    )

    window = MainWindowV2(
        root=root,
        app_state=app_state,
        webui_manager=webui_manager,
        app_controller=app_controller,
        packs_controller=None,
        pipeline_controller=app_controller.pipeline_controller,
        gui_log_handler=app_controller.get_gui_log_handler(),
    )

    # Now set the main_window on controller
    app_controller.set_main_window(window)

    return root, app_state, app_controller, window
