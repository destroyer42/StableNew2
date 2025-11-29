"""Tests for PipelineControlsPanel component."""

import os
import sys
import unittest

# Handle headless testing
if sys.platform.startswith("linux") and "DISPLAY" not in os.environ:
    os.environ["DISPLAY"] = ":99"

import tkinter as tk

from src.gui.pipeline_controls_panel import PipelineControlsPanel


class TestPipelineControlsPanel(unittest.TestCase):
    """Test suite for PipelineControlsPanel."""

    def setUp(self):
        """Set up test fixtures."""
        try:
            self.root = tk.Tk()
            self.root.withdraw()
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
        """Test that the PipelineControlsPanel can be instantiated."""
        panel = PipelineControlsPanel(self.root, style="Dark.TFrame")

        # Assert that the panel is created and is a ttk.Frame
        from tkinter import ttk

        self.assertIsInstance(panel, ttk.Frame)
        self.assertIsNotNone(panel)

    def test_default_settings(self):
        """Test that default settings are correct."""
        panel = PipelineControlsPanel(self.root)
        settings = panel.get_settings()

        # Check defaults
        self.assertTrue(settings["txt2img_enabled"])
        self.assertTrue(settings["img2img_enabled"])
        self.assertTrue(settings["upscale_enabled"])
        self.assertFalse(settings["video_enabled"])
        self.assertEqual(settings["loop_type"], "single")
        self.assertEqual(settings["loop_count"], 1)
        self.assertEqual(settings["pack_mode"], "selected")
        self.assertEqual(settings["images_per_prompt"], 1)
        self.assertEqual(settings["variant_mode"], "fanout")

    def test_toggle_stages(self):
        """Test toggling stage checkboxes."""
        panel = PipelineControlsPanel(self.root)

        # Toggle txt2img off
        panel.txt2img_enabled.set(False)
        settings = panel.get_settings()
        self.assertFalse(settings["txt2img_enabled"])

        # Toggle video on
        panel.video_enabled.set(True)
        settings = panel.get_settings()
        self.assertTrue(settings["video_enabled"])

        # Toggle multiple
        panel.img2img_enabled.set(False)
        panel.upscale_enabled.set(False)
        settings = panel.get_settings()
        self.assertFalse(settings["img2img_enabled"])
        self.assertFalse(settings["upscale_enabled"])

    def test_loop_type_selection(self):
        """Test loop type radio button selection."""
        panel = PipelineControlsPanel(self.root)

        # Default should be single
        settings = panel.get_settings()
        self.assertEqual(settings["loop_type"], "single")

        # Change to stages
        panel.loop_type_var.set("stages")
        settings = panel.get_settings()
        self.assertEqual(settings["loop_type"], "stages")

        # Change to pipeline
        panel.loop_type_var.set("pipeline")
        settings = panel.get_settings()
        self.assertEqual(settings["loop_type"], "pipeline")

    def test_loop_count(self):
        """Test loop count spinbox."""
        panel = PipelineControlsPanel(self.root)

        # Set loop count to 5
        panel.loop_count_var.set("5")
        settings = panel.get_settings()
        self.assertEqual(settings["loop_count"], 5)

        # Set to maximum
        panel.loop_count_var.set("100")
        settings = panel.get_settings()
        self.assertEqual(settings["loop_count"], 100)

        # Invalid value should default to 1
        panel.loop_count_var.set("invalid")
        settings = panel.get_settings()
        self.assertEqual(settings["loop_count"], 1)

    def test_pack_mode_selection(self):
        """Test pack mode radio button selection."""
        panel = PipelineControlsPanel(self.root)

        # Default should be selected
        settings = panel.get_settings()
        self.assertEqual(settings["pack_mode"], "selected")

        # Change to all
        panel.pack_mode_var.set("all")
        settings = panel.get_settings()
        self.assertEqual(settings["pack_mode"], "all")

        # Change to custom
        panel.pack_mode_var.set("custom")
        settings = panel.get_settings()
        self.assertEqual(settings["pack_mode"], "custom")

    def test_images_per_prompt(self):
        """Test images per prompt spinbox."""
        panel = PipelineControlsPanel(self.root)

        # Set to 3
        panel.images_per_prompt_var.set("3")
        settings = panel.get_settings()
        self.assertEqual(settings["images_per_prompt"], 3)

        # Set to maximum
        panel.images_per_prompt_var.set("10")
        settings = panel.get_settings()
        self.assertEqual(settings["images_per_prompt"], 10)

        # Invalid value should default to 1
        panel.images_per_prompt_var.set("abc")
        settings = panel.get_settings()
        self.assertEqual(settings["images_per_prompt"], 1)

    def test_get_settings_returns_dict(self):
        """Test that get_settings returns a properly structured dict."""
        panel = PipelineControlsPanel(self.root)
        settings = panel.get_settings()

        # Check that it's a dictionary
        self.assertIsInstance(settings, dict)

        # Check all required keys are present
        required_keys = [
            "txt2img_enabled",
            "img2img_enabled",
            "upscale_enabled",
            "video_enabled",
            "loop_type",
            "loop_count",
            "pack_mode",
            "images_per_prompt",
            "model_matrix",
            "hypernetworks",
            "variant_mode",
        ]
        for key in required_keys:
            self.assertIn(key, settings)

    def test_set_settings(self):
        """Test setting multiple settings at once."""
        panel = PipelineControlsPanel(self.root)

        new_settings = {
            "txt2img_enabled": False,
            "img2img_enabled": False,
            "upscale_enabled": False,
            "video_enabled": True,
            "loop_type": "pipeline",
            "loop_count": 5,
            "pack_mode": "all",
            "images_per_prompt": 3,
        }

        panel.set_settings(new_settings)
        current_settings = panel.get_settings()

        # Verify all settings were applied
        for key, value in new_settings.items():
            self.assertEqual(current_settings[key], value)

    def test_set_settings_partial(self):
        """Test setting only some settings."""
        panel = PipelineControlsPanel(self.root)

        # Set only a few settings
        partial_settings = {"loop_type": "stages", "loop_count": 10}

        panel.set_settings(partial_settings)
        settings = panel.get_settings()

        # Check that partial settings were applied
        self.assertEqual(settings["loop_type"], "stages")
        self.assertEqual(settings["loop_count"], 10)

        # Check that other settings remain at defaults
        self.assertTrue(settings["txt2img_enabled"])
        self.assertEqual(settings["pack_mode"], "selected")

    def test_complex_scenario(self):
        """Test a complex scenario with multiple setting changes."""
        panel = PipelineControlsPanel(self.root)

        # Configure for a specific workflow
        panel.txt2img_enabled.set(True)
        panel.img2img_enabled.set(False)  # Skip img2img
        panel.upscale_enabled.set(True)
        panel.video_enabled.set(True)
        panel.loop_type_var.set("pipeline")
        panel.loop_count_var.set("3")
        panel.pack_mode_var.set("all")
        panel.images_per_prompt_var.set("2")

        settings = panel.get_settings()

        # Verify the complex configuration
        self.assertTrue(settings["txt2img_enabled"])
        self.assertFalse(settings["img2img_enabled"])
        self.assertTrue(settings["upscale_enabled"])
        self.assertTrue(settings["video_enabled"])
        self.assertEqual(settings["loop_type"], "pipeline")
        self.assertEqual(settings["loop_count"], 3)
        self.assertEqual(settings["pack_mode"], "all")
        self.assertEqual(settings["images_per_prompt"], 2)

    def test_variant_matrix_parsing(self):
        panel = PipelineControlsPanel(self.root)
        panel.model_matrix_var.set("modelA, modelB")
        panel.hypernetworks_var.set("HN1:0.5, HN2")
        panel.variant_mode_var.set("rotate")

        settings = panel.get_settings()
        self.assertEqual(settings["model_matrix"], ["modelA", "modelB"])
        self.assertEqual(
            settings["hypernetworks"],
            [
                {"name": "HN1", "strength": 0.5},
                {"name": "HN2", "strength": 1.0},
            ],
        )
        self.assertEqual(settings["variant_mode"], "rotate")


if __name__ == "__main__":
    unittest.main()
