"""Tests for SidebarPanelV2 preset dropdown functionality."""

from unittest.mock import Mock, patch

import pytest

from src.gui.sidebar_panel_v2 import SidebarPanelV2


class MockController:
    """Mock controller for testing sidebar preset functionality."""

    def __init__(self):
        self.selected_preset = None

    def on_preset_selected(self, preset_name: str) -> None:
        self.selected_preset = preset_name


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
            sidebar.preset_dropdown = mock_dropdown

            # Check that dropdown has preset names
            values = sidebar.preset_dropdown.cget("values")
            assert isinstance(values, (tuple, list))

    @patch("tkinter.Tk")
    def test_sidebar_preset_selection_calls_controller(self, mock_tk, mock_controller):
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
            sidebar.preset_dropdown = mock_dropdown
            sidebar.preset_var = Mock()
            sidebar.preset_var.get.return_value = "preset1"
            sidebar.config_source_label = mock_label

            # Simulate selecting a preset
            sidebar._on_preset_selected()

            # Check that controller was called
            assert mock_controller.selected_preset == "preset1"
            # Check that label was updated
            mock_label.config.assert_called_with(text="Preset: preset1")
