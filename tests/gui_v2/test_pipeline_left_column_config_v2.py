from __future__ import annotations

import pytest

from src.app_factory import build_v2_app
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

        # Check that pipeline config panel exists (now integrated into sidebar)
        config_panel = getattr(sidebar, "pipeline_config_panel", None)
        assert config_panel is not None, "PipelineConfigPanel should be present in sidebar"

        stage_states = getattr(sidebar, "stage_states", None)
        assert stage_states is not None, "Sidebar should expose stage toggle state"
        for stage_name in ("txt2img", "img2img", "adetailer", "upscale"):
            assert stage_name in stage_states, f"Stage toggle {stage_name} should exist"

        # Check that both panels have access to controller and app_state (may be None in test environment)
        assert hasattr(config_panel, 'controller'), "Config panel should have controller attribute"
        assert hasattr(config_panel, 'app_state'), "Config panel should have app_state attribute"

        # Check that the panels are properly integrated
        left_inner = getattr(pipeline_tab, "left_inner", None)
        assert left_inner is not None, "Left inner frame should exist"

        # Verify the sidebar is a child of the left column
        children = left_inner.winfo_children()
        sidebar_found = any(isinstance(child, SidebarPanelV2) for child in children)

        assert sidebar_found, "SidebarPanelV2 should be in left column"

    finally:
        try:
            root.destroy()
        except Exception:
            pass
