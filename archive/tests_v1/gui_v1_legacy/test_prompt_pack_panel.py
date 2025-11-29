"""Tests for PromptPackPanel component."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Handle headless testing
if sys.platform.startswith("linux") and "DISPLAY" not in os.environ:
    # For headless Linux environments, use virtual display
    os.environ["DISPLAY"] = ":99"

import tkinter as tk

from src.gui.prompt_pack_panel import PromptPackPanel


class TestPromptPackPanel(unittest.TestCase):
    """Test suite for PromptPackPanel."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a root window (required for widgets)
        try:
            self.root = tk.Tk()
            self.root.withdraw()  # Hide the window
        except tk.TclError:
            self.skipTest("No display available for Tkinter tests")

    def tearDown(self):
        """Clean up after tests."""
        if hasattr(self, "root"):
            try:
                self.root.destroy()
            except:
                pass

    def test_panel_instantiation(self):
        """Test that the PromptPackPanel can be instantiated."""
        mock_coordinator = MagicMock()
        mock_list_manager = MagicMock()
        mock_list_manager.get_list_names.return_value = []

        # Instantiate the panel
        panel = PromptPackPanel(
            self.root, coordinator=mock_coordinator, list_manager=mock_list_manager
        )

        # Assert that the panel is created and is a ttk.Frame
        from tkinter import ttk

        self.assertIsInstance(panel, ttk.Frame)
        self.assertIsNotNone(panel)
        self.assertIsNotNone(panel.packs_listbox)

    def test_panel_with_callbacks(self):
        """Test panel with selection change callback."""
        mock_on_selection_changed = MagicMock()
        mock_on_advanced_editor = MagicMock()
        mock_list_manager = MagicMock()
        mock_list_manager.get_list_names.return_value = []

        panel = PromptPackPanel(
            self.root,
            on_selection_changed=mock_on_selection_changed,
            on_advanced_editor=mock_on_advanced_editor,
            list_manager=mock_list_manager,
        )

        # Callbacks should be stored
        self.assertEqual(panel._on_selection_changed, mock_on_selection_changed)
        self.assertEqual(panel._on_advanced_editor, mock_on_advanced_editor)

    @patch("src.gui.prompt_pack_panel.get_prompt_packs")
    def test_refresh_packs(self, mock_get_packs):
        """Test refreshing the pack list."""
        # Setup mock to return some packs
        mock_pack1 = MagicMock()
        mock_pack1.name = "pack1.txt"
        mock_pack2 = MagicMock()
        mock_pack2.name = "pack2.txt"
        mock_get_packs.return_value = [mock_pack1, mock_pack2]

        mock_list_manager = MagicMock()
        mock_list_manager.get_list_names.return_value = []

        panel = PromptPackPanel(self.root, list_manager=mock_list_manager)

        # Initially should have loaded packs
        self.assertEqual(panel.packs_listbox.size(), 2)

        # Refresh again
        panel.refresh_packs(silent=True)
        self.assertEqual(panel.packs_listbox.size(), 2)

    @patch("src.gui.prompt_pack_panel.get_prompt_packs")
    def test_get_selected_packs(self, mock_get_packs):
        """Test getting selected packs."""
        mock_pack1 = MagicMock()
        mock_pack1.name = "pack1.txt"
        mock_pack2 = MagicMock()
        mock_pack2.name = "pack2.txt"
        mock_get_packs.return_value = [mock_pack1, mock_pack2]

        mock_list_manager = MagicMock()
        mock_list_manager.get_list_names.return_value = []

        panel = PromptPackPanel(self.root, list_manager=mock_list_manager)

        # Initially nothing selected
        self.assertEqual(panel.get_selected_packs(), [])

        # Select first pack
        panel.packs_listbox.selection_set(0)
        selected = panel.get_selected_packs()
        self.assertEqual(selected, ["pack1.txt"])

        # Select both
        panel.packs_listbox.selection_set(1)
        selected = panel.get_selected_packs()
        self.assertEqual(len(selected), 2)
        self.assertIn("pack1.txt", selected)
        self.assertIn("pack2.txt", selected)

    @patch("src.gui.prompt_pack_panel.get_prompt_packs")
    def test_set_selected_packs(self, mock_get_packs):
        """Test setting selected packs."""
        mock_pack1 = MagicMock()
        mock_pack1.name = "pack1.txt"
        mock_pack2 = MagicMock()
        mock_pack2.name = "pack2.txt"
        mock_get_packs.return_value = [mock_pack1, mock_pack2]

        mock_on_selection = MagicMock()
        mock_list_manager = MagicMock()
        mock_list_manager.get_list_names.return_value = []

        panel = PromptPackPanel(
            self.root, on_selection_changed=mock_on_selection, list_manager=mock_list_manager
        )

        # Set selection to pack2
        panel.set_selected_packs(["pack2.txt"])

        # Check selection
        selected = panel.get_selected_packs()
        self.assertEqual(selected, ["pack2.txt"])

        # Callback should have been called
        mock_on_selection.assert_called()

    @patch("src.gui.prompt_pack_panel.get_prompt_packs")
    def test_selection_callback(self, mock_get_packs):
        """Test that selection changes trigger callback."""
        mock_pack1 = MagicMock()
        mock_pack1.name = "pack1.txt"
        mock_get_packs.return_value = [mock_pack1]

        mock_on_selection = MagicMock()
        mock_list_manager = MagicMock()
        mock_list_manager.get_list_names.return_value = []

        panel = PromptPackPanel(
            self.root, on_selection_changed=mock_on_selection, list_manager=mock_list_manager
        )

        # Simulate selection change via helper to ensure callbacks are safe
        panel.set_selected_packs(["pack1.txt"])

        # Callback should be called with selected packs
        mock_on_selection.assert_called_with(["pack1.txt"])

    @patch("src.gui.prompt_pack_panel.get_prompt_packs")
    def test_select_first_pack(self, mock_get_packs):
        """Test selecting first pack."""
        mock_pack1 = MagicMock()
        mock_pack1.name = "pack1.txt"
        mock_get_packs.return_value = [mock_pack1]

        mock_on_selection = MagicMock()
        mock_list_manager = MagicMock()
        mock_list_manager.get_list_names.return_value = []

        panel = PromptPackPanel(
            self.root, on_selection_changed=mock_on_selection, list_manager=mock_list_manager
        )

        # Select first pack
        panel.select_first_pack()

        # First pack should be selected
        selected = panel.get_selected_packs()
        self.assertEqual(selected, ["pack1.txt"])


if __name__ == "__main__":
    unittest.main()
