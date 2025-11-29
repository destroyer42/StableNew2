# Moved to archive/gui_v1/app_layout_v2.py on November 28, 2025
# This file is now a stub. See archive for legacy code.

# Moved to archive/gui_v1/app_layout_v2.py on November 28, 2025
# This file is now a stub. See archive for legacy code.

"""V2 application layout builder for StableNewGUI.

This helper centralizes panel instantiation and attachment for the V2 GUI shell.
It is intentionally limited to Tk layout concerns and does not touch controller,
pipeline, or learning logic.
"""

from __future__ import annotations

from typing import Any
from tkinter import ttk

from src.gui.panels_v2 import (
    PipelinePanelV2,
    PreviewPanelV2,
    RandomizerPanelV2,
    SidebarPanelV2,
    StatusBarV2,
)
from src.gui.prompt_pack_adapter_v2 import PromptPackAdapterV2, PromptPackSummary
from src.gui.job_history_panel_v2 import JobHistoryPanelV2


class AppLayoutV2:
    """Builds and attaches V2 panels to a StableNewGUI owner."""

    def __init__(self, owner: Any, theme: Any = None) -> None:
        self.owner = owner
        self.theme = theme
        self._frame_style = getattr(theme, "SURFACE_FRAME_STYLE", "Dark.TFrame")
        try:
            self.prompt_pack_adapter = getattr(owner, "prompt_pack_adapter_v2")
        except Exception:
            self.prompt_pack_adapter = None
        if self.prompt_pack_adapter is None:
            try:
                self.prompt_pack_adapter = PromptPackAdapterV2()
                setattr(owner, "prompt_pack_adapter_v2", self.prompt_pack_adapter)
            except Exception:
                self.prompt_pack_adapter = None

    def build_layout(self, root_frame: Any | None = None) -> None:
        """Instantiate panels and attach them to the owner if not already present."""

        owner = self.owner
        root_frame = getattr(owner, "root", None)
        self.left_zone = self._ensure_zone("left_zone", root_frame)
        self.center_zone = self._ensure_zone("center_zone", root_frame)
        self.center_stack = getattr(owner, "center_stack", None) or self.center_zone
        self.right_zone = self._ensure_zone("right_zone", root_frame)
        self.bottom_zone = self._ensure_zone("bottom_zone", getattr(owner, "_bottom_pane", root_frame))

        # Pipeline / center panel
        center_parent = self.center_stack or self.center_zone
        if not hasattr(owner, "pipeline_panel_v2") and center_parent is not None:
            owner.pipeline_panel_v2 = PipelinePanelV2(
                center_parent,
                controller=getattr(owner, "controller", None),
                theme=self.theme,
                config_manager=getattr(owner, "config_manager", None),
            )
            try:
                owner.pipeline_panel_v2.pack(fill="both", expand=True)
            except Exception:
                pass

        # Sidebar (depends on prompt pack adapter and apply callback)
        if not hasattr(owner, "sidebar_panel_v2") and self.left_zone is not None:
            owner.sidebar_panel_v2 = SidebarPanelV2(
                self.left_zone,
                controller=getattr(owner, "controller", None),
                theme=self.theme,
                prompt_pack_adapter=self.prompt_pack_adapter,
                on_apply_pack=self._apply_pack_to_prompt,
            )
            try:
                owner.sidebar_panel_v2.pack(fill="both", expand=True)
            except Exception:
                pass
        if hasattr(owner, "sidebar_panel_v2"):
            try:
                owner.model_manager_panel_v2 = getattr(owner.sidebar_panel_v2, "model_manager_panel", None)
                owner.core_config_panel_v2 = owner.sidebar_panel_v2.core_config_panel
                owner.negative_prompt_panel_v2 = owner.sidebar_panel_v2.negative_prompt_panel
                owner.resolution_panel_v2 = getattr(owner.sidebar_panel_v2.core_config_panel, "resolution_panel", None)
            except Exception:
                pass

        if (
            not hasattr(owner, "randomizer_panel_v2")
            and center_parent is not None
            and hasattr(owner, "pipeline_panel_v2")
        ):
            owner.randomizer_panel_v2 = RandomizerPanelV2(
                center_parent, controller=getattr(owner, "controller", None), theme=self.theme
            )
            try:
                owner.randomizer_panel_v2.pack(fill="both", expand=True, pady=(5, 0))
            except Exception:
                pass

        # Right-side panels: preview
        if not hasattr(owner, "preview_panel_v2") and self.right_zone is not None:
            owner.preview_panel_v2 = PreviewPanelV2(
                self.right_zone,
                controller=getattr(owner, "controller", None),
                theme=self.theme,
            )
            try:
                owner.preview_panel_v2.pack(fill="both", expand=True)
            except Exception:
                pass

        # Jobs / history panel (optional, read-only)
        if not hasattr(owner, "job_history_panel_v2") and self.right_zone is not None:
            history_service = getattr(owner, "job_history_service", None)
            if history_service is None:
                ctrl = getattr(owner, "controller", None)
                getter = getattr(ctrl, "get_job_history_service", None)
                if callable(getter):
                    try:
                        history_service = getter()
                    except Exception:
                        history_service = None
            if history_service:
                owner.job_history_panel_v2 = JobHistoryPanelV2(
                    owner.right_zone, job_history_service=history_service, theme=self.theme
                )
                try:
                    owner.job_history_panel_v2.pack(fill="both", expand=True, pady=(5, 0))
                except Exception:
                    pass
        elif hasattr(owner, "job_history_panel_v2"):
            history_service = getattr(owner, "job_history_service", None)
            if history_service:
                try:
                    owner.job_history_panel_v2._service = history_service
                except Exception:
                    pass

        # Status bar
        if not hasattr(owner, "status_bar_v2") and self.bottom_zone is not None:
            owner.status_bar_v2 = StatusBarV2(
                self.bottom_zone,
                controller=getattr(owner, "controller", None),
                theme=self.theme,
            )
            try:
                owner.status_bar_v2.pack(fill="x", pady=(4, 0))
            except Exception:
                pass

    def attach_run_button(self, run_button: Any | None = None) -> None:
        """Expose the run button reference consistently."""

        if run_button is not None:
            self.owner.run_button = run_button

    def _apply_pack_to_prompt(self, prompt_text: str, summary: PromptPackSummary | None = None) -> None:
        pipeline_panel = getattr(self.owner, "pipeline_panel_v2", None)
        if pipeline_panel is None:
            return
        pipeline_panel.set_prompt(prompt_text or "")
        editor = getattr(pipeline_panel, "_editor", None)
        editor_window = getattr(pipeline_panel, "_editor_window", None)
        if editor and editor_window and getattr(editor_window, "winfo_exists", lambda: False)():
            try:
                editor.prompt_text.delete("1.0", "end")
                if prompt_text:
                    editor.prompt_text.insert("1.0", prompt_text)
            except Exception:
                pass

    def _ensure_zone(self, attr: str, parent: Any | None) -> Any | None:
        """Guarantee a frame exists for the given zone so panels have a target."""
        zone = getattr(self.owner, attr, None)
        if zone is None and parent is not None:
            try:
                zone = ttk.Frame(parent, style=self._frame_style)
                zone.pack(fill="both", expand=True)
                setattr(self.owner, attr, zone)
            except Exception:
                zone = None
        return zone
