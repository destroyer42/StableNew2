"""Tests for PR-1: Layout Cleanup & Component De-duplication"""

import inspect

from src.gui.main_window import StableNewGUI


class TestPr1LayoutCleanup:
    """Test PR-1 layout cleanup and component deduplication."""

    def test_build_config_pipeline_panel_structure(self):
        """Test that _build_config_pipeline_panel method exists and has expected structure."""
        # Create a StableNewGUI instance (without calling __init__)
        gui = StableNewGUI.__new__(StableNewGUI)

        # Check that the method exists
        assert hasattr(gui, '_build_config_pipeline_panel')
        assert callable(gui._build_config_pipeline_panel)

        # Check that the method source contains expected elements
        source = inspect.getsource(gui._build_config_pipeline_panel)

        # Should contain calls to create the notebook and tabs
        assert 'ttk.Notebook' in source
        assert 'add(pipeline_tab, text="Pipeline")' in source
        assert 'add(randomization_tab, text="Randomization")' in source
        assert 'add(general_tab, text="General")' in source

        # Should call _build_randomization_tab
        assert '_build_randomization_tab(randomization_tab)' in source

        # Should call _build_pipeline_controls_panel
        assert '_build_pipeline_controls_panel(general_body)' in source

    def test_randomization_tab_method_exists(self):
        """Test that the randomization tab build method exists."""
        gui = StableNewGUI.__new__(StableNewGUI)

        # Check that the method exists
        assert hasattr(gui, '_build_randomization_tab')
        assert callable(gui._build_randomization_tab)

    def test_pipeline_controls_panel_method_exists(self):
        """Test that the pipeline controls panel build method exists."""
        gui = StableNewGUI.__new__(StableNewGUI)

        # Check that the method exists
        assert hasattr(gui, '_build_pipeline_controls_panel')
        assert callable(gui._build_pipeline_controls_panel)

    def test_ui_build_method_structure(self):
        """Test that _build_ui has the expected structure after changes."""
        gui = StableNewGUI.__new__(StableNewGUI)

        # Check that the method exists
        assert hasattr(gui, '_build_ui')
        assert callable(gui._build_ui)

        # Check that related methods exist
        assert hasattr(gui, '_build_config_pipeline_panel')
        assert hasattr(gui, '_build_prompt_pack_panel')
        assert hasattr(gui, '_build_bottom_panel')
        assert hasattr(gui, '_build_status_bar')
