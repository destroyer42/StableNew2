from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

from src.api.webui_process_manager import WebUIProcessManager
from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.main_window_v2 import MainWindowV2
from src.utils.config import ConfigManager

if TYPE_CHECKING:
    from src.controller.job_service import JobService


from typing import Any


def build_v2_app(
    *,
    root: tk.Tk | None = None,
    pipeline_runner: Any | None = None,
    webui_manager: WebUIProcessManager | None = None,
    threaded: bool = False,
    config_manager: ConfigManager | None = None,
    job_service: JobService | None = None,
) -> tuple[tk.Tk, AppStateV2, AppController, MainWindowV2]:
    """
    Build the V2 application stack with injectable runner for tests.

    PR-0114C-Ty: Added job_service parameter for DI in tests.
    Tests can pass a JobService with StubRunner/NullHistoryService to avoid
    real pipeline execution.

    Args:
        root: Optional Tk root window.
        pipeline_runner: Optional pipeline runner (usually None for tests).
        webui_manager: Optional WebUI process manager.
        threaded: Whether to use threaded mode.
        config_manager: Optional config manager.
        job_service: Optional JobService. If None, AppController creates a real one.
            Tests should pass a stubbed JobService to avoid real execution.

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
        job_service=job_service,  # PR-0114C-Ty: DI for tests
    )
    # --- BEGIN PR-CORE1-D21A: Diagnostics/Watchdog wiring ---
    # DiagnosticsServiceV2 and SystemWatchdogV2 are now initialized in AppController
    # --- END PR-CORE1-D21A ---

    # --- BEGIN PR-CORE1-D21A: Diagnostics/Watchdog wiring ---
    from pathlib import Path

    from src.services.diagnostics_service_v2 import DiagnosticsServiceV2

    diagnostics_service = DiagnosticsServiceV2(Path("reports") / "diagnostics")
    app_controller.attach_watchdog(diagnostics_service)
    # --- END PR-CORE1-D21A ---

    # Ensure pipeline_controller is set before constructing MainWindowV2
    pipeline_controller = getattr(app_controller, "pipeline_controller", None)
    window = MainWindowV2(
        root=root,
        app_state=app_state,
        webui_manager=webui_manager,
        app_controller=app_controller,
        packs_controller=None,
        pipeline_controller=pipeline_controller,
        gui_log_handler=app_controller.get_gui_log_handler(),
    )

    # Now set the main_window on controller
    app_controller.set_main_window(window)

    return root, app_state, app_controller, window
