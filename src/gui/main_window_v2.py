# Used by tests and entrypoint contract
from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.api.webui_process_manager import WebUIProcessManager, build_default_webui_process_config
from src.gui.advanced_prompt_editor import AdvancedPromptEditorV2
from src.gui.app_state_v2 import AppStateV2
from src.gui.dropdown_loader_v2 import DropdownLoader as DropdownLoaderV2
from src.gui.engine_settings_dialog import EngineSettingsDialog
from src.gui.gui_invoker import GuiInvoker
from src.gui.layout_v2 import configure_root_grid
from src.gui.log_trace_panel_v2 import LogTracePanelV2
from src.gui.status_bar_v2 import StatusBarV2
from src.gui.theme_v2 import BACKGROUND_ELEVATED, TEXT_PRIMARY, apply_theme
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.gui.views.movie_clips_tab_frame_v2 import MovieClipsTabFrameV2
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from src.gui.views.photo_optimize_tab_frame_v2 import PhotoOptimizeTabFrame
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.gui.views.svd_tab_frame_v2 import SVDTabFrameV2
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.gui.zone_map_v2 import get_root_zone_config
from src.services.ui_state_store import get_ui_state_store
from src.utils import InMemoryLogHandler
from src.utils.config import ConfigManager

logger = logging.getLogger(__name__)

_WINDOW_SENTINEL_OFFSCREEN = -10000


class HeaderZone(ttk.Frame):
    def __init__(self, master: tk.Misc):
        super().__init__(master, style="Panel.TFrame")
        self.run_button = ttk.Button(self, text="Run", style="Primary.TButton")
        self.stop_button = ttk.Button(self, text="Stop", style="Secondary.TButton")
        self.preview_button = ttk.Button(self, text="Preview", style="Secondary.TButton")
        self.settings_button = ttk.Button(self, text="Settings", style="Secondary.TButton")
        self.refresh_button = ttk.Button(self, text="Refresh", style="Secondary.TButton")
        self.help_button = ttk.Button(self, text="Help Mode: Off", style="Secondary.TButton")
        self.debug_button = ttk.Button(self, text="Debug", style="Secondary.TButton")

        for idx, btn in enumerate(
            [
                self.run_button,
                self.stop_button,
                self.preview_button,
                self.settings_button,
                self.refresh_button,
                self.help_button,
                self.debug_button,
            ]
        ):
            btn.grid(row=0, column=idx, padx=4, pady=4)


class LeftZone(ttk.Frame):
    def __init__(self, master: tk.Misc):
        super().__init__(master, style="Panel.TFrame")
        self.load_pack_button = ttk.Button(self, text="Load Pack")
        self.edit_pack_button = ttk.Button(self, text="Edit Pack")
        self.packs_list = tk.Listbox(self, exportselection=False)
        self.preset_combo = ttk.Combobox(self, values=[])

        self.load_pack_button.pack(fill="x", padx=4, pady=2)
        self.edit_pack_button.pack(fill="x", padx=4, pady=2)
        self.packs_list.pack(fill="both", expand=True, padx=4, pady=4)
        ttk.Label(self, text="Preset").pack(anchor="w", padx=4)
        self.preset_combo.pack(fill="x", padx=4, pady=2)


class BottomZone(ttk.Frame):
    def __init__(self, master: tk.Misc, *, controller=None, app_state=None):
        super().__init__(master, style="StatusBar.TFrame")
        self.status_bar_v2 = StatusBarV2(self, controller=controller, app_state=app_state)
        self.status_bar_v2.grid(row=1, column=0, sticky="ew")

        # Compatibility aliases expected by AppController-based tests.
        self.api_status_label = getattr(
            getattr(self.status_bar_v2, "webui_panel", None), "status_label", None
        )
        if self.api_status_label is None:
            self.api_status_label = ttk.Label(self, text="API: Unknown", style="StatusBar.TLabel")
        self.status_label = getattr(
            self.status_bar_v2, "status_label", ttk.Label(self, text="Status: Idle")
        )

        log_style_kwargs = {
            "bg": BACKGROUND_ELEVATED,
            "fg": TEXT_PRIMARY,
            "insertbackground": TEXT_PRIMARY,
        }
        self.log_text = tk.Text(self, height=10, **log_style_kwargs)
        self.log_text.grid_forget()

        # Configure grid weights
        self.rowconfigure(0, weight=1)  # log panel
        self.rowconfigure(1, weight=0)  # status bar
        self.columnconfigure(0, weight=1)


DEFAULT_MAIN_WINDOW_WIDTH = int(PipelineTabFrame.DEFAULT_COLUMN_WIDTH * 3.1)
DEFAULT_MAIN_WINDOW_HEIGHT = int(900 * 1.5)
MIN_MAIN_WINDOW_WIDTH = DEFAULT_MAIN_WINDOW_WIDTH
MIN_MAIN_WINDOW_HEIGHT = int(740 * 1.5)


class MainWindowV2:
    """Minimal V2 spine used by legacy controllers and new app entrypoint."""

    def __init__(
        self,
        root: tk.Tk,
        app_state: AppStateV2 | None = None,
        webui_manager: WebUIProcessManager | None = None,
        app_controller=None,
        packs_controller=None,
        pipeline_controller=None,
        gui_log_handler: InMemoryLogHandler | None = None,
    ) -> None:
        self.root = root
        self._disposed = False
        self._close_in_progress = False
        self._graceful_exit_handler: Callable[[str], None] | None = None
        self.app_state = app_state or AppStateV2()
        self.webui_process_manager = webui_manager
        self.app_controller = app_controller
        self.packs_controller = packs_controller
        self.pipeline_controller = pipeline_controller
        self.gui_log_handler = gui_log_handler
        self._invoker = GuiInvoker(self.root)
        self.app_state.set_invoker(self._invoker)

        self.root.title("StableNew V2 (Spine)")
        self._ensure_window_geometry()

        apply_theme(self.root)
        configure_root_grid(self.root)

        # --- Create and grid all V2 zones ---
        self.header_zone = HeaderZone(self.root)
        self.header_zone.grid(**get_root_zone_config("header"))

        self.center_notebook = ttk.Notebook(self.root)
        self.center_notebook.grid(**get_root_zone_config("main"))
        # Registry to ensure a single authoritative tab instance per id
        self._tab_registry: dict[str, tk.Widget] = {}

        # Prompt tab (compatibility for journey tests / prompt workspace access)
        self.prompt_tab = PromptTabFrame(self.center_notebook, app_state=self.app_state)
        self.add_tab("prompt", "Prompt", self.prompt_tab)

        # PR-CORE1-D14: Always create and assign pipeline_tab for test/compat
        from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame

        # Use the registry to prevent duplicate pipeline tabs
        def _make_pipeline(parent):
            # Construct the richer PipelineTabFrame with available context so dropdowns and panels populate
            try:
                tab = PipelineTabFrame(
                    parent,
                    prompt_workspace_state=getattr(self, "prompt_workspace_state", None),
                    app_state=self.app_state,
                    app_controller=self.app_controller,
                    pipeline_controller=self.pipeline_controller,
                    theme=getattr(self, "theme", None),
                )
            except Exception:
                # Fallback to minimal constructor
                tab = PipelineTabFrame(parent)
            # Also ensure pipeline_controller attribute is set if present
            if (
                hasattr(tab, "pipeline_controller")
                and getattr(tab, "pipeline_controller", None) is None
            ):
                try:
                    tab.pipeline_controller = self.pipeline_controller
                except Exception:
                    pass
            return tab

        existing_pipeline_tab = self._tab_registry.get("pipeline")
        if existing_pipeline_tab is not None:
            self.pipeline_tab = existing_pipeline_tab
        else:
            self.pipeline_tab = self.add_tab("pipeline", "Pipeline", _make_pipeline)

        # Learning tab (optional; attach via registry)
        def _make_learning(parent):
            import logging
            logger = logging.getLogger(__name__)            
            logger.info("[MainWindow] Creating LearningTabFrame")
            
            # Create with full parameters - no fallback, fail fast on errors
            tab = LearningTabFrame(
                parent,
                app_state=self.app_state,
                pipeline_controller=self.pipeline_controller,
                app_controller=self.app_controller,
            )
            
            logger.info("[MainWindow] LearningTabFrame created successfully")
            return tab
            # Wire controller if present
            if hasattr(tab, "controller"):
                try:
                    tab.controller = self.app_controller or self.pipeline_controller
                except Exception:
                    pass
            return tab

        self.learning_tab = self.add_tab("learning", "Learning", _make_learning)
        self._restore_learning_tab_state()

        def _make_review(parent):
            return ReviewTabFrame(
                parent,
                app_controller=self.app_controller,
                app_state=self.app_state,
            )

        self.review_tab = self.add_tab("review", "Review", _make_review)

        def _make_photo_optimize(parent):
            return PhotoOptimizeTabFrame(
                parent,
                app_controller=self.app_controller,
                app_state=self.app_state,
            )

        self.photo_optimize_tab = self.add_tab("photo_optimize", "Photo Optomize", _make_photo_optimize)
        self._restore_photo_optimize_tab_state()

        def _make_movie_clips(parent):
            return MovieClipsTabFrameV2(
                parent,
                app_controller=self.app_controller,
                app_state=self.app_state,
            )

        self.movie_clips_tab = self.add_tab("movie_clips", "Movie Clips", _make_movie_clips)
        self._restore_movie_clips_tab_state()

        def _make_svd(parent):
            return SVDTabFrameV2(
                parent,
                app_controller=self.app_controller,
                app_state=self.app_state,
            )

        self.svd_tab = self.add_tab("svd", "SVD Img2Vid", _make_svd)
        self._restore_svd_tab_state()

        def _make_video_workflow(parent):
            return VideoWorkflowTabFrameV2(
                parent,
                app_controller=self.app_controller,
                app_state=self.app_state,
            )

        self.video_workflow_tab = self.add_tab(
            "video_workflow",
            "Video Workflow",
            _make_video_workflow,
        )
        self._restore_video_workflow_tab_state()

        # PR-PERSIST-001: Restore selected tab
        self._restore_tab_selection()

        self.left_zone = None
        self.right_zone = None

        self.bottom_zone = BottomZone(
            self.root, controller=self.app_controller, app_state=self.app_state
        )
        self.bottom_zone.grid(**get_root_zone_config("status"))
        self.status_bar_v2 = getattr(self.bottom_zone, "status_bar_v2", None)

        gui_log_handler = getattr(self, "gui_log_handler", None)
        self.log_trace_panel_v2: LogTracePanelV2 | None = None
        if self.gui_log_handler is not None:
            bundle_cmd = getattr(self.app_controller, "generate_diagnostics_bundle_manual", None)
            self.log_trace_panel_v2 = LogTracePanelV2(
                self.bottom_zone,
                log_handler=self.gui_log_handler,
                on_generate_bundle=bundle_cmd,
                audience="operator",
            )
            self.log_trace_panel_v2.grid(row=0, column=0, sticky="nsew")

        # --- Attach panels to zones ---
        import os

        self._is_test_mode = (
            bool(os.environ.get("PYTEST_CURRENT_TEST"))
            or os.environ.get("STABLENEW_TEST_MODE") == "1"
        )
        from src.gui.panels_v2.layout_manager_v2 import LayoutManagerV2

        self.layout_manager_v2 = LayoutManagerV2(self)
        # In tests we still attach panels so UI smoke tests can assert existence
        # of standard tabs. Always attach panels here for test harnesses.
        try:
            self.layout_manager_v2.attach_panels()
        except Exception:
            # Protect tests from attachment errors
            pass

        self.left_zone = getattr(self.pipeline_tab, "pack_loader_compat", None)
        self.right_zone = getattr(self.pipeline_tab, "preview_panel", None)
        self.sidebar_panel_v2 = getattr(self.pipeline_tab, "sidebar", None)

        self._dropdown_loader_v2 = DropdownLoaderV2(
            getattr(self.app_controller, "_config_manager", None)
        )
        if not hasattr(self.pipeline_tab, "apply_webui_resources"):

            def _apply_pipeline_resources(resources: dict[str, list[Any]] | None) -> None:
                self._dropdown_loader_v2.apply(resources, pipeline_tab=self.pipeline_tab)

            try:
                self.pipeline_tab.apply_webui_resources = _apply_pipeline_resources
            except Exception:
                pass

        # Provide delegation helpers expected by controllers/tests
        self.after = self.root.after  # type: ignore[attr-defined]

        self._wire_toolbar_callbacks()
        self._wire_status_bar()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        try:
            self.root.bind("<Destroy>", self._on_destroy, add="+")
        except Exception:
            pass

        # --- UI Heartbeat: Tk thread liveness signal ---
        self._install_ui_heartbeat()
        
        # Trigger deferred queue autostart after the GUI renders so restored
        # queued jobs actually resume when auto-run was enabled before shutdown.
        self.root.after(100, self._trigger_deferred_queue_autostart)

    def _trigger_deferred_queue_autostart(self) -> None:
        """Trigger deferred queue autostart after GUI is fully rendered."""
        logger.info("[STARTUP-PERF] Attempting to trigger deferred queue autostart...")
        try:
            webui_ctrl = getattr(getattr(self, "app_controller", None), "webui_connection_controller", None)
            is_ready = getattr(webui_ctrl, "is_webui_ready_strict", None)
            if callable(is_ready) and not is_ready():
                logger.info("[STARTUP-PERF] WebUI not strictly ready yet; deferring queue autostart until READY callback")
                return
            # Access JobExecutionController via pipeline_controller
            if not self.pipeline_controller:
                logger.warning("[STARTUP-PERF] No pipeline_controller available")
                return
            if not hasattr(self.pipeline_controller, '_job_controller'):
                logger.warning("[STARTUP-PERF] pipeline_controller has no _job_controller attribute")
                return
            
            job_controller = self.pipeline_controller._job_controller
            if not job_controller:
                logger.warning("[STARTUP-PERF] _job_controller is None")
                return
            if not hasattr(job_controller, 'trigger_deferred_autostart'):
                logger.warning("[STARTUP-PERF] job_controller has no trigger_deferred_autostart method")
                return
            
            logger.info("[STARTUP-PERF] Calling trigger_deferred_autostart()...")
            job_controller.trigger_deferred_autostart()
            logger.info("[STARTUP-PERF] Deferred autostart trigger completed")
        except Exception:
            # Log but don't crash GUI if autostart fails
            logger.exception("[STARTUP-PERF] Failed to trigger deferred queue autostart")

    def run_in_main_thread(self, cb: Callable[[], None]) -> None:
        """Schedule the callback on the Tk main thread (safe from any thread)."""
        if getattr(self, "root", None) is not None:
            try:
                self.root.after(0, cb)
                return
            except Exception:
                pass
        cb()

    def add_tab(self, tab_id: str, title: str, frame_or_factory: Any) -> tk.Widget:
        """Add a tab only if not already present. Accepts a frame instance or a factory(parent)->frame."""
        if tab_id in self._tab_registry:
            return self._tab_registry[tab_id]
        # Create the frame if a factory was provided
        try:
            if callable(frame_or_factory):
                frame = frame_or_factory(self.center_notebook)
            else:
                frame = frame_or_factory
        except Exception:
            # Best-effort: fall back to a simple empty frame
            try:
                frame = ttk.Frame(self.center_notebook)
            except Exception:
                frame = tk.Frame(self.center_notebook)
        try:
            self.center_notebook.add(frame, text=title)
        except Exception:
            pass
        self._tab_registry[tab_id] = frame
        return frame

    def get_tab(self, tab_id: str) -> Any:
        return self._tab_registry.get(tab_id)

    def _install_ui_heartbeat(self):
        """Install UI heartbeat ticker that runs every 250ms.
        
        PR-HB-003: Enhanced with diagnostic logging and operation tracking.
        """
        tick_count = 0
        last_operation = None
        
        def _tick():
            nonlocal tick_count, last_operation
            tick_count += 1
            
            # Update controller heartbeat timestamp
            if self.app_controller and hasattr(self.app_controller, "update_ui_heartbeat"):
                self.app_controller.update_ui_heartbeat()
            
            # PR-HB-003: Log heartbeat diagnostics periodically or when operation changes
            if self.app_controller:
                current_op = getattr(self.app_controller, "current_operation_label", None)
                
                # Log every 20 ticks (5 seconds) or when operation changes
                should_log = (tick_count % 20 == 0) or (current_op != last_operation and current_op is not None)
                
                if should_log:
                    import logging
                    logger = logging.getLogger(__name__)
                    op_text = current_op if current_op else "idle"
                    logger.debug(f"[UI] heartbeat tick #{tick_count} op={op_text}")
                    last_operation = current_op
            
            self.root.after(250, _tick)

        self.root.after(250, _tick)

    # Compatibility hook for controllers
    def connect_controller(self, controller) -> None:
        self.controller = controller
        if self.app_controller is None:
            self.app_controller = controller
            self._wire_toolbar_callbacks()
        if getattr(self, "status_bar_v2", None):
            try:
                self.status_bar_v2.controller = controller
            except Exception:
                pass
        try:
            self.app_state.controller = controller
        except Exception:
            pass

        if hasattr(self, "pipeline_tab") and hasattr(self.pipeline_tab, "sidebar"):
            try:
                self.pipeline_tab.sidebar.controller = controller
                base_generation_panel = getattr(self.pipeline_tab.sidebar, "base_generation_panel", None)
                if base_generation_panel and hasattr(base_generation_panel, "_controller"):
                    base_generation_panel._controller = controller
            except Exception:
                pass
        # Update run_controls with the controller
        if hasattr(self, "pipeline_tab") and hasattr(self.pipeline_tab, "run_controls"):
            try:
                self.pipeline_tab.run_controls.controller = controller
            except Exception:
                pass
        # Update preview_panel with the controller
        if hasattr(self, "pipeline_tab") and hasattr(self.pipeline_tab, "preview_panel"):
            try:
                self.pipeline_tab.preview_panel.controller = controller
            except Exception:
                pass
        if hasattr(self, "review_tab"):
            try:
                self.review_tab.app_controller = controller
            except Exception:
                pass
        if hasattr(self, "photo_optimize_tab"):
            try:
                self.photo_optimize_tab.app_controller = controller
                bind_app_state = getattr(self.photo_optimize_tab, "bind_app_state", None)
                if callable(bind_app_state):
                    bind_app_state(self.app_state)
                else:
                    self.photo_optimize_tab.app_state = self.app_state
            except Exception:
                pass
        if hasattr(self, "video_workflow_tab"):
            try:
                self.video_workflow_tab.app_controller = controller
                self.video_workflow_tab.app_state = self.app_state
            except Exception:
                pass
        if hasattr(self, "movie_clips_tab"):
            try:
                self.movie_clips_tab.app_controller = controller
                self.movie_clips_tab.app_state = self.app_state
            except Exception:
                pass

    def _ensure_window_geometry(self) -> None:
        """Apply default geometry/minimums so the three-column layout is visible."""
        # PR-PERSIST-001: Try to restore saved window geometry
        ui_store = get_ui_state_store()
        state = ui_store.load_state()
        restored = False
        
        if state:
            window_state = state.get("window", {})
            saved_geometry = window_state.get("geometry")
            saved_state = window_state.get("state")
            learning_state = state.get("learning", {})
            if isinstance(learning_state, dict):
                try:
                    self.app_state.set_learning_enabled(bool(learning_state.get("enabled", True)))
                except Exception:
                    pass
            
            if saved_geometry:
                try:
                    if self._is_window_geometry_visible(saved_geometry):
                        self.root.geometry(saved_geometry)
                        restored = True
                        logger.debug(f"Restored window geometry: {saved_geometry}")
                    else:
                        logger.warning(
                            "Ignoring saved off-screen window geometry: %s",
                            saved_geometry,
                        )
                except Exception as e:
                    logger.warning(f"Failed to restore window geometry: {e}")
            
            if saved_state == "zoomed":
                try:
                    self.root.state("zoomed")
                except Exception:
                    pass
        
        # If not restored, check current size and apply defaults if needed
        if not restored:
            try:
                geom = self.root.geometry()
                width_str, rest = geom.split("x", 1)
                width = int(width_str)
                height_str = rest.split("+", 1)[0]
                height = int(height_str)
            except Exception:
                width = 0
                height = 0

            if width < MIN_MAIN_WINDOW_WIDTH or height < MIN_MAIN_WINDOW_HEIGHT:
                self.root.geometry(f"{DEFAULT_MAIN_WINDOW_WIDTH}x{DEFAULT_MAIN_WINDOW_HEIGHT}")

        self.root.minsize(MIN_MAIN_WINDOW_WIDTH, MIN_MAIN_WINDOW_HEIGHT)
        try:
            self.root.deiconify()
        except Exception:
            pass

    def _parse_window_geometry(self, geometry: str) -> tuple[int, int, int | None, int | None] | None:
        text = str(geometry or "").strip()
        if "x" not in text:
            return None
        try:
            width_str, remainder = text.split("x", 1)
            width = int(width_str)
            x = y = None
            if "+" in remainder:
                height_str, x_str, y_str = remainder.split("+", 2)
                height = int(height_str)
                x = int(x_str)
                y = int(y_str)
            else:
                height = int(remainder)
            return width, height, x, y
        except Exception:
            return None

    def _is_window_geometry_visible(self, geometry: str) -> bool:
        parsed = self._parse_window_geometry(geometry)
        if parsed is None:
            return False
        width, height, x, y = parsed
        if width < MIN_MAIN_WINDOW_WIDTH or height < MIN_MAIN_WINDOW_HEIGHT:
            return False
        if x is None or y is None:
            return True
        if x <= _WINDOW_SENTINEL_OFFSCREEN or y <= _WINDOW_SENTINEL_OFFSCREEN:
            return False
        try:
            screen_width = int(self.root.winfo_screenwidth() or 0)
            screen_height = int(self.root.winfo_screenheight() or 0)
        except Exception:
            screen_width = 0
            screen_height = 0
        if screen_width <= 0 or screen_height <= 0:
            return True
        margin_x = 80
        margin_y = 60
        return (
            x < screen_width - margin_x
            and y < screen_height - margin_y
            and (x + width) > margin_x
            and (y + height) > margin_y
        )

    def update_pack_list(self, packs: list[str]) -> None:
        left = getattr(self, "left_zone", None)
        if hasattr(left, "set_pack_names"):
            try:
                left.set_pack_names(packs)
                return
            except Exception:
                pass
        lb = getattr(left, "packs_list", None)
        if lb is None:
            return
        lb.delete(0, "end")
        for name in packs:
            lb.insert("end", name)

    def _wire_toolbar_callbacks(self) -> None:
        header = getattr(self, "header_zone", None)
        if header is None:
            return
        # Prefer the lightweight AppController wiring if provided
        ctrl = self.app_controller
        if ctrl:
            for attr, btn in [
                ("on_run_clicked", header.run_button),
                ("on_stop_clicked", header.stop_button),
                ("on_preview_clicked", header.preview_button),
                ("on_open_settings", header.settings_button),
                ("on_refresh_clicked", header.refresh_button),
                ("on_help_clicked", header.help_button),
                ("open_debug_hub", header.debug_button),
            ]:
                callback = getattr(ctrl, attr, None)
                if callable(callback):
                    try:
                        btn.configure(command=callback)
                    except Exception:
                        pass
        else:
            # Best-effort fallback wiring using pipeline/pack controllers
            if self.pipeline_controller:
                start_cb = getattr(self.pipeline_controller, "start_pipeline", None) or getattr(
                    self.pipeline_controller, "start", None
                )
                stop_cb = getattr(self.pipeline_controller, "stop_pipeline", None) or getattr(
                    self.pipeline_controller, "stop", None
                )
                if callable(start_cb):
                    header.run_button.configure(command=start_cb)
                if callable(stop_cb):
                    header.stop_button.configure(command=stop_cb)
            header.help_button.configure(command=self._toggle_help_mode)

        if getattr(self, "app_state", None) and hasattr(self.app_state, "subscribe"):
            try:
                self.app_state.subscribe("preview_jobs", self._update_run_button_state)
            except Exception:
                pass
            try:
                self.app_state.subscribe("current_pack", self._update_run_button_state)
            except Exception:
                pass
            try:
                self.app_state.subscribe("help_mode", self._update_help_button_state)
            except Exception:
                pass
        self._update_run_button_state()
        self._update_help_button_state()

    def _update_run_button_state(self, *_: Any) -> None:
        header = getattr(self, "header_zone", None)
        if header is None:
            return
        button = getattr(header, "run_button", None)
        if button is None or not hasattr(button, "state"):
            return
        app_state = getattr(self, "app_state", None)
        can_run = False
        if app_state is not None:
            has_pack = bool(getattr(app_state, "current_pack", None))
            preview_jobs = getattr(app_state, "preview_jobs", None) or []
            can_run = bool(has_pack and preview_jobs)
        if can_run:
            button.state(["!disabled"])
        else:
            button.state(["disabled"])

    def _toggle_help_mode(self) -> None:
        app_state = getattr(self, "app_state", None)
        if app_state is None:
            return
        toggle = getattr(app_state, "toggle_help_mode", None)
        if callable(toggle):
            toggle()

    def _update_help_button_state(self, *_: Any) -> None:
        header = getattr(self, "header_zone", None)
        if header is None:
            return
        button = getattr(header, "help_button", None)
        if button is None:
            return
        enabled = bool(getattr(self.app_state, "help_mode_enabled", False))
        button.configure(text=f"Help Mode: {'On' if enabled else 'Off'}")

    def set_graceful_exit_handler(self, handler: Callable[[str], None] | None) -> None:
        """Register the handler used for canonical shutdown."""

        self._graceful_exit_handler = handler

    def _wire_left_zone_callbacks(self) -> None:
        left = getattr(self, "left_zone", None)
        if left is None:
            return

        ctrl = self.packs_controller or self.app_controller
        if not ctrl:
            return

        if hasattr(left, "load_pack_button"):
            cb = getattr(ctrl, "on_load_pack", None) or getattr(ctrl, "load_pack", None)
            if callable(cb):
                try:
                    left.load_pack_button.configure(command=cb)
                except Exception:
                    pass

        if hasattr(left, "edit_pack_button"):
            cb = getattr(ctrl, "on_edit_pack", None) or getattr(ctrl, "edit_pack", None)
            if callable(cb):
                try:
                    left.edit_pack_button.configure(command=cb)
                except Exception:
                    pass

        if hasattr(left, "packs_list") and callable(getattr(ctrl, "on_pack_selected", None)):
            try:
                left.packs_list.bind(
                    "<<ListboxSelect>>", lambda _e: self._handle_pack_selection(ctrl)
                )
            except Exception:
                pass

        if hasattr(left, "preset_combo") and callable(getattr(ctrl, "on_preset_selected", None)):
            try:
                left.preset_combo.bind(
                    "<<ComboboxSelected>>",
                    lambda _e: ctrl.on_preset_selected(left.preset_combo.get()),
                )
            except Exception:
                pass

    def _handle_pack_selection(self, ctrl) -> None:
        lb = getattr(getattr(self, "left_zone", None), "packs_list", None)
        if lb is None:
            return
        try:
            selection = lb.curselection()
            if selection:
                ctrl.on_pack_selected(int(selection[0]))
        except Exception:
            pass

    def _on_close(self) -> None:
        self._trigger_graceful_exit("window-close")

    def on_app_close(self) -> None:
        self._trigger_graceful_exit("window-close")

    def _trigger_graceful_exit(self, reason: str) -> None:
        handler = getattr(self, "_graceful_exit_handler", None)
        if handler:
            try:
                handler(reason)
            except Exception:
                pass
            return
        self._perform_legacy_shutdown(reason)

    def _perform_legacy_shutdown(self, reason: str) -> None:
        if self._close_in_progress:
            return
        self._close_in_progress = True
        controller = getattr(self, "app_controller", None)
        if getattr(self, "_invoker", None):
            try:
                self._invoker.dispose()
            except Exception:
                pass
        if controller:
            try:
                controller.shutdown_app(reason)
            except Exception:
                pass
        try:
            # Exit mainloop promptly to avoid Tk hanging on close.
            self.root.quit()
        except Exception:
            pass
        self.cleanup()
        try:
            self.root.after_idle(self._destroy_root)
        except Exception:
            self._destroy_root()

    def _destroy_root(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass

    def _on_destroy(self, event) -> None:
        if event is not None and getattr(event, "widget", None) not in {None, self.root}:
            return
        if not self._close_in_progress:
            self._trigger_graceful_exit("destroy")

    def cleanup(self) -> None:
        """Best-effort shutdown to make Tk teardown safe for tests and runtime."""
        if self._disposed:
            return
        self._disposed = True
        
        # PR-PERSIST-001: Save UI state before cleanup
        try:
            self._save_ui_state()
        except Exception as e:
            logger.warning(f"Failed to save UI state during cleanup: {e}")

        try:
            self.app_state.disable_notifications()
        except Exception:
            pass

        try:
            if self._invoker:
                self._invoker.dispose()
        except Exception:
            pass

        # Stop background work if controllers expose hooks.
        try:
            if self.pipeline_controller:
                stop = getattr(self.pipeline_controller, "stop_all", None) or getattr(
                    self.pipeline_controller, "shutdown", None
                )
                if callable(stop):
                    stop()
        except Exception:
            pass

        try:
            if self.app_controller:
                stop = getattr(self.app_controller, "stop_all_background_work", None) or getattr(
                    self.app_controller, "stop_all", None
                )
                if callable(stop):
                    stop()
        except Exception:
            pass

        try:
            controller_owns_shutdown = bool(getattr(self, "app_controller", None))
            if self.webui_process_manager and not controller_owns_shutdown:
                stop = getattr(self.webui_process_manager, "shutdown", None) or getattr(
                    self.webui_process_manager, "stop", None
                )
                if callable(stop):
                    stop()
        except Exception:
            pass

        try:
            comfy_manager = getattr(self, "comfy_process_manager", None)
            if comfy_manager:
                stop = getattr(comfy_manager, "shutdown", None) or getattr(comfy_manager, "stop", None)
                if callable(stop):
                    stop()
        except Exception:
            pass

    def _wire_status_bar(self) -> None:
        if not getattr(self, "status_bar_v2", None):
            return
        try:
            self.status_bar_v2.app_state = self.app_state
            if hasattr(self.app_state, "subscribe"):
                self.app_state.subscribe("status_text", self.status_bar_v2._sync_status_text)
            try:
                self.status_bar_v2._sync_status_text()
            except Exception:
                pass
        except Exception:
            pass

    def schedule_auto_exit(self, seconds: float) -> None:
        """Schedule the same close path used by the window-close button."""

        if seconds is None:
            return
        try:
            timeout_ms = int(max(0, float(seconds)) * 1000)
        except Exception:
            return
        if timeout_ms <= 0:
            return
        try:
            self.root.after(timeout_ms, lambda: self._trigger_graceful_exit("auto-exit"))
        except Exception:
            pass

    def _handle_apply_pack(self, prompt_text: str, summary) -> None:
        if getattr(self, "pipeline_panel", None) and hasattr(self.pipeline_panel, "set_prompt"):
            try:
                self.pipeline_panel.set_prompt(prompt_text or "")
            except Exception:
                pass
        if getattr(self, "app_state", None):
            try:
                pack_name = getattr(summary, "name", None)
                if pack_name:
                    self.app_state.set_current_pack(pack_name)
                    self.app_state.set_status_text(f"Pack applied: {pack_name}")
            except Exception:
                pass

    def open_advanced_editor(
        self,
        *,
        initial_prompt: str = "",
        initial_negative_prompt: str | None = None,
        on_apply: Callable[[str, str | None], None] | None = None,
    ) -> None:
        if not getattr(self, "root", None):
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Advanced Prompt Editor")
        dialog.transient(self.root)

        def _handle_apply(prompt_value: str, negative_value: str | None = None) -> None:
            if callable(on_apply):
                try:
                    on_apply(prompt_value, negative_value)
                except Exception:
                    pass
            try:
                dialog.destroy()
            except Exception:
                pass

        editor = AdvancedPromptEditorV2(
            dialog,
            initial_prompt=initial_prompt,
            initial_negative_prompt=initial_negative_prompt,
            on_apply=_handle_apply,
            on_cancel=lambda: dialog.destroy(),
        )
        editor.pack(fill=tk.BOTH, expand=True)
        try:
            dialog.grab_set()
        except Exception:
            pass

    def apply_prompt_text(self, prompt: str, negative_prompt: str | None = None) -> None:
        text = prompt or ""
        if getattr(self, "app_state", None):
            try:
                self.app_state.set_prompt(text)
            except Exception:
                pass
            if negative_prompt is not None:
                try:
                    self.app_state.set_negative_prompt(negative_prompt)
                except Exception:
                    pass

        prompt_tab = getattr(self, "prompt_tab", None)
        if prompt_tab and hasattr(prompt_tab, "apply_prompt_text"):
            try:
                prompt_tab.apply_prompt_text(text)
            except Exception:
                pass

    def open_engine_settings_dialog(self, *, config_manager: ConfigManager) -> None:
        if not getattr(self, "root", None):
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Engine Settings")
        dialog.transient(self.root)

        status = getattr(self.app_state, "webui_state", None)
        panel = EngineSettingsDialog(
            dialog,
            config_manager=config_manager,
            status_text=status,
            on_save=lambda values: self._handle_settings_saved(values, dialog),
            on_cancel=lambda: dialog.destroy(),
        )
        panel.pack(fill=tk.BOTH, expand=True)
        try:
            dialog.grab_set()
        except Exception:
            pass

    def _handle_settings_saved(self, values: dict[str, Any], dialog: tk.Toplevel) -> None:
        controller = getattr(self.app_state, "controller", None)
        if controller and hasattr(controller, "on_settings_saved"):
            try:
                controller.on_settings_saved(values)
            except Exception:
                pass
        try:
            dialog.destroy()
        except Exception:
            pass

    # PR-PERSIST-001: UI state persistence methods
    def _save_ui_state(self) -> None:
        """Save window geometry and tab selection to disk."""
        try:
            ui_store = get_ui_state_store()
            existing_state = ui_store.load_state() or {}
            
            # Get window geometry and state
            geometry = self.root.geometry()
            window_state = "normal"
            try:
                if self.root.state() == "zoomed":
                    window_state = "zoomed"
            except Exception:
                pass
            if window_state == "normal" and not self._is_window_geometry_visible(geometry):
                logger.warning(
                    "Skipping save of off-screen window geometry: %s",
                    geometry,
                )
                existing_window_state = existing_state.get("window", {})
                if isinstance(existing_window_state, dict):
                    preserved_geometry = existing_window_state.get("geometry")
                    if self._is_window_geometry_visible(str(preserved_geometry or "")):
                        geometry = str(preserved_geometry)
                    else:
                        geometry = f"{DEFAULT_MAIN_WINDOW_WIDTH}x{DEFAULT_MAIN_WINDOW_HEIGHT}"
                else:
                    geometry = f"{DEFAULT_MAIN_WINDOW_WIDTH}x{DEFAULT_MAIN_WINDOW_HEIGHT}"

            # Get selected tab index
            selected_tab_index = 0
            try:
                selected_tab_index = self.center_notebook.index(self.center_notebook.select())
            except Exception:
                pass
            
            state = {
                **existing_state,
                "window": {
                    "geometry": geometry,
                    "state": window_state
                },
                "tabs": {
                    "selected_index": selected_tab_index
                },
            }
            try:
                learning_tab = getattr(self, "learning_tab", None)
                getter = getattr(learning_tab, "get_learning_session_state", None)
                if callable(getter):
                    learning_state = getter()
                    if isinstance(learning_state, dict):
                        state["learning"] = learning_state
                    elif "learning" not in state:
                        state["learning"] = {}
            except Exception:
                if "learning" not in state:
                    state["learning"] = {}
            try:
                photo_tab = getattr(self, "photo_optimize_tab", None)
                photo_getter = getattr(photo_tab, "get_photo_optimize_state", None)
                if callable(photo_getter):
                    photo_state = photo_getter()
                    if isinstance(photo_state, dict):
                        state["photo_optimize"] = photo_state
                    elif "photo_optimize" not in state:
                        state["photo_optimize"] = {}
            except Exception:
                if "photo_optimize" not in state:
                    state["photo_optimize"] = {}
            try:
                clips_tab = getattr(self, "movie_clips_tab", None)
                clips_getter = getattr(clips_tab, "get_movie_clips_state", None)
                if callable(clips_getter):
                    clips_state = clips_getter()
                    if isinstance(clips_state, dict):
                        state["movie_clips"] = clips_state
                    elif "movie_clips" not in state:
                        state["movie_clips"] = {}
            except Exception:
                if "movie_clips" not in state:
                    state["movie_clips"] = {}
            try:
                svd_tab = getattr(self, "svd_tab", None)
                svd_getter = getattr(svd_tab, "get_svd_state", None)
                if callable(svd_getter):
                    svd_state = svd_getter()
                    if isinstance(svd_state, dict):
                        state["svd"] = svd_state
                    elif "svd" not in state:
                        state["svd"] = {}
            except Exception:
                if "svd" not in state:
                    state["svd"] = {}
            try:
                video_tab = getattr(self, "video_workflow_tab", None)
                video_getter = getattr(video_tab, "get_video_workflow_state", None)
                if callable(video_getter):
                    video_state = video_getter()
                    if isinstance(video_state, dict):
                        state["video_workflow"] = video_state
                    elif "video_workflow" not in state:
                        state["video_workflow"] = {}
            except Exception:
                if "video_workflow" not in state:
                    state["video_workflow"] = {}

            ui_store.save_state(state)
            logger.debug(f"Saved UI state: geometry={geometry}, tab={selected_tab_index}")
        except Exception as e:
            logger.warning(f"Failed to save UI state: {e}")

    def _restore_tab_selection(self) -> None:
        """Restore previously selected tab."""
        try:
            ui_store = get_ui_state_store()
            state = ui_store.load_state()
            
            if state:
                tabs_state = state.get("tabs", {})
                selected_index = tabs_state.get("selected_index", 0)
                
                # Validate index is in range
                tab_count = self.center_notebook.index("end")
                if 0 <= selected_index < tab_count:
                    self.center_notebook.select(selected_index)
                    logger.debug(f"Restored tab selection: index {selected_index}")
        except Exception as e:
            logger.warning(f"Failed to restore tab selection: {e}")

    def _restore_learning_tab_state(self) -> None:
        """Restore persisted learning tab state."""
        try:
            ui_store = get_ui_state_store()
            state = ui_store.load_state() or {}
            learning_state = state.get("learning")
            learning_tab = getattr(self, "learning_tab", None)
            restore = getattr(learning_tab, "restore_learning_session_state", None)
            if callable(restore):
                restore(learning_state)
        except Exception as e:
            logger.warning(f"Failed to restore learning tab state: {e}")

    def _restore_photo_optimize_tab_state(self) -> None:
        """Restore persisted Photo Optomize tab state."""
        try:
            ui_store = get_ui_state_store()
            state = ui_store.load_state() or {}
            photo_state = state.get("photo_optimize")
            photo_tab = getattr(self, "photo_optimize_tab", None)
            restore = getattr(photo_tab, "restore_photo_optimize_state", None)
            if callable(restore):
                restore(photo_state)
        except Exception as e:
            logger.warning(f"Failed to restore Photo Optomize tab state: {e}")

    def _restore_movie_clips_tab_state(self) -> None:
        """Restore persisted Movie Clips tab state."""
        try:
            ui_store = get_ui_state_store()
            state = ui_store.load_state() or {}
            clips_state = state.get("movie_clips")
            tab = getattr(self, "movie_clips_tab", None)
            restore = getattr(tab, "restore_movie_clips_state", None)
            if callable(restore):
                restore(clips_state)
        except Exception as e:
            logger.warning(f"Failed to restore Movie Clips tab state: {e}")

    def _restore_svd_tab_state(self) -> None:
        """Restore persisted SVD tab state."""
        try:
            ui_store = get_ui_state_store()
            state = ui_store.load_state() or {}
            svd_state = state.get("svd")
            tab = getattr(self, "svd_tab", None)
            restore = getattr(tab, "restore_svd_state", None)
            if callable(restore):
                restore(svd_state)
        except Exception as e:
            logger.warning(f"Failed to restore SVD tab state: {e}")

    def _restore_video_workflow_tab_state(self) -> None:
        """Restore persisted Video Workflow tab state."""
        try:
            ui_store = get_ui_state_store()
            state = ui_store.load_state() or {}
            video_state = state.get("video_workflow")
            tab = getattr(self, "video_workflow_tab", None)
            restore = getattr(tab, "restore_video_workflow_state", None)
            if callable(restore):
                restore(video_state)
        except Exception as e:
            logger.warning(f"Failed to restore Video Workflow tab state: {e}")


def run_app(
    root: tk.Tk | None = None,
    webui_manager: WebUIProcessManager | None = None,
    app_controller=None,
    packs_controller=None,
    pipeline_controller=None,
) -> None:
    """Launch the V2 application shell."""

    if root is None:
        root = tk.Tk()

    if webui_manager is None:
        proc_config = build_default_webui_process_config()
        if proc_config:
            webui_manager = WebUIProcessManager(proc_config)
            if proc_config.autostart_enabled:
                try:
                    webui_manager.start()
                except Exception:
                    pass

    app_state = AppStateV2()
    MainWindowV2(
        root=root,
        app_state=app_state,
        webui_manager=webui_manager,
        app_controller=app_controller,
        packs_controller=packs_controller,
        pipeline_controller=pipeline_controller,
    )
    root.mainloop()


# Backward-compatible alias expected by controllers/tests
MainWindow = MainWindowV2
ENTRYPOINT_GUI_CLASS = MainWindowV2
