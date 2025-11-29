"""Tests for PipelineControlsPanel get_settings method.
Created: 2025-11-02 22:31:47
Updated: 2025-11-04
"""

from src.gui.pipeline_controls_panel import PipelineControlsPanel


def test_pipeline_controls_returns_settings_dict(tk_root):
    """Test that get_settings() returns dict with toggles and loop settings."""
    panel = PipelineControlsPanel(tk_root)

    # Get settings
    settings = panel.get_settings()

    # Verify it returns a dictionary
    assert isinstance(settings, dict)

    # Verify required keys are present
    assert "txt2img_enabled" in settings
    assert "img2img_enabled" in settings
    assert "upscale_enabled" in settings
    assert "video_enabled" in settings
    assert "loop_type" in settings
    assert "loop_count" in settings
    assert "pack_mode" in settings
    assert "images_per_prompt" in settings

    # Verify default values
    assert settings["txt2img_enabled"] == True
    assert settings["img2img_enabled"] == True
    assert settings["upscale_enabled"] == True
    assert isinstance(settings["loop_count"], int)
    assert isinstance(settings["images_per_prompt"], int)
