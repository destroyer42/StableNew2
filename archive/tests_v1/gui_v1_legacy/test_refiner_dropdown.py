"""Test that refiner dropdown is populated with models."""

import pytest

from src.gui.config_panel import ConfigPanel


@pytest.fixture
def config_panel_with_tk(tk_root):
    """Create a ConfigPanel for testing."""
    panel = ConfigPanel(tk_root, coordinator=None)
    return panel


def test_refiner_dropdown_populated_with_models(config_panel_with_tk):
    """Test that set_model_options populates the refiner dropdown."""
    panel = config_panel_with_tk

    test_models = [
        "sd_xl_base_1.0.safetensors",
        "sd_xl_refiner_1.0.safetensors",
        "juggernautXL_v9.safetensors",
    ]

    # Call set_model_options
    panel.set_model_options(test_models)

    # Verify refiner dropdown was populated
    refiner_combo = panel.txt2img_widgets.get("refiner_checkpoint")
    assert refiner_combo is not None, "Refiner checkpoint widget should exist"

    values = refiner_combo["values"]
    assert len(values) == 4, f"Expected 4 values (None + 3 models), got {len(values)}"
    assert values[0] == "None", "First value should be 'None'"
    assert "sd_xl_base_1.0.safetensors" in values
    assert "sd_xl_refiner_1.0.safetensors" in values
    assert "juggernautXL_v9.safetensors" in values


def test_refiner_dropdown_handles_empty_models(config_panel_with_tk):
    """Test that refiner dropdown handles empty model list gracefully."""
    panel = config_panel_with_tk

    # Call with empty list
    panel.set_model_options([])

    # Verify refiner dropdown still has "None" option
    refiner_combo = panel.txt2img_widgets.get("refiner_checkpoint")
    assert refiner_combo is not None

    values = refiner_combo["values"]
    assert len(values) == 1, f"Expected 1 value (just None), got {len(values)}"
    assert values[0] == "None"


def test_refiner_dropdown_filters_empty_strings(config_panel_with_tk):
    """Test that refiner dropdown filters out empty/whitespace model names."""
    panel = config_panel_with_tk

    test_models = [
        "model1.safetensors",
        "",  # Empty string
        "   ",  # Whitespace
        "model2.ckpt",
        None,  # None value
    ]

    panel.set_model_options(test_models)

    refiner_combo = panel.txt2img_widgets.get("refiner_checkpoint")
    values = refiner_combo["values"]

    # Should only have None + 2 valid models
    assert len(values) == 3, f"Expected 3 values, got {len(values)}: {values}"
    assert values[0] == "None"
    assert "model1.safetensors" in values
    assert "model2.ckpt" in values
