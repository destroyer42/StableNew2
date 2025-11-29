"""Layout skeleton assertions for the v2 GUI."""

from __future__ import annotations

from src.gui.pipeline_panel_v2 import PipelinePanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.randomizer_panel_v2 import RandomizerPanelV2
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.status_bar_v2 import StatusBarV2


def test_gui_v2_layout_skeleton(gui_app_factory):
    """Verify key layout regions exist and are interactive."""

    app = gui_app_factory()

    assert isinstance(app.sidebar_panel_v2, SidebarPanelV2)
    assert isinstance(app.pipeline_panel_v2, PipelinePanelV2)
    assert isinstance(app.randomizer_panel_v2, RandomizerPanelV2)
    assert isinstance(app.preview_panel_v2, PreviewPanelV2)
    assert isinstance(app.status_bar_v2, StatusBarV2)
    assert app.pipeline_controls_panel.winfo_exists()
    assert app.run_pipeline_btn.winfo_exists()

    # V2 left panel attributes
    sidebar = app.sidebar_panel_v2
    assert hasattr(sidebar, "pack_panel")
    assert hasattr(sidebar, "preset_dropdown")
    assert hasattr(sidebar, "config_source_label")
    assert isinstance(sidebar.pack_panel, object)
    assert isinstance(sidebar.preset_dropdown, object)
    assert isinstance(sidebar.config_source_label, object)
