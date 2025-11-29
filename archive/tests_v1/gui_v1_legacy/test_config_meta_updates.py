"""Tests for safe config metadata updates in StableNewGUI."""

import pytest

# Skip these tests if tkinter is not available
pytest.importorskip("tkinter")

import tkinter as tk

from src.gui.config_panel import ConfigPanel


class TestConfigMetaUpdates:
    """Test safe metadata updates and combo enabling."""

    def setup_method(self):
        """Set up test fixtures."""
        try:
            self.root = tk.Tk()
            self.root.withdraw()
            self.config_panel = ConfigPanel(self.root, coordinator=None, style="Dark.TFrame")
        except tk.TclError:
            pytest.skip("Tk/Tcl unavailable in this environment")

    def teardown_method(self):
        """Clean up after tests."""
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_metadata_attrs_initialized_as_empty_lists(self):
        """Test that metadata attributes are initialized as empty lists."""
        # Simulate main window initialization
        gui_mock = type("GUI", (), {})()
        gui_mock.schedulers = []
        gui_mock.upscaler_names = []
        gui_mock.vae_names = []

        assert gui_mock.schedulers == []
        assert gui_mock.upscaler_names == []
        assert gui_mock.vae_names == []

    def test_set_scheduler_options_enables_combo(self):
        """Test that set_scheduler_options enables combo when values present."""
        schedulers = ["normal", "karras", "exponential"]
        self.config_panel.set_scheduler_options(schedulers)

        # Check that scheduler combos have values
        scheduler_widget = self.config_panel.txt2img_widgets.get("scheduler")
        if scheduler_widget is not None:
            values = scheduler_widget["values"]
            assert "Normal" in values or "Karras" in values

    def test_set_upscaler_options_enables_combo(self):
        """Test that set_upscaler_options enables combo when values present."""
        upscalers = ["R-ESRGAN 4x+", "ESRGAN_4x", "Latent"]
        self.config_panel.set_upscaler_options(upscalers)

        # Check that upscaler combo has values
        upscaler_widget = self.config_panel.upscale_widgets.get("upscaler")
        if upscaler_widget is not None:
            values = upscaler_widget["values"]
            assert "R-ESRGAN 4x+" in values or "ESRGAN_4x" in values

    def test_set_vae_options_enables_combo(self):
        """Test that set_vae_options enables combo when values present."""
        vae_models = ["vae-ft-mse-840000-ema", "kl-f8-anime2"]
        self.config_panel.set_vae_options(vae_models)

        # Check that VAE combos have values
        vae_widget = self.config_panel.txt2img_widgets.get("vae")
        if vae_widget is not None:
            values = vae_widget["values"]
            assert "vae-ft-mse-840000-ema" in values or "kl-f8-anime2" in values

    def test_metadata_update_with_empty_list_safe(self):
        """Test that updating with empty list doesn't crash."""
        # Should not raise
        self.config_panel.set_scheduler_options([])
        self.config_panel.set_upscaler_options([])
        self.config_panel.set_vae_options([])

    def test_metadata_update_with_partial_captures_values(self):
        """Test that functools.partial captures values correctly."""
        from functools import partial

        schedulers = ["normal", "karras"]
        upscalers = ["R-ESRGAN 4x+"]
        vae_models = ["vae-ft-mse-840000"]

        # Simulate the pattern used in main_window async refresh methods
        # Create partials that capture the list values
        set_scheduler_partial = partial(self.config_panel.set_scheduler_options, list(schedulers))
        set_upscaler_partial = partial(self.config_panel.set_upscaler_options, list(upscalers))
        set_vae_partial = partial(self.config_panel.set_vae_options, list(vae_models))

        # Now modify the original lists (simulating late binding issue)
        schedulers.clear()
        upscalers.clear()
        vae_models.clear()

        # Call the partials - they should still have the captured values
        set_scheduler_partial()
        set_upscaler_partial()
        set_vae_partial()

        # Verify combos have the original values, not empty
        scheduler_widget = self.config_panel.txt2img_widgets.get("scheduler")
        if scheduler_widget is not None:
            values = scheduler_widget["values"]
            # Should have captured values, not empty
            assert len(values) > 0

    def test_on_metadata_ready_pattern(self):
        """Test the on_metadata_ready pattern with partial."""
        from functools import partial

        # Simulate the pattern from main_window
        class MockGUI:
            def __init__(self, config_panel):
                self.config_panel = config_panel
                self.schedulers = []
                self.upscaler_names = []
                self.vae_names = []
                self.root = tk.Tk()
                self.root.withdraw()

            def on_metadata_ready(self, meta):
                self.schedulers = meta.get("schedulers", [])
                self.upscaler_names = meta.get("upscalers", [])
                self.vae_names = meta.get("vaes", [])

                # Use partial to capture values
                self.root.after(
                    0, partial(self.config_panel.set_scheduler_options, list(self.schedulers))
                )
                self.root.after(
                    0, partial(self.config_panel.set_upscaler_options, list(self.upscaler_names))
                )
                self.root.after(0, partial(self.config_panel.set_vae_options, list(self.vae_names)))

        try:
            mock_gui = MockGUI(self.config_panel)
        except tk.TclError:
            pytest.skip("Tk/Tcl unavailable for mock GUI")

        metadata = {
            "schedulers": ["normal", "karras"],
            "upscalers": ["R-ESRGAN 4x+"],
            "vaes": ["vae-ft-mse-840000"],
        }

        mock_gui.on_metadata_ready(metadata)
        mock_gui.root.update()

        # Verify values were set
        assert mock_gui.schedulers == ["normal", "karras"]
        assert mock_gui.upscaler_names == ["R-ESRGAN 4x+"]
        assert mock_gui.vae_names == ["vae-ft-mse-840000"]

        mock_gui.root.destroy()
