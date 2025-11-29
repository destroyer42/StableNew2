from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.views.stage_cards_panel import StageCardsPanel
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2


class PipelineTabFrame(ttk.Frame):
    """Layout scaffold for the Pipeline tab."""
    # Panel width variables for easy adjustment
    SIDEBAR_MIN_WIDTH = 320
    CENTRAL_MIN_WIDTH = 480

    def __init__(
        self,
        master: tk.Misc,
        *,
        prompt_workspace_state: Any = None,
        app_state: Any = None,
        pipeline_controller: Any = None,
        theme: Any = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.prompt_workspace_state = prompt_workspace_state
        self.app_state = app_state
        self.pipeline_controller = pipeline_controller
        self.theme = theme
        self.state_manager = getattr(self.pipeline_controller, "state_manager", None)

        # Body with three columns
        self.body_frame = ttk.Frame(self, padding=8, style="Panel.TFrame")
        self.body_frame.grid(row=0, column=0, sticky="nsew")
        self.body_frame.columnconfigure(0, weight=0)
        self.body_frame.columnconfigure(1, weight=1)  # 66% of previous width
        self.body_frame.columnconfigure(2, weight=1)
        self.body_frame.rowconfigure(0, weight=1)

        # Scrollable left column for sidebar/global negative/prompt packs
        self.left_scroll = ScrollableFrame(self.body_frame, style="Panel.TFrame")
        self.left_inner = self.left_scroll.inner
        self.left_scroll.grid(row=0, column=0, sticky="nsw", padx=(0, 4))
        self.left_inner.update_idletasks()
        self.body_frame.grid_propagate(False)

        self.sidebar = SidebarPanelV2(
            self.left_inner,
            controller=self.pipeline_controller,
            app_state=self.app_state,
            theme=self.theme,
            on_change=lambda: self._handle_sidebar_change(),
        )
        self.sidebar.pack(fill="x", pady=(0, 8))

        # Add global negative prompt and prompt pack selector here as needed
        # ...existing code for global negative/prompt packs if present...

        self.stage_scroll = ScrollableFrame(self.body_frame, style="Panel.TFrame")
        self.stage_cards_frame = self.stage_scroll.inner
        self.stage_scroll.grid(row=0, column=1, sticky="nsew", padx=4)
        self.stage_scroll.inner.update_idletasks()

        self.preview_panel = PreviewPanelV2(self.body_frame, controller=self.pipeline_controller, theme=self.theme)
        self.preview_panel.grid(row=0, column=2, sticky="nsew", padx=(4, 0))

        self.stage_cards_panel = StageCardsPanel(
            self.stage_cards_frame,
            controller=self.pipeline_controller,
            theme=self.theme,
            app_state=self.app_state,
            on_change=lambda: self._sync_state_overrides(),
        )
        self.stage_cards_panel.pack(fill="both", expand=True)
        self._sync_state_overrides()
        self._handle_sidebar_change()
        if self.app_state is not None:
            try:
                self.app_state.add_resource_listener(self._on_app_state_resources_changed)
            except Exception:
                pass
            self._on_app_state_resources_changed(self.app_state.resources)

    def _sync_state_overrides(self) -> None:
        """Push current stage card values into the pipeline controller state manager."""
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
            # If the state manager provides a setter, attempt to call it
            setter = getattr(self.state_manager, "set_pipeline_overrides", None)
            if callable(setter):
                try:
                    setter(overrides)
                except Exception:
                    pass

    def _apply_stage_visibility(self) -> None:
        enabled = set(self.sidebar.get_enabled_stages()) if hasattr(self, "sidebar") else {"txt2img", "img2img", "upscale"}
        if "txt2img" in enabled:
            self.stage_cards_panel.txt2img_card.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        else:
            self.stage_cards_panel.txt2img_card.grid_remove()
        if "img2img" in enabled:
            self.stage_cards_panel.img2img_card.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        else:
            self.stage_cards_panel.img2img_card.grid_remove()
        if "upscale" in enabled:
            self.stage_cards_panel.upscale_card.grid(row=2, column=0, sticky="nsew")
        else:
            self.stage_cards_panel.upscale_card.grid_remove()

    def _handle_sidebar_change(self) -> None:
        self._apply_stage_visibility()
        try:
            if hasattr(self, "preview_panel"):
                self.preview_panel.update_from_controls(self.sidebar)
        except Exception:
            pass

    def _on_app_state_resources_changed(self, resources: dict[str, list[Any]] | None) -> None:
        panel = getattr(self, "stage_cards_panel", None)
        if panel is not None:
            try:
                panel.apply_resource_update(resources)
            except Exception:
                pass
