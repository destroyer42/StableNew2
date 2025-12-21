from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui import design_system_v2 as design_system
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.panels_v2.debug_log_panel_v2 import DebugLogPanelV2
from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.gui.panels_v2.running_job_panel_v2 import RunningJobPanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.state import PipelineState
from src.gui.theme_v2 import CARD_FRAME_STYLE, SURFACE_FRAME_STYLE
from src.gui.tooltip import attach_tooltip
from src.gui.views.diagnostics_dashboard_v2 import DiagnosticsDashboardV2
from src.gui.views.stage_cards_panel import StageCardsPanel
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui.zone_map_v2 import get_pipeline_stage_order
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.utils.process_inspector_v2 import format_process_brief, iter_stablenew_like_processes

logger = logging.getLogger(__name__)


class PipelineTabFrame(ttk.Frame):
    """Layout scaffold for the Pipeline tab."""

    DEFAULT_COLUMN_WIDTH = design_system.Spacing.XL * 40  # ~640
    MIN_COLUMN_WIDTH = design_system.Spacing.XL * 25  # ~400
    LOGGING_ROW_MIN_HEIGHT = design_system.Spacing.XL * 10
    LOGGING_ROW_WEIGHT = 1

    def __init__(
        self,
        master: tk.Misc,
        *,
        prompt_workspace_state: Any = None,
        app_state: Any = None,
        app_controller: Any = None,
        pipeline_controller: Any = None,
        theme: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.prompt_workspace_state = prompt_workspace_state
        self.app_state = app_state
        self.app_controller = app_controller
        self.pipeline_controller = pipeline_controller
        self.theme = theme
        self.state_manager = getattr(self.pipeline_controller, "state_manager", None)

        # Initialize pipeline state and enable variables for test compatibility
        self.pipeline_state = PipelineState()
        if self.pipeline_controller and self.app_state:
            try:
                self.pipeline_controller.bind_app_state(self.app_state)
            except Exception:
                pass

        self.rowconfigure(0, weight=1)
        for idx in range(3):
            self.columnconfigure(idx, weight=1, minsize=self.DEFAULT_COLUMN_WIDTH)

        def _create_card(parent: ttk.Frame) -> ttk.Frame:
            card = ttk.Frame(parent, padding=12, style=CARD_FRAME_STYLE)
            card.columnconfigure(0, weight=1)
            return card

        self.left_column = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.left_column.grid(row=0, column=0, sticky="nsew")
        self.left_column.rowconfigure(0, weight=1)
        self.left_column.columnconfigure(0, weight=1)
        self.left_scroll = ScrollableFrame(self.left_column, style=CARD_FRAME_STYLE)
        self.left_scroll.grid(row=0, column=0, sticky="nsew")
        self.left_inner = self.left_scroll.inner

        # PR-GUI-H: Remove redundant sidebar_card wrapper - SidebarPanelV2 directly in scroll inner
        self.sidebar = SidebarPanelV2(
            self.left_inner,
            controller=self.app_controller or self.pipeline_controller,
            app_state=self.app_state,
            theme=self.theme,
            on_change=lambda: self._handle_sidebar_change(),
        )
        self.sidebar.pack(fill="both", pady=(0, 12), expand=True)

        # PR-GUI-H: prompt_text and restore_last_run_button moved to sidebar Pack Selector card
        # Keep references for compatibility
        self.prompt_text = getattr(self.sidebar, "prompt_text", tk.Entry(self.left_inner))
        self.restore_last_run_button = getattr(self.sidebar, "restore_last_run_button", None)
        if self.prompt_text:
            attach_tooltip(self.prompt_text, "Primary text prompt for the active pipeline.")
        # JT05-friendly attribute for tracking the img2img/upscale input image path
        self.input_image_path: str = ""

        self.center_column = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.center_column.grid(row=0, column=1, sticky="nsew")
        self.center_column.rowconfigure(0, weight=1)
        self.center_column.columnconfigure(0, weight=1)
        self.stage_scroll = ScrollableFrame(self.center_column, style=CARD_FRAME_STYLE)
        self.stage_scroll.grid(row=0, column=0, sticky="nsew")
        self.stage_cards_frame = self.stage_scroll.inner

        self.right_column = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.right_column.grid(row=0, column=2, sticky="nsew")
        self.right_column.rowconfigure(0, weight=1)
        self.right_column.columnconfigure(0, weight=1)
        queue_controller = self.app_controller or self.pipeline_controller

        self.right_scroll = ScrollableFrame(self.right_column, style=CARD_FRAME_STYLE)
        self.right_scroll.grid(row=0, column=0, sticky="nsew")
        self.right_scroll.inner.columnconfigure(0, weight=1)
        self.right_scroll.inner.rowconfigure(0, weight=1)
        self.right_scroll.inner.rowconfigure(3, weight=1)  # History row gets weight

        preview_card = _create_card(self.right_scroll.inner)
        preview_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=(0, 8))
        preview_card.rowconfigure(0, weight=1)
        self.preview_panel = PreviewPanelV2(
            preview_card,
            controller=queue_controller,
            app_state=self.app_state,
            theme=self.theme,
        )
        self.preview_panel.grid(row=0, column=0, sticky="nsew")

        # PR-GUI-F1: Run Controls panel removed - controls moved to QueuePanelV2

        queue_card = _create_card(self.right_scroll.inner)
        queue_card.grid(row=1, column=0, sticky="ew", padx=(0, 12), pady=(0, 8))
        self.queue_panel = QueuePanelV2(
            queue_card,
            controller=queue_controller,
            app_state=self.app_state,
        )
        self.queue_panel.grid(row=0, column=0, sticky="ew")

        running_job_card = _create_card(self.right_scroll.inner)
        running_job_card.grid(row=2, column=0, sticky="ew", padx=(0, 12), pady=(0, 8))
        self.running_job_panel = RunningJobPanelV2(
            running_job_card,
            controller=queue_controller,
            app_state=self.app_state,
        )
        self.running_job_panel.grid(row=0, column=0, sticky="ew")

        history_card = _create_card(self.right_scroll.inner)
        history_card.grid(row=3, column=0, sticky="nsew", padx=(0, 12), pady=(0, 0))
        history_card.rowconfigure(0, weight=1)
        self.history_panel = JobHistoryPanelV2(
            history_card,
            controller=queue_controller,
            app_state=self.app_state,
            theme=self.theme,
        )
        self.history_panel.grid(row=0, column=0, sticky="nsew")

        self.right_scroll.inner.rowconfigure(4, weight=0)
        diagnostics_card = _create_card(self.right_scroll.inner)
        diagnostics_card.grid(row=4, column=0, sticky="ew", padx=(0, 12), pady=(0, 0))
        diagnostics_card.rowconfigure(0, weight=1)
        self.diagnostics_dashboard = DiagnosticsDashboardV2(
            diagnostics_card,
            controller=queue_controller,
            app_state=self.app_state,
        )
        self.diagnostics_dashboard.grid(row=0, column=0, sticky="nsew")

        self.stage_cards_panel = StageCardsPanel(
            self.stage_cards_frame,
            controller=self.pipeline_controller,
            theme=self.theme,
            app_state=self.app_state,
            on_change=lambda: self._sync_state_overrides(),
        )
        self.stage_cards_panel.pack(fill="both", expand=True)
        txt2img_card = getattr(self.stage_cards_panel, "txt2img_card", None)
        img2img_card = getattr(self.stage_cards_panel, "img2img_card", None)
        upscale_card = getattr(self.stage_cards_panel, "upscale_card", None)
        self.txt2img_width = getattr(txt2img_card, "width_var", tk.IntVar(value=512))
        self.txt2img_height = getattr(txt2img_card, "height_var", tk.IntVar(value=512))
        self.txt2img_steps = getattr(txt2img_card, "steps_var", tk.IntVar(value=20))
        self.txt2img_cfg_scale = getattr(txt2img_card, "cfg_var", tk.DoubleVar(value=7.0))
        self.img2img_width = getattr(img2img_card, "width_var", tk.IntVar(value=512))
        self.img2img_height = getattr(img2img_card, "height_var", tk.IntVar(value=512))
        self.img2img_strength = getattr(img2img_card, "denoise_var", tk.DoubleVar(value=0.3))
        self.upscale_scale = getattr(upscale_card, "factor_var", tk.DoubleVar(value=2.0))
        self.upscale_steps = getattr(upscale_card, "steps_var", tk.IntVar(value=20))
        self.upscale_tile_size = getattr(upscale_card, "tile_size_var", tk.IntVar(value=512))
        self.upscale_denoise = getattr(upscale_card, "denoise_var", tk.DoubleVar(value=0.35))

        # Stage toggle vars and upscale proxies (JT05 compatibility)
        # CRITICAL: These are read by controller when applying config - defaults must be correct
        self.txt2img_enabled = tk.BooleanVar(value=True)  # Only txt2img should default to True
        self.img2img_enabled = tk.BooleanVar(value=False)
        self.adetailer_enabled = tk.BooleanVar(value=False)  # Fixed: was True
        self.upscale_enabled = tk.BooleanVar(value=False)

        self.upscale_factor = tk.DoubleVar(value=2.0)
        self.upscale_model = tk.StringVar()
        self.upscale_tile_size = tk.IntVar(value=512)

        upscale_card = getattr(self.stage_cards_panel, "upscale_card", None)
        if upscale_card is not None:
            try:
                self.upscale_factor = upscale_card.factor_var
            except Exception:
                pass
            try:
                self.upscale_model = upscale_card.upscaler_var
            except Exception:
                pass
            try:
                self.upscale_tile_size = upscale_card.tile_size_var
            except Exception:
                pass

        try:
            self.txt2img_enabled.trace_add(
                "write",
                lambda *_: self._on_stage_toggle_var("txt2img", self.txt2img_enabled),
            )
            self.img2img_enabled.trace_add(
                "write",
                lambda *_: self._on_stage_toggle_var("img2img", self.img2img_enabled),
            )
            self.upscale_enabled.trace_add(
                "write",
                lambda *_: self._on_stage_toggle_var("upscale", self.upscale_enabled),
            )
            self.adetailer_enabled.trace_add(
                "write",
                lambda *_: self._on_stage_toggle_var("adetailer", self.adetailer_enabled),
            )
        except Exception:
            pass

        listener = getattr(self.pipeline_controller, "on_adetailer_config_changed", None)
        if callable(listener):
            try:
                self.stage_cards_panel.add_adetailer_listener(listener)
            except Exception:
                pass
        self._sync_state_overrides()
        self._handle_sidebar_change()

        if self.app_state is not None:
            try:
                self.app_state.add_resource_listener(self._on_app_state_resources_changed)
                self.app_state.subscribe("job_draft", self._on_job_draft_changed)
                self.app_state.subscribe("queue_items", self._on_queue_items_changed)
                self.app_state.subscribe("running_job", self._on_running_job_changed)
                self.app_state.subscribe("queue_status", self._on_queue_status_changed)
                self.app_state.subscribe("history_items", self._on_history_items_changed)
            except Exception:
                pass
            self._on_app_state_resources_changed(self.app_state.resources)
            self._on_job_draft_changed()
            self._on_queue_items_changed()
            self._on_running_job_changed()
            self._on_queue_status_changed()
            self._on_history_items_changed()
            if hasattr(self, "run_controls"):
                self.run_controls.update_from_app_state(self.app_state)
        controller = self.app_controller or self.pipeline_controller
        if controller:
            try:
                controller.restore_last_run()
            except Exception:
                pass

        # PR-GUI-D: ScrollableFrame already handles mouse wheel; remove redundant calls
        attach_tooltip(self.sidebar, "Pipeline controls and prompt packs.")

        self.pack_loader_compat = self.sidebar
        self.left_compat = self.sidebar

        log_card = _create_card(self.right_scroll.inner)
        log_card.grid(row=5, column=0, sticky="ew", padx=(0, 12), pady=(0, 0))
        self.log_panel = DebugLogPanelV2(
            log_card,
            app_state=self.app_state,
        )
        self.log_panel.grid(row=0, column=0, sticky="nsew")

        # PR-GUI-D: Ensure minimum window width on first show
        self._width_ensured = False
        self.bind("<Map>", self._on_first_map)
        self._bind_process_inspector_shortcut()

    # -------------------------------------------------------------------------
    # PR-GUI-D: Minimum Window Width
    # -------------------------------------------------------------------------
    MIN_WINDOW_WIDTH = 1400

    def _on_first_map(self, event: tk.Event | None = None) -> None:
        """Called when the Pipeline tab becomes visible for the first time."""
        if self._width_ensured:
            return
        self._width_ensured = True
        self._ensure_minimum_window_width()

    def _ensure_minimum_window_width(self) -> None:
        """Expand the window if it's narrower than the minimum for 3 columns."""
        try:
            root = self.winfo_toplevel()
            current_geom = root.geometry()  # "WxH+X+Y"
            width_str, rest = current_geom.split("x", 1)
            width = int(width_str)
        except Exception:
            return

        if width < self.MIN_WINDOW_WIDTH:
            try:
                parts = rest.split("+")
                height = parts[0]
                x = parts[1] if len(parts) > 1 else None
                y = parts[2] if len(parts) > 2 else None

                if x is not None and y is not None:
                    root.geometry(f"{self.MIN_WINDOW_WIDTH}x{height}+{x}+{y}")
                else:
                    root.geometry(f"{self.MIN_WINDOW_WIDTH}x{height}")
            except Exception:
                pass

    def update_pack_list(self, pack_names: list[str]) -> None:
        """Update the pack list in the pack loader compat."""
        self.pack_loader_compat.set_pack_names(pack_names)

    def _sync_state_overrides(self) -> None:
        if not self.state_manager:
            return
        # Guard against early callback before stage_cards_panel is assigned
        if not hasattr(self, "stage_cards_panel") or self.stage_cards_panel is None:
            return
        prompt_text = ""
        try:
            if self.prompt_workspace_state is not None:
                prompt_text = self.prompt_workspace_state.get_current_prompt_text() or ""
        except Exception:
            prompt_text = ""

        if not prompt_text and hasattr(self, "prompt_text"):
            try:
                prompt_text = self.prompt_text.get() or ""
            except Exception:
                pass

        overrides = self.stage_cards_panel.to_overrides(prompt_text=prompt_text)
        try:
            self.state_manager.pipeline_overrides = overrides
        except Exception:
            setter = getattr(self.state_manager, "set_pipeline_overrides", None)
            if callable(setter):
                try:
                    setter(overrides)
                except Exception:
                    pass

    def _on_stage_toggle_var(self, stage_name: str, var: tk.BooleanVar) -> None:
        if not hasattr(self, "stage_cards_panel") or self.stage_cards_panel is None:
            return
        try:
            enabled = bool(var.get())
            self.stage_cards_panel.set_stage_enabled(stage_name, enabled)
        except Exception:
            pass

    def _apply_stage_visibility(self) -> None:
        stage_order = get_pipeline_stage_order() or ["txt2img", "img2img", "ADetailer", "upscale"]
        enabled = (
            self.sidebar.get_enabled_stages()
            if hasattr(self, "sidebar")
            else ["txt2img", "img2img", "ADetailer", "upscale"]
        )
        mapping = {
            stage_name: getattr(self.stage_cards_panel, f"{stage_name}_card", None)
            for stage_name in stage_order
        }
        ordered_cards = []
        for stage_name in stage_order:
            if stage_name in enabled:
                card = mapping.get(stage_name)
                if card:
                    ordered_cards.append(card)

        for idx, card in enumerate(ordered_cards):
            is_last = idx == len(ordered_cards) - 1
            card.grid(row=idx, column=0, sticky="nsew", pady=(0, 0) if is_last else (0, 6))

        for card in mapping.values():
            if card not in ordered_cards:
                card.grid_remove()

    def _bind_process_inspector_shortcut(self) -> None:
        """Register the hidden Ctrl+Alt+P shortcut for the diagnostic helper."""
        try:
            self.bind_all("<Control-Alt-P>", self._on_process_inspector_shortcut, add="+")
        except Exception:
            pass

    def _on_process_inspector_shortcut(self, event: tk.Event | None = None) -> None:
        """Invoke the process-inspection helper when the shortcut fires."""
        self._run_process_inspector()

    def _run_process_inspector(self) -> None:
        processes = list(iter_stablenew_like_processes())
        if not processes:
            self._log_process_inspector_message(
                "[PROC] inspector: no StableNew-like python processes found."
            )
            return
        for proc in processes:
            self._log_process_inspector_message(format_process_brief(proc))

    def _log_process_inspector_message(self, message: str) -> None:
        """Write the given message to the GUI log panel and trace handler."""
        controller = self.app_controller
        if controller is not None:
            append = getattr(controller, "_append_log", None)
            if callable(append):
                try:
                    append(message)
                except Exception:
                    pass
        logger.info(message)

    def _handle_sidebar_change(self) -> None:
        self._apply_stage_visibility()
        if hasattr(self, "preview_panel"):
            try:
                self.preview_panel.update_from_controls(self.sidebar)
            except Exception:
                pass
        self._refresh_preview_from_pipeline_jobs()

    def _on_restore_last_run_clicked(self) -> None:
        controller = self.app_controller or self.pipeline_controller
        if not controller:
            return
        try:
            controller.restore_last_run(force=True)
        except Exception:
            pass

    def _on_app_state_resources_changed(
        self, resources: dict[str, list[Any]] | None = None
    ) -> None:
        panel = getattr(self, "stage_cards_panel", None)
        if panel is not None and resources:
            panel.apply_resource_update(resources)

    def _on_job_draft_changed(self) -> None:
        if self.app_state is None:
            return
        try:
            self._refresh_preview_from_pipeline_jobs()
        except Exception:
            pass

    def _refresh_preview_from_pipeline_jobs(self) -> bool:
        """Attempt to render JobUiSummary data before falling back to draft text."""
        records = self._get_pipeline_preview_jobs()
        has_records = bool(records)
        if has_records and self.app_state and hasattr(self.app_state, "set_preview_jobs"):
            try:
                self.app_state.set_preview_jobs(records)
            except Exception:
                pass
        try:
            if hasattr(self, "preview_panel"):
                self.preview_panel.update_from_app_state(self.app_state)
        except Exception:
            pass
        return has_records

    def _get_pipeline_preview_jobs(self) -> list[NormalizedJobRecord]:
        controller = self.pipeline_controller or getattr(
            self.app_controller, "pipeline_controller", None
        )
        if controller is None:
            return []
        getter = getattr(controller, "get_preview_jobs", None)
        if not callable(getter):
            return []
        try:
            return getter()
        except Exception:
            return []

    def _on_queue_items_changed(self) -> None:
        if self.app_state is None:
            return
        # PR-GUI-F1: Queue items are now displayed in QueuePanelV2
        try:
            if hasattr(self, "queue_panel"):
                self.queue_panel.update_from_app_state(self.app_state)
        except Exception:
            pass

    def _on_running_job_changed(self) -> None:
        if self.app_state is None:
            return
        # PR-GUI-F1: Running job is now displayed in RunningJobPanelV2
        try:
            if hasattr(self, "running_job_panel"):
                self.running_job_panel.update_from_app_state(self.app_state)
        except Exception:
            pass
        # Also update queue panel for status
        try:
            if hasattr(self, "queue_panel"):
                self.queue_panel.update_from_app_state(self.app_state)
        except Exception:
            pass

    def _on_queue_status_changed(self) -> None:
        if self.app_state is None:
            return
        # PR-GUI-F1: Queue status is now displayed in QueuePanelV2
        try:
            if hasattr(self, "queue_panel"):
                self.queue_panel.update_queue_status(self.app_state.queue_status)
        except Exception:
            pass

    def _on_history_items_changed(self) -> None:
        if self.app_state is None or not hasattr(self, "history_panel"):
            return
        try:
            self.history_panel._on_history_items_changed()
        except Exception:
            pass


PipelineTabFrame = PipelineTabFrame
