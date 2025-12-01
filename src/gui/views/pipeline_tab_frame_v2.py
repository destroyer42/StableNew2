from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui import design_system_v2 as design_system
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.panels_v2.pipeline_run_controls_v2 import PipelineRunControlsV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.scrolling import enable_mousewheel
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.theme_v2 import CARD_FRAME_STYLE, SURFACE_FRAME_STYLE
from src.gui.tooltip import attach_tooltip
from src.gui.views.stage_cards_panel import StageCardsPanel
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui.zone_map_v2 import get_pipeline_stage_order


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
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self.prompt_workspace_state = prompt_workspace_state
        self.app_state = app_state
        self.app_controller = app_controller
        self.pipeline_controller = pipeline_controller
        self.theme = theme
        self.state_manager = getattr(self.pipeline_controller, "state_manager", None)

        self.rowconfigure(0, weight=1)
        for idx in range(3):
            self.columnconfigure(idx, weight=1, minsize=self.DEFAULT_COLUMN_WIDTH)

        self.left_column = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.left_column.grid(row=0, column=0, sticky="nsew")
        self.left_column.rowconfigure(0, weight=1)
        self.left_column.rowconfigure(1, weight=0)
        self.left_column.columnconfigure(0, weight=1)
        self.left_scroll = ScrollableFrame(self.left_column, style=CARD_FRAME_STYLE)
        self.left_scroll.grid(row=0, column=0, sticky="nsew")
        self.left_inner = self.left_scroll.inner
        self.sidebar = SidebarPanelV2(
            self.left_inner,
            controller=self.app_controller or self.pipeline_controller,
            app_state=self.app_state,
            theme=self.theme,
            on_change=lambda: self._handle_sidebar_change(),
        )
        self.sidebar.pack(fill="x", pady=(0, 16))
        self.restore_last_run_button = ttk.Button(
            self.left_column,
            text="Restore Last Run",
            command=self._on_restore_last_run_clicked,
        )
        self.restore_last_run_button.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self.center_column = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.center_column.grid(row=0, column=1, sticky="nsew")
        self.center_column.rowconfigure(0, weight=1)
        self.center_column.columnconfigure(0, weight=1)
        self.stage_scroll = ScrollableFrame(self.center_column, style=CARD_FRAME_STYLE)
        self.stage_scroll.grid(row=0, column=0, sticky="nsew")
        self.stage_cards_frame = self.stage_scroll.inner

        self.right_column = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
        self.right_column.grid(row=0, column=2, sticky="nsew")
        self.right_column.rowconfigure(0, weight=0)
        self.right_column.rowconfigure(1, weight=1)
        self.right_column.rowconfigure(2, weight=1)
        self.right_column.columnconfigure(0, weight=1)
        queue_controller = self.app_controller or self.pipeline_controller
        self.run_controls = PipelineRunControlsV2(
            self.right_column,
            controller=queue_controller,
            theme=self.theme,
        )
        self.run_controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.preview_panel = PreviewPanelV2(
            self.right_column,
            controller=queue_controller,
            app_state=self.app_state,
            theme=self.theme,
        )
        self.preview_panel.grid(row=1, column=0, sticky="nsew")

        self.history_panel = JobHistoryPanelV2(
            self.right_column,
            controller=queue_controller,
            app_state=self.app_state,
            theme=self.theme,
        )
        self.history_panel.grid(row=2, column=0, sticky="nsew", pady=(8, 0))


        self.stage_cards_panel = StageCardsPanel(
            self.stage_cards_frame,
            controller=self.pipeline_controller,
            theme=self.theme,
            app_state=self.app_state,
            on_change=lambda: self._sync_state_overrides(),
        )
        self.stage_cards_panel.pack(fill="both", expand=True)
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
        controller = self.app_controller or self.pipeline_controller
        if controller:
            try:
                controller.restore_last_run()
            except Exception:
                pass

        enable_mousewheel(self.left_scroll.inner)
        enable_mousewheel(self.stage_cards_frame)
        enable_mousewheel(self.preview_panel)
        enable_mousewheel(self.history_panel)
        attach_tooltip(self.sidebar, "Pipeline controls and prompt packs.")

        self.pack_loader_compat = self.sidebar
        self.left_compat = self.sidebar

    def update_pack_list(self, pack_names: list[str]) -> None:
        """Update the pack list in the pack loader compat."""
        self.pack_loader_compat.set_pack_names(pack_names)

    def _sync_state_overrides(self) -> None:
        if not self.state_manager:
            return
        prompt_text = ""
        try:
            if self.prompt_workspace_state is not None:
                prompt_text = self.prompt_workspace_state.get_current_prompt_text()
        except Exception:
            prompt_text = ""

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

    def _apply_stage_visibility(self) -> None:
        stage_order = get_pipeline_stage_order() or ["txt2img", "adetailer", "img2img", "upscale"]
        enabled = self.sidebar.get_enabled_stages() if hasattr(self, "sidebar") else ["txt2img", "img2img", "upscale"]
        mapping = {stage_name: getattr(self.stage_cards_panel, f"{stage_name}_card", None) for stage_name in stage_order}
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

    def _handle_sidebar_change(self) -> None:
        self._apply_stage_visibility()
        try:
            if hasattr(self, "preview_panel"):
                self.preview_panel.update_from_controls(self.sidebar)
        except Exception:
            pass

    def _on_restore_last_run_clicked(self) -> None:
        controller = self.app_controller or self.pipeline_controller
        if not controller:
            return
        try:
            controller.restore_last_run(force=True)
        except Exception:
            pass

    def _on_app_state_resources_changed(self, resources: dict[str, list[Any]] | None = None) -> None:
        panel = getattr(self, "stage_cards_panel", None)
        if panel is not None and resources:
            panel.apply_resource_update(resources)

    def _on_job_draft_changed(self) -> None:
        if self.app_state is None or not hasattr(self, "preview_panel"):
            return
        try:
            job_draft = self.app_state.job_draft
            self.preview_panel.update_from_job_draft(job_draft)
        except Exception:
            pass

    def _on_queue_items_changed(self) -> None:
        if self.app_state is None or not hasattr(self, "preview_panel"):
            return
        try:
            self.preview_panel.update_queue_items(self.app_state.queue_items)
        except Exception:
            pass

    def _on_running_job_changed(self) -> None:
        if self.app_state is None or not hasattr(self, "preview_panel"):
            return
        try:
            self.preview_panel.update_running_job(self.app_state.running_job)
        except Exception:
            pass

    def _on_queue_status_changed(self) -> None:
        if self.app_state is None or not hasattr(self, "preview_panel"):
            return
        try:
            self.preview_panel.update_queue_status(self.app_state.queue_status)
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
