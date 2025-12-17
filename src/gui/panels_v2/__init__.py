"""Namespace for V2 panel re-exports."""

# PR-CORE1-12: PipelineConfigPanel archived to panels_v2/archive/
# from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel
from src.gui.panels_v2.job_explanation_panel_v2 import JobExplanationPanelV2
from src.gui.panels_v2.pipeline_panel_v2 import PipelinePanelV2
from src.gui.panels_v2.preview_panel_v2 import PreviewPanelV2
from src.gui.panels_v2.randomizer_panel_v2 import RandomizerPanelV2
from src.gui.panels_v2.sidebar_panel_v2 import SidebarPanelV2
from src.gui.panels_v2.status_bar_v2 import StatusBarV2

__all__ = [
    "PipelinePanelV2",
    "PreviewPanelV2",
    "RandomizerPanelV2",
    "SidebarPanelV2",
    "StatusBarV2",
    # PR-CORE1-12: "PipelineConfigPanel" removed - archived to panels_v2/archive/
    "JobExplanationPanelV2",
]
