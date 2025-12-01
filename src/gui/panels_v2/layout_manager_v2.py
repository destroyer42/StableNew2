"""Optional layout manager to compose V2 panels."""

from __future__ import annotations

from typing import Any

from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame


class LayoutManagerV2:
    """Helper to build and attach panel instances to a main window."""

    def __init__(self, main_window: Any) -> None:
        self.main_window = main_window

    def attach_panels(self) -> None:
        """Instantiate and wire V2 tab frames into the notebook."""
        mw = self.main_window
        notebook = getattr(mw, "center_notebook", None)
        if notebook is None:
            return

        app_state = getattr(mw, "app_state", None)
        app_controller = getattr(mw, "app_controller", None)
        pipeline_controller = getattr(mw, "pipeline_controller", None)
        prompt_workspace_state = getattr(mw, "prompt_workspace_state", None)
        theme = getattr(mw, "theme", None)

        mw.prompt_tab = PromptTabFrame(
            notebook,
            app_state=app_state,
        )
        notebook.add(mw.prompt_tab, text="Prompt")

        mw.pipeline_tab = PipelineTabFrame(
            notebook,
            prompt_workspace_state=prompt_workspace_state,
            app_state=app_state,
            app_controller=app_controller,
            pipeline_controller=pipeline_controller,
            theme=theme,
        )
        notebook.add(mw.pipeline_tab, text="Pipeline")

        mw.learning_tab = LearningTabFrame(
            notebook,
            app_state=app_state,
            pipeline_controller=pipeline_controller,
        )
        notebook.add(mw.learning_tab, text="Learning")

        notebook.select(mw.pipeline_tab)

        if hasattr(mw.pipeline_tab, "pack_loader_compat"):
            mw.left_zone = mw.pipeline_tab.pack_loader_compat
        mw.right_zone = getattr(mw.pipeline_tab, "preview_panel", None)

        mw.sidebar_panel_v2 = getattr(mw.pipeline_tab, "sidebar", None)
        stage_panel = getattr(mw.pipeline_tab, "stage_cards_panel", None)
        mw.pipeline_config_panel_v2 = getattr(getattr(mw.pipeline_tab, "sidebar", None), "pipeline_config_panel", None)
        mw.pipeline_panel_v2 = stage_panel
        mw.randomizer_panel_v2 = getattr(mw.pipeline_tab, "randomizer_panel", None)
        mw.preview_panel_v2 = getattr(mw.pipeline_tab, "preview_panel", None)
        mw.status_bar_v2 = getattr(getattr(mw, "bottom_zone", None), "status_bar_v2", None)

        mw.pipeline_controls_panel = getattr(stage_panel, "controls_panel", stage_panel)
        mw.run_pipeline_btn = getattr(stage_panel, "run_button", None)
