from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

from src.api.webui_process_manager import WebUIProcessManager
from src.app.bootstrap import build_gui_kernel
from src.config.app_config import get_job_history_path
from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.main_window_v2 import MainWindowV2
from src.gui.ui_dispatcher import TkUiDispatcher
from src.runtime_host import (
    RuntimeHostPort,
    coerce_runtime_host,
    launch_child_runtime_host_client,
)
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
    runtime_host: RuntimeHostPort | None = None,
    launch_runtime_host: bool = False,
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
        runtime_host: Optional runtime-host seam. If omitted, any injected
            JobService is wrapped as a local runtime host.

    Returns (root, app_state, app_controller, window).
    """

    if root is None:
        root = tk.Tk()
    ui_dispatcher = TkUiDispatcher(root)

    app_state = AppStateV2()

    # Create controller first to get gui_log_handler
    config_manager = config_manager or ConfigManager()
    kernel = build_gui_kernel(
        config_manager=config_manager,
        structured_logger=None,
    )
    created_runtime_host = None
    resolved_runtime_host = coerce_runtime_host(runtime_host or job_service)
    if (
        resolved_runtime_host is None
        and launch_runtime_host
        and job_service is None
        and pipeline_runner is None
    ):
        created_runtime_host = launch_child_runtime_host_client(
            history_path=get_job_history_path(),
        )
        resolved_runtime_host = created_runtime_host

    try:
        app_controller = AppController(
            None,  # main_window=None for now
            pipeline_runner=pipeline_runner or kernel.pipeline_runner,
            threaded=threaded,
            ui_scheduler=ui_dispatcher.invoke,
            webui_process_manager=webui_manager,
            config_manager=kernel.config_manager,
            job_service=job_service,  # PR-0114C-Ty: DI for tests
            runtime_host=resolved_runtime_host,
            api_client=kernel.api_client,
            structured_logger=kernel.structured_logger,
            runtime_ports=kernel.runtime_ports,
            optional_dependency_snapshot=kernel.capabilities,
        )
    except Exception:
        if created_runtime_host is not None and hasattr(created_runtime_host, "stop"):
            try:
                created_runtime_host.stop()
            except Exception:
                pass
        raise
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
    try:
        window = MainWindowV2(
            root=root,
            app_state=app_state,
            webui_manager=webui_manager,
            app_controller=app_controller,
            packs_controller=None,
            pipeline_controller=pipeline_controller,
            gui_log_handler=app_controller.get_gui_log_handler(),
        )
    except Exception:
        if created_runtime_host is not None and hasattr(created_runtime_host, "stop"):
            try:
                created_runtime_host.stop()
            except Exception:
                pass
        raise

    # Now set the main_window on controller
    app_controller.set_main_window(window)

    return root, app_state, app_controller, window
