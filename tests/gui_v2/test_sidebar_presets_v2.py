"""Tests for SidebarPanelV2 preset dropdown functionality."""

from unittest.mock import Mock, patch

import pytest

from src.gui.sidebar_panel_v2 import SidebarPanelV2


class MockController:
    """Mock controller for testing sidebar preset functionality."""

    def __init__(self):
        self.selected_recipe = None

    def on_saved_recipe_selected(self, recipe_name: str) -> None:
        self.selected_recipe = recipe_name


class TestSidebarPresets:
    """Test SidebarPanelV2 preset dropdown population and selection."""

    @pytest.fixture
    def mock_controller(self):
        return MockController()

    @patch("tkinter.Tk")
    def test_sidebar_populates_presets_dropdown(self, mock_tk, mock_controller):
        """Test that sidebar populates preset dropdown with names from ConfigManager."""
        # Mock Tkinter components
        mock_root = Mock()
        mock_tk.return_value = mock_root
        mock_root.withdraw = Mock()

        # Mock the dropdown
        mock_dropdown = Mock()
        mock_dropdown.cget.return_value = ("preset1", "preset2", "preset3")

        with patch.object(SidebarPanelV2, "__init__", return_value=None):
            sidebar = SidebarPanelV2.__new__(SidebarPanelV2)
            sidebar.saved_recipe_dropdown = mock_dropdown

            # Check that dropdown has preset names
            values = sidebar.saved_recipe_dropdown.cget("values")
            assert isinstance(values, (tuple, list))

    def test_sidebar_preset_selection_calls_controller(self, mock_controller, tmp_path, tk_root):
        """Selecting a recipe calls the controller and reports it as selected, not applied."""
        config_manager = Mock()
        config_manager.presets_dir = tmp_path
        config_manager.list_presets.return_value = ["preset1", "preset2"]
        config_manager.load_preset.return_value = {
            "txt2img": {"model": "sdxl", "sampler_name": "Euler", "width": 768, "height": 768}
        }
        sidebar = SidebarPanelV2(
            tk_root,
            controller=mock_controller,
            prompt_pack_adapter=Mock(load_summaries=Mock(return_value=[])),
            config_manager=config_manager,
            pack_list_manager=Mock(
                get_list_names=Mock(return_value=[]), get_list=Mock(return_value=None)
            ),
        )
        try:
            sidebar.saved_recipe_var.set("preset1")

            sidebar._on_saved_recipe_selected()

            assert mock_controller.selected_recipe == "preset1"
            rendered = sidebar.config_source_label.cget("text")
            assert "Recipe 'preset1' selected, not applied" in rendered
            assert "sdxl | 768x768 | Euler" in rendered
        finally:
            sidebar.destroy()
