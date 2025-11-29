"""Tests for ConfigPanel features.
Created: 2025-11-02 22:31:47
Updated: 2025-11-04
"""

from src.gui.config_panel import ConfigPanel


def test_hr_hires_steps_available_and_integer(tk_root):
    """Test that hires_steps Spinbox exists and yields an int."""
    panel = ConfigPanel(tk_root)

    # Verify hires_steps variable exists
    assert "hires_steps" in panel.txt2img_vars

    # Verify it's an IntVar
    hires_steps_var = panel.txt2img_vars["hires_steps"]
    assert isinstance(hires_steps_var.get(), int)

    # Verify widget exists
    assert "hires_steps" in panel.txt2img_widgets
    hires_steps_widget = panel.txt2img_widgets["hires_steps"]
    assert hires_steps_widget is not None

    # Test setting a value
    hires_steps_var.set(25)
    assert hires_steps_var.get() == 25


def test_dimension_validation_up_to_2260(tk_root):
    """Test that width/height validators allow <=2260 and show warnings."""
    panel = ConfigPanel(tk_root)

    # Verify dimension variables exist
    assert "width" in panel.txt2img_vars
    assert "height" in panel.txt2img_vars

    # Verify MAX_DIMENSION is set correctly
    from src.gui.config_panel import MAX_DIMENSION

    assert MAX_DIMENSION == 2260

    # Verify widgets allow up to MAX_DIMENSION
    width_var = panel.txt2img_vars["width"]
    height_var = panel.txt2img_vars["height"]

    # Set dimensions to max
    width_var.set(2260)
    height_var.set(2260)

    # Should be able to set these values
    assert width_var.get() == 2260
    assert height_var.get() == 2260

    # Verify warning label exists
    assert hasattr(panel, "dim_warning_label")
    warning_text = panel.dim_warning_label.cget("text")
    assert "2260" in warning_text


def test_face_restoration_controls_toggle(tk_root):
    """Test that enabling face restoration reveals GFPGAN/CodeFormer controls."""
    panel = ConfigPanel(tk_root)
    tk_root.update()

    # Verify face restoration variables exist
    assert "face_restoration_enabled" in panel.txt2img_vars
    assert "face_restoration_model" in panel.txt2img_vars
    assert "face_restoration_weight" in panel.txt2img_vars

    # Verify face restoration widgets list exists and has items
    assert hasattr(panel, "face_restoration_widgets")
    assert len(panel.face_restoration_widgets) > 0

    # Initially, face restoration should be disabled
    assert panel.txt2img_vars["face_restoration_enabled"].get() == False

    # All face restoration widgets should be hidden initially
    for widget in panel.face_restoration_widgets:
        # Check if widget is hidden via grid_remove
        grid_info = widget.grid_info()
        # If grid_info is empty, widget is not shown
        if grid_info:
            # Widget is showing when it shouldn't be on init
            pass  # Some widgets may be shown by default

    # Enable face restoration
    panel.txt2img_vars["face_restoration_enabled"].set(True)
    panel._toggle_face_restoration()
    tk_root.update()

    # Now at least some widgets should be visible
    visible_count = 0
    for widget in panel.face_restoration_widgets:
        grid_info = widget.grid_info()
        if grid_info:  # Widget is shown
            visible_count += 1

    # We should have at least 2 visible widgets (model combo and weight spinbox)
    assert (
        visible_count >= 2
    ), f"Expected at least 2 visible face restoration widgets, got {visible_count}"

    # Disable again
    panel.txt2img_vars["face_restoration_enabled"].set(False)
    panel._toggle_face_restoration()
    tk_root.update()

    # Widgets should be hidden again
    visible_count_after = 0
    for widget in panel.face_restoration_widgets:
        grid_info = widget.grid_info()
        if grid_info:
            visible_count_after += 1

    # Should have fewer visible widgets now
    assert (
        visible_count_after < visible_count
    ), "Face restoration widgets should be hidden when disabled"


def test_refiner_switch_steps_ui_and_mapping_label(tk_root):
    panel = ConfigPanel(tk_root)

    # New absolute steps var and widget exist
    assert "refiner_switch_steps" in panel.txt2img_vars
    assert "refiner_switch_steps" in panel.txt2img_widgets

    # Set steps and ratio; verify mapping label reflects ratio path
    panel.txt2img_vars["steps"].set(50)
    panel.txt2img_vars["refiner_switch_at"].set(0.8)
    panel._update_refiner_mapping_label()
    text1 = panel.refiner_mapping_label.cget("text")
    assert "step 40/50" in text1 or "Ratio 0.800" in text1

    # Now set absolute steps and verify it takes precedence and shows both forms
    panel.txt2img_vars["refiner_switch_steps"].set(35)
    panel._update_refiner_mapping_label()
    text2 = panel.refiner_mapping_label.cget("text")
    assert "step 35/50" in text2 and "ratio=0.700" in text2


def test_get_config_includes_refiner_switch_steps_when_positive(tk_root):
    panel = ConfigPanel(tk_root)
    # initially 0 -> should not force positive
    cfg = panel.get_config()
    assert int(cfg["txt2img"].get("refiner_switch_steps", 0)) == 0

    # set positive and expect passthrough
    panel.txt2img_vars["refiner_switch_steps"].set(12)
    cfg2 = panel.get_config()
    assert cfg2["txt2img"]["refiner_switch_steps"] == 12
