from __future__ import annotations

import pytest

from src.app_factory import build_v2_app
from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
from src.gui.sidebar_panel_v2 import SidebarPanelV2


@pytest.mark.gui
def test_pipeline_left_column_config_v2() -> None:
    """Test that PipelineTabFrameV2 contains both SidebarPanelV2 and PipelineConfigPanelV2."""
    try:
        root, app_state, controller, window = build_v2_app()
    except Exception as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        # Get the pipeline tab
        pipeline_tab = getattr(window, "pipeline_tab", None)
        assert pipeline_tab is not None, "Pipeline tab should exist"

        # Check that sidebar panel exists
        sidebar = getattr(pipeline_tab, "sidebar", None)
        assert isinstance(sidebar, SidebarPanelV2), "SidebarPanelV2 should be present"

        # Check that pipeline config panel exists
        config_panel = getattr(pipeline_tab, "pipeline_config_panel", None)
        assert isinstance(config_panel, PipelineConfigPanel), "PipelineConfigPanel should be present"

        # Check that both panels have access to controller and app_state
        assert config_panel.controller is not None, "Config panel should have controller"
        assert config_panel.app_state is not None, "Config panel should have app_state"

        # Check that the panels are properly packed in the left column
        left_inner = getattr(pipeline_tab, "left_inner", None)
        assert left_inner is not None, "Left inner frame should exist"

        # Verify the panels are children of the left column
        children = left_inner.winfo_children()
        sidebar_found = any(isinstance(child, SidebarPanelV2) for child in children)
        config_found = any(isinstance(child, PipelineConfigPanel) for child in children)

        assert sidebar_found, "SidebarPanelV2 should be in left column"
        assert config_found, "PipelineConfigPanel should be in left column"

    finally:
        try:
            root.destroy()
        except Exception:
            pass
