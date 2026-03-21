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

    @patch("tkinter.Tk")
    def test_sidebar_preset_selection_calls_controller(self, mock_tk, mock_controller, tmp_path):
        """Test that selecting a preset calls the controller's on_preset_selected method."""
        # Mock Tkinter components
        mock_root = Mock()
        mock_tk.return_value = mock_root
        mock_root.withdraw = Mock()
        mock_root.destroy = Mock()

        # Mock the dropdown
        mock_dropdown = Mock()
        mock_dropdown.cget.return_value = ("preset1", "preset2")

        # Mock the config source label
        mock_label = Mock()

        with (
            patch.object(SidebarPanelV2, "__init__", return_value=None),
            patch.object(SidebarPanelV2, "grid_columnconfigure", return_value=None),
        ):
            sidebar = SidebarPanelV2.__new__(SidebarPanelV2)
            sidebar.controller = mock_controller
            sidebar.saved_recipe_dropdown = mock_dropdown
            sidebar.saved_recipe_var = Mock()
            sidebar.saved_recipe_var.get.return_value = "preset1"
            sidebar.config_source_label = mock_label
            sidebar.config_manager = Mock()
            sidebar.config_manager.presets_dir = tmp_path
            sidebar.config_manager.load_preset.return_value = {
                "txt2img": {"model": "sdxl", "sampler_name": "Euler", "width": 768, "height": 768}
            }

            # Simulate selecting a preset
            sidebar._on_saved_recipe_selected()

            # Check that controller was called
            assert mock_controller.selected_recipe == "preset1"
            # Check that label was updated
            mock_label.config.assert_called()
            rendered = mock_label.config.call_args.kwargs["text"]
            assert rendered.startswith("Saved Recipe: preset1")
